from __future__ import annotations

import argparse
import io
import zipfile
from pathlib import Path

import httpx
from grains_cli import deploy as deploy_cmd
from grains_cli.apiclient import GrainsClient, zip_project


def _project(tmp_path: Path, mjs=False):
    (tmp_path / "grains.toml").write_text('[agent]\nname = "cliagent"\nentrypoint = "grains_app:handle"\nruntime = "python3.12"\npublic = false\n')
    (tmp_path / ("grains_app.mjs" if mjs else "grains_app.py")).write_text("x = 1\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "junk.pyc").write_text("junk")
    return tmp_path


def test_zip_project_skips_caches(tmp_path):
    _project(tmp_path)
    names = zipfile.ZipFile(io.BytesIO(zip_project(tmp_path))).namelist()
    assert "grains.toml" in names and "grains_app.py" in names
    assert not any("__pycache__" in n for n in names)


def test_deploy_creates_then_deploys(tmp_path, monkeypatch):
    _project(tmp_path)
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, req.url.path))
        if req.url.path == "/v1/agents":
            return httpx.Response(201, json={"agent": {"name": "cliagent"}})
        if req.url.path.endswith("/deployments"):
            assert req.headers["content-type"] == "application/zip"
            return httpx.Response(202, json={"deployment": {"status": "live"}})
        return httpx.Response(404)

    client = GrainsClient("https://api.test", "grains_dt_x", http=httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(deploy_cmd, "_client_or_exit", lambda a: client)
    rc = deploy_cmd.cmd_deploy(argparse.Namespace(path=str(tmp_path), token="grains_dt_x", api=None))
    assert rc == 0
    assert ("POST", "/v1/agents") in calls
    assert any(p.endswith("/deployments") for _, p in calls)


def test_deploy_tolerates_existing_agent(tmp_path):
    _project(tmp_path)

    def handler(req):
        if req.url.path == "/v1/agents":
            return httpx.Response(409, json={"detail": "taken"})
        if req.url.path.endswith("/deployments"):
            return httpx.Response(202, json={"deployment": {"status": "live"}})
        return httpx.Response(404)

    client = GrainsClient("https://api.test", "t", http=httpx.Client(transport=httpx.MockTransport(handler)))
    import grains_cli.deploy as d
    orig = d._client_or_exit
    d._client_or_exit = lambda a: client
    try:
        rc = d.cmd_deploy(argparse.Namespace(path=str(tmp_path), token="t", api=None))
    finally:
        d._client_or_exit = orig
    assert rc == 0


def test_deploy_requires_token(tmp_path, monkeypatch, capsys):
    _project(tmp_path)
    monkeypatch.delenv("GRAINS_DEPLOY_TOKEN", raising=False)
    rc = None
    try:
        deploy_cmd.cmd_deploy(argparse.Namespace(path=str(tmp_path), token=None, api=None))
    except SystemExit as e:
        rc = e.code
    assert rc == 2
    assert "welcome" in capsys.readouterr().err
