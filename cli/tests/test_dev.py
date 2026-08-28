import json
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from grains_cli.dev import serve
from grains_cli.init import cmd_init
from grains_cli.main import build_parser

FIXTURES = Path(__file__).resolve().parent.parent.parent / "fixtures"
DEADLINE_S = 10.0
POLL_INTERVAL_S = 0.05


def _post_json(base_url, path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        base_url + path, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read())


def _get_json(base_url, path):
    with urllib.request.urlopen(base_url + path) as resp:
        return resp.status, json.loads(resp.read())


def _wait_for_done(base_url, task_id):
    deadline = time.monotonic() + DEADLINE_S
    while time.monotonic() < deadline:
        _, body = _get_json(base_url, f"/tasks/{task_id}")
        if body["status"] in ("done", "failed"):
            return body
        time.sleep(POLL_INTERVAL_S)
    raise AssertionError(f"task {task_id} did not finish within {DEADLINE_S}s")


@pytest.fixture
def running_server(tmp_path):
    servers = []

    def _start(project_dir):
        server = serve(str(project_dir), port=0)
        servers.append(server)
        host, port = server.server_address
        return f"http://{host}:{port}"

    yield _start

    for server in servers:
        server.shutdown()
        server.server_close()


def test_healthz(running_server, tmp_path):
    project = tmp_path / "agent"
    shutil.copytree(FIXTURES / "template_agent", project)
    base_url = running_server(project)
    status, body = _get_json(base_url, "/healthz")
    assert status == 200
    assert body == {"status": "ok"}


def test_template_agent_echoes(running_server, tmp_path):
    project = tmp_path / "agent"
    shutil.copytree(FIXTURES / "template_agent", project)
    base_url = running_server(project)

    status, body = _post_json(base_url, "/tasks", {"text": "hello world", "payload": {}})
    assert status == 202
    task_id = body["task_id"]

    result = _wait_for_done(base_url, task_id)
    assert result["status"] == "done"
    assert result["reply"]["text"] == "echo: hello world"
    assert result["error"] is None


def test_crewai_retrofit_via_real_init(running_server, tmp_path):
    project = tmp_path / "crewai_project"
    shutil.copytree(FIXTURES / "crewai_example", project)

    rc = cmd_init(build_parser().parse_args(["init", str(project)]))
    assert rc == 0

    app_path = project / "grains_app.py"
    content = app_path.read_text()
    content = content.replace(
        "from your_project.crew import your_crew  # noqa: F401",
        "from my_project.crew import research_crew",
    )
    content = content.replace("your_crew", "research_crew")
    app_path.write_text(content)

    assert len(content.splitlines()) <= 25
    compile(content, str(app_path), "exec")

    base_url = running_server(project)
    status, body = _post_json(base_url, "/tasks", {"text": "market trends", "payload": {}})
    assert status == 202
    task_id = body["task_id"]

    result = _wait_for_done(base_url, task_id)
    assert result["status"] == "done"
    assert result["reply"]["text"] == "research result for: market trends"


def test_failed_handler_reports_error(running_server, tmp_path):
    project = tmp_path / "broken_agent"
    project.mkdir()
    (project / "grains_app.py").write_text(
        "from grains import Task\n\n\ndef handle(task: Task):\n    raise ValueError('boom')\n"
    )
    (project / "grains.toml").write_text(
        '[agent]\nname = "broken"\nentrypoint = "grains_app:handle"\n'
        'runtime = "python3.12"\npublic = false\n\n'
        "[secrets]\nnames = []\n\n[egress]\nallow = []\n"
    )
    base_url = running_server(project)

    status, body = _post_json(base_url, "/tasks", {"text": "hi", "payload": {}})
    assert status == 202
    task_id = body["task_id"]

    result = _wait_for_done(base_url, task_id)
    assert result["status"] == "failed"
    assert "boom" in result["error"]
    assert result["reply"] is None


def test_get_unknown_task_returns_404(running_server, tmp_path):
    project = tmp_path / "agent"
    shutil.copytree(FIXTURES / "template_agent", project)
    base_url = running_server(project)
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _get_json(base_url, "/tasks/does-not-exist")
    assert exc_info.value.code == 404


def test_ephemeral_port_is_nonzero(running_server, tmp_path):
    project = tmp_path / "agent"
    shutil.copytree(FIXTURES / "template_agent", project)
    base_url = running_server(project)
    assert base_url.rsplit(":", 1)[1] != "0"


def test_post_non_object_json_returns_400(running_server, tmp_path):
    project = tmp_path / "agent"
    shutil.copytree(FIXTURES / "template_agent", project)
    base = running_server(project)
    req = urllib.request.Request(
        base + "/tasks", data=b"null", headers={"Content-Type": "application/json"}, method="POST"
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 400


def test_charges_surfaced_in_task_record(running_server, tmp_path):
    project = tmp_path / "charger"
    project.mkdir()
    (project / "grains_app.py").write_text(
        "from grains import agent\n\n\n"
        "@agent.handler\n"
        "def handle(task):\n"
        "    task.charge(\"5.00\")\n"
        "    return task.reply(\"charged\")\n"
    )
    (project / "grains.toml").write_text(
        '[agent]\nname = "charger"\nentrypoint = "grains_app:handle"\n'
        'runtime = "python3.12"\npublic = false\n'
    )
    base = running_server(project)
    _, body = _post_json(base, "/tasks", {"text": "go"})
    record = _wait_for_done(base, body["task_id"])
    assert record["status"] == "done"
    assert record["charges"] == [{"value": "5.00", "currency": "USDC"}]


def test_dev_runs_node_agent(running_server, tmp_path):
    import shutil
    if not shutil.which("node"):
        import pytest
        pytest.skip("node not available")
    project = tmp_path / "nodeagent"
    project.mkdir()
    (project / "grains_app.mjs").write_text(
        "export function handle(task) {\n  return task.reply('node echo: ' + task.text);\n}\n"
    )
    (project / "grains.toml").write_text(
        '[agent]\nname = "n"\nentrypoint = "grains_app:handle"\nruntime = "nodejs20.x"\npublic = false\n'
    )
    base = running_server(project)
    _, body = _post_json(base, "/tasks", {"text": "hi"})
    record = _wait_for_done(base, body["task_id"])
    assert record["status"] == "done"
    assert record["reply"]["text"] == "node echo: hi"
