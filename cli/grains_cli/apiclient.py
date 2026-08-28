"""Minimal Grains control-plane client for the CLI (deploy/logs/agents).

Authenticated by a deploy token (--token or GRAINS_DEPLOY_TOKEN). Kept
self-contained so grains-cli doesn't depend on grains-mcp.
"""
from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import httpx

DEFAULT_API = "https://api.grains.run"


class GrainsAPIError(Exception):
    def __init__(self, status: int, body):
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body


def resolve_api(explicit: str | None) -> str:
    return (explicit or os.environ.get("GRAINS_API_URL") or DEFAULT_API).rstrip("/")


def resolve_token(explicit: str | None) -> str | None:
    if explicit or os.environ.get("GRAINS_DEPLOY_TOKEN"):
        return explicit or os.environ.get("GRAINS_DEPLOY_TOKEN")
    from .login import stored_token  # lazy: avoid import cycle
    return stored_token(resolve_api(None))


def zip_project(path: Path) -> bytes:
    """Zip an agent project: grains.toml + grains_app.* + any other files,
    skipping caches/VCS/virtualenvs."""
    skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "dist", "build",
                 ".pytest_cache", ".ruff_cache", ".egg-info"}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(path.rglob("*")):
            if f.is_dir():
                continue
            if any(part in skip_dirs or part.endswith(".egg-info") for part in f.relative_to(path).parts):
                continue
            zf.write(f, f.relative_to(path).as_posix())
    return buf.getvalue()


class GrainsClient:
    def __init__(self, api: str, token: str, http: httpx.Client | None = None):
        self.api = api.rstrip("/")
        self.token = token
        self.http = http if http is not None else httpx.Client(timeout=120.0)

    def _req(self, method: str, path: str, **kw):
        headers = {"Authorization": f"Bearer {self.token}"}
        headers.update(kw.pop("headers", None) or {})
        r = self.http.request(method, self.api + path, headers=headers, **kw)
        if r.status_code >= 400:
            try:
                body = r.json()
            except ValueError:
                body = r.text
            raise GrainsAPIError(r.status_code, body)
        return {} if r.status_code == 204 or not r.content else r.json()

    def create_agent(self, name: str) -> dict:
        return self._req("POST", "/v1/agents", json={"name": name})

    def deploy(self, name: str, zip_bytes: bytes) -> dict:
        return self._req("POST", f"/v1/agents/{name}/deployments",
                         content=zip_bytes, headers={"Content-Type": "application/zip"})

    def list_agents(self) -> dict:
        return self._req("GET", "/v1/agents")

    def logs(self, name: str, limit: int = 50) -> dict:
        return self._req("GET", f"/v1/agents/{name}/logs?limit={limit}")
