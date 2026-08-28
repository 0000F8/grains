"""client.py tests: verify requests are built correctly and responses parsed,
against httpx.MockTransport -- no real network.
"""
from __future__ import annotations

import json

import httpx
import pytest
from grains_mcp.client import GrainsAPIError, GrainsClient, zip_files


def _client(handler) -> GrainsClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    return GrainsClient(base_url="https://api.example.test", deploy_token="grains_dt_abc", http=http)


def test_create_agent_posts_name_and_bearer_auth():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"agent": {"id": "1", "name": "foo", "did": "did:x"}})

    client = _client(handler)
    result = client.create_agent("foo")

    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.example.test/v1/agents"
    assert captured["auth"] == "Bearer grains_dt_abc"
    assert captured["body"] == {"name": "foo"}
    assert result["agent"]["name"] == "foo"


def test_get_agent_builds_path():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.example.test/v1/agents/foo"
        return httpx.Response(200, json={"agent": {"name": "foo"}})

    client = _client(handler)
    assert client.get_agent("foo")["agent"]["name"] == "foo"


def test_get_logs_passes_limit_query_param():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/agents/foo/logs"
        assert request.url.params["limit"] == "25"
        return httpx.Response(200, json={"events": []})

    client = _client(handler)
    assert client.get_logs("foo", limit=25) == {"events": []}


def test_patch_agent_sends_only_provided_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert json.loads(request.content) == {"public": True}
        return httpx.Response(200, json={"agent": {"public": True}})

    client = _client(handler)
    result = client.patch_agent("foo", public=True)
    assert result["agent"]["public"] is True


def test_put_secret_sends_name_and_value():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert str(request.url) == "https://api.example.test/v1/agents/foo/secrets"
        assert json.loads(request.content) == {"name": "API_KEY", "value": "shh"}
        return httpx.Response(200, json={"name": "API_KEY"})

    client = _client(handler)
    assert client.put_secret("foo", "API_KEY", "shh") == {"name": "API_KEY"}


def test_deploy_zip_sends_raw_bytes_with_zip_content_type():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://api.example.test/v1/agents/foo/deployments"
        assert request.headers["content-type"] == "application/zip"
        assert request.content == b"PK\x03\x04zipbytes"
        return httpx.Response(202, json={"deployment": {"id": "d1", "status": "live"}})

    client = _client(handler)
    result = client.deploy_zip("foo", b"PK\x03\x04zipbytes")
    assert result["deployment"]["status"] == "live"


def test_create_caller_token():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.example.test/v1/agents/foo/caller-tokens"
        return httpx.Response(201, json={"id": "t1", "token": "grains_ct_x"})

    client = _client(handler)
    assert client.create_caller_token("foo")["token"] == "grains_ct_x"


def test_submit_task_uses_caller_token_when_given():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.example.test/agents/foo/tasks"
        assert request.headers["authorization"] == "Bearer grains_ct_x"
        assert json.loads(request.content) == {"text": "hi", "payload": {}}
        return httpx.Response(202, json={"task_id": "task1"})

    client = _client(handler)
    result = client.submit_task("foo", "hi", caller_token="grains_ct_x")
    assert result == {"task_id": "task1"}


def test_submit_task_falls_back_to_deploy_token():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer grains_dt_abc"
        return httpx.Response(202, json={"task_id": "task1"})

    client = _client(handler)
    client.submit_task("foo", "hi")


def test_get_task_returns_status_and_reply():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.example.test/agents/foo/tasks/task1"
        return httpx.Response(
            200,
            json={"task_id": "task1", "status": "done", "reply": {"text": "hi"}, "charges": None, "error": None},
        )

    client = _client(handler)
    result = client.get_task("foo", "task1", token="grains_ct_x")
    assert result["status"] == "done"
    assert result["reply"] == {"text": "hi"}


def test_non_2xx_raises_grains_api_error_with_json_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "agent name already taken"})

    client = _client(handler)
    with pytest.raises(GrainsAPIError) as excinfo:
        client.create_agent("dup")
    assert excinfo.value.status == 409
    assert excinfo.value.body == {"detail": "agent name already taken"}


def test_non_2xx_raises_grains_api_error_with_text_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    client = _client(handler)
    with pytest.raises(GrainsAPIError) as excinfo:
        client.get_agent("foo")
    assert excinfo.value.status == 500
    assert "internal error" in excinfo.value.body


def test_204_response_returns_empty_dict():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    client = _client(handler)
    assert client.get_agent("foo") == {}


def test_zip_files_builds_valid_zip_with_expected_members():
    import zipfile
    from io import BytesIO

    data = zip_files({"grains_app.py": b"print('hi')", "grains.toml": b"[agent]\n"})
    with zipfile.ZipFile(BytesIO(data)) as zf:
        names = set(zf.namelist())
        assert names == {"grains_app.py", "grains.toml"}
        assert zf.read("grains_app.py") == b"print('hi')"
