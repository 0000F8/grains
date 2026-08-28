"""Tests for the MCP tool logic layer (server.py's private `_*` functions).

These call the tool implementations directly against a FakeGrainsClient --
no MCP transport, no real network. `build_server` is exercised separately
just to confirm the FastMCP wiring doesn't blow up.
"""
from __future__ import annotations

import tomllib
import zipfile
from io import BytesIO

import pytest
from grains_mcp.client import GrainsAPIError, GrainsClient
from grains_mcp.server import (
    _agent_status,
    _deploy,
    _invoke,
    _list_agents,
    _logs,
    _scaffold,
    _secret_set,
    _set_price,
    build_server,
)


class FakeGrainsClient:
    """Duck-types the GrainsClient surface server.py's tools call, with
    scriptable responses/errors and a call log for assertions.
    """

    def __init__(self):
        self.calls: list[tuple[str, tuple, dict]] = []
        self.agents: dict[str, dict] = {}
        self.deployments: list[tuple[str, bytes]] = []
        self.secrets: dict[tuple[str, str], str] = {}
        self.tasks: dict[str, dict] = {}
        self.create_agent_error: GrainsAPIError | None = None
        self.task_status_sequence: list[str] = []

    def _log(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))

    def create_agent(self, name):
        self._log("create_agent", name)
        if self.create_agent_error is not None:
            raise self.create_agent_error
        agent = {"id": "agent-1", "name": name, "did": f"did:grains:{name}", "public": False}
        self.agents[name] = agent
        return {"agent": agent, "identity_doc": {"did": agent["did"], "spec": "grains-identity/0.1"}}

    def get_agent(self, name):
        self._log("get_agent", name)
        if name not in self.agents:
            raise GrainsAPIError(404, {"detail": "agent not found"})
        return {"agent": self.agents[name]}

    def list_agents(self):
        self._log("list_agents")
        return {"agents": list(self.agents.values())}

    def get_logs(self, name, limit=50):
        self._log("get_logs", name, limit=limit)
        return {"events": []}

    def patch_agent(self, name, **fields):
        self._log("patch_agent", name, **fields)
        self.agents[name].update(fields)
        return {"agent": self.agents[name]}

    def put_secret(self, name, secret_name, value):
        self._log("put_secret", name, secret_name, value)
        self.secrets[(name, secret_name)] = value
        return {"name": secret_name}

    def deploy_zip(self, name, zip_bytes):
        self._log("deploy_zip", name, zip_bytes)
        self.deployments.append((name, zip_bytes))
        return {"deployment": {"id": "dep-1", "status": "live", "artifact_ref": "ref", "error": None}}

    def create_caller_token(self, name):
        self._log("create_caller_token", name)
        return {"id": "ct-1", "token": "grains_ct_fake"}

    def submit_task(self, name, text, payload=None, caller_token=None):
        self._log("submit_task", name, text, payload=payload, caller_token=caller_token)
        task_id = "task-1"
        self.tasks[task_id] = {"task_id": task_id, "status": "queued", "reply": None, "error": None}
        return {"task_id": task_id}

    def get_task(self, name, task_id, token=None):
        self._log("get_task", name, task_id, token=token)
        if self.task_status_sequence:
            status = self.task_status_sequence.pop(0)
            self.tasks[task_id]["status"] = status
            if status == "done":
                self.tasks[task_id]["reply"] = {"text": "42"}
        return self.tasks[task_id]


# -- grains_scaffold ---------------------------------------------------------


@pytest.mark.parametrize("framework", ["none", "crewai", "langchain", "langgraph"])
def test_scaffold_returns_valid_compilable_files(framework):
    result = _scaffold(f"a {framework} agent", framework)
    files = result["files"]
    assert set(files) == {"grains_app.py", "grains.toml"}

    compile(files["grains_app.py"], "grains_app.py", "exec")

    toml_data = tomllib.loads(files["grains.toml"])
    assert toml_data["agent"]["entrypoint"] == "grains_app:handle"

    wrapper_lines = [
        ln for ln in files["grains_app.py"].splitlines() if ln.strip() and not ln.strip().startswith("#")
    ]
    assert len(wrapper_lines) <= 25
    assert "notes" in result


def test_scaffold_unknown_framework_falls_back_to_none():
    result = _scaffold("something weird", framework="not-a-real-framework")
    assert "def handle(task: Task)" in result["files"]["grains_app.py"]
    assert "echo:" in result["files"]["grains_app.py"]


def test_scaffold_derives_a_safe_slug_name():
    result = _scaffold("My Cool Agent!!!", framework="none")
    toml_data = tomllib.loads(result["files"]["grains.toml"])
    name = toml_data["agent"]["name"]
    assert name[0].isalpha()
    assert set(name) <= set("abcdefghijklmnopqrstuvwxyz0123456789-")


# -- grains_deploy ------------------------------------------------------------


def _valid_files():
    return {"grains_app.py": "def handle(task):\n    return task\n", "grains.toml": "[agent]\nname='x'\n"}


def test_deploy_creates_agent_then_deploys_zip():
    client = FakeGrainsClient()
    result = _deploy(client, "newbot", _valid_files())

    assert result["status"] == "live"
    assert result["did"] == "did:grains:newbot"
    assert result["identity_doc"]["did"] == "did:grains:newbot"
    assert [c[0] for c in client.calls] == ["create_agent", "deploy_zip"]

    deployed_name, zip_bytes = client.deployments[0]
    assert deployed_name == "newbot"
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        assert set(zf.namelist()) == {"grains_app.py", "grains.toml"}


def test_deploy_handles_already_taken_409_and_still_deploys():
    client = FakeGrainsClient()
    client.create_agent_error = GrainsAPIError(409, {"detail": "agent name already taken"})

    result = _deploy(client, "existingbot", _valid_files())

    assert result["status"] == "live"
    assert "did" not in result
    assert len(client.deployments) == 1


def test_deploy_propagates_non_409_create_errors():
    client = FakeGrainsClient()
    client.create_agent_error = GrainsAPIError(403, {"detail": "free tier agent limit reached"})

    result = _deploy(client, "bot", _valid_files())

    assert isinstance(result, str)
    assert "error" in result.lower()
    assert not client.deployments


def test_deploy_rejects_missing_required_files():
    client = FakeGrainsClient()
    result = _deploy(client, "bot", {"grains_app.py": "x = 1"})
    assert isinstance(result, str)
    assert "grains.toml" in result
    assert not client.calls


# -- grains_list_agents / grains_agent_status / grains_logs -----------------


def test_list_agents_returns_agents():
    client = FakeGrainsClient()
    client.create_agent("a")
    assert _list_agents(client)["agents"][0]["name"] == "a"


def test_agent_status_wraps_api_error_as_string():
    client = FakeGrainsClient()
    result = _agent_status(client, "nope")
    assert isinstance(result, str)
    assert "404" in result


def test_logs_passes_through():
    client = FakeGrainsClient()
    client.create_agent("a")
    assert _logs(client, "a", limit=10) == {"events": []}


# -- grains_secret_set --------------------------------------------------------


def test_secret_set_never_returns_the_value():
    client = FakeGrainsClient()
    client.create_agent("a")
    result = _secret_set(client, "a", "API_KEY", "super-secret-value")
    assert result == {"ok": True, "name": "API_KEY"}
    assert "super-secret-value" not in str(result)
    assert client.secrets[("a", "API_KEY")] == "super-secret-value"  # still sent to the API


# -- grains_set_price ----------------------------------------------------------


def test_set_price_accepts_decimal_string():
    client = FakeGrainsClient()
    client.create_agent("a")
    result = _set_price(client, "a", price_value="1.50")
    assert result["agent"]["price_value"] == "1.50"


def test_set_price_rejects_float():
    client = FakeGrainsClient()
    client.create_agent("a")
    result = _set_price(client, "a", price_value=1.50)
    assert isinstance(result, str)
    assert "decimal string" in result
    assert "price_value" not in client.agents["a"]


def test_set_price_rejects_malformed_decimal_string():
    client = FakeGrainsClient()
    client.create_agent("a")
    result = _set_price(client, "a", price_value="not-a-number")
    assert isinstance(result, str)


def test_set_price_can_toggle_public_only():
    client = FakeGrainsClient()
    client.create_agent("a")
    result = _set_price(client, "a", public=True)
    assert result["agent"]["public"] is True


def test_set_price_requires_at_least_one_field():
    client = FakeGrainsClient()
    client.create_agent("a")
    result = _set_price(client, "a")
    assert isinstance(result, str)


# -- grains_invoke -------------------------------------------------------------


def test_invoke_polls_until_done():
    client = FakeGrainsClient()
    client.create_agent("a")  # private -> needs a caller token
    client.task_status_sequence = ["queued", "running", "done"]
    sleeps = []

    result = _invoke(client, "a", "hello", timeout_s=60, sleep_fn=sleeps.append)

    assert result == {"status": "done", "reply": {"text": "42"}, "error": None}
    assert sleeps == [2, 2]
    assert any(c[0] == "create_caller_token" for c in client.calls)


def test_invoke_public_agent_skips_caller_token():
    client = FakeGrainsClient()
    client.create_agent("a")
    client.agents["a"]["public"] = True
    client.task_status_sequence = ["done"]

    _invoke(client, "a", "hello", timeout_s=10, sleep_fn=lambda s: None)

    assert not any(c[0] == "create_caller_token" for c in client.calls)


def test_invoke_times_out_with_bounded_iterations():
    client = FakeGrainsClient()
    client.create_agent("a")
    client.agents["a"]["public"] = True
    client.task_status_sequence = []  # never reaches done/failed -> stays "queued"
    sleeps = []

    result = _invoke(client, "a", "hello", timeout_s=6, sleep_fn=sleeps.append)

    assert result["status"] == "timeout"
    assert len(sleeps) == 3  # timeout_s // 2 iterations


def test_invoke_reports_failed_status():
    client = FakeGrainsClient()
    client.create_agent("a")
    client.agents["a"]["public"] = True
    client.task_status_sequence = ["failed"]

    result = _invoke(client, "a", "hello", timeout_s=10, sleep_fn=lambda s: None)

    assert result["status"] == "failed"


# -- build_server (FastMCP wiring only; no transport) -------------------------


def test_build_server_registers_all_tools():
    client = FakeGrainsClient()
    mcp = build_server(client)
    tool_names = set(mcp._tool_manager._tools.keys())
    assert tool_names == {
        "grains_scaffold",
        "grains_deploy",
        "grains_list_agents",
        "grains_agent_status",
        "grains_logs",
        "grains_secret_set",
        "grains_invoke",
        "grains_set_price",
    }


def test_build_server_tool_calls_through_to_client():
    client = FakeGrainsClient()
    client.create_agent("a")
    mcp = build_server(client)
    fn = mcp._tool_manager._tools["grains_agent_status"].fn
    assert fn(name="a")["agent"]["name"] == "a"


def test_build_server_uses_real_client_type_without_error():
    # Confirms GrainsClient itself (not just the fake) is accepted by build_server.
    real_client = GrainsClient(base_url="https://example.test", deploy_token="grains_dt_x")
    mcp = build_server(real_client)
    assert "grains_scaffold" in mcp._tool_manager._tools



def test_set_price_rejects_non_finite():
    from grains_mcp import server as srv

    class C:
        def patch_agent(self, *a, **k):
            raise AssertionError("should not reach the API")

    for bad in ("nan", "Infinity", "-Infinity", "inf", "sNaN", "-1.00"):
        r = srv._set_price(C(), "a", price_value=bad)
        assert isinstance(r, str) and r.startswith("error:"), (bad, r)
