"""Thin, typed-ish client over the Grains control-plane HTTP API.

Every method maps 1:1 to a control-plane endpoint. The underlying `httpx.Client`
is injectable so callers (and tests) never need a real network connection.
"""
from __future__ import annotations

import io
import zipfile

import httpx


class GrainsAPIError(Exception):
    """Raised for any non-2xx response from the control plane."""

    def __init__(self, status: int, body):
        self.status = status
        self.body = body
        super().__init__(f"grains API error {status}: {body!r}")


def zip_files(files: dict[str, bytes]) -> bytes:
    """Build an in-memory zip from {filename: content} pairs."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


class GrainsClient:
    """Client acting as one grains user, authenticated by their deploy token."""

    def __init__(self, base_url: str, deploy_token: str, http: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.deploy_token = deploy_token
        self.http = http if http is not None else httpx.Client(timeout=120.0)

    def _headers(self, token: str | None = None) -> dict[str, str]:
        return {"Authorization": f"Bearer {token or self.deploy_token}"}

    def _request(self, method: str, path: str, **kwargs):
        url = f"{self.base_url}{path}"
        resp = self.http.request(method, url, **kwargs)
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = resp.text
            raise GrainsAPIError(resp.status_code, body)
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    # -- agents ------------------------------------------------------------
    def create_agent(self, name: str) -> dict:
        return self._request("POST", "/v1/agents", json={"name": name}, headers=self._headers())

    def list_agents(self) -> dict:
        return self._request("GET", "/v1/agents", headers=self._headers())

    def get_agent(self, name: str) -> dict:
        return self._request("GET", f"/v1/agents/{name}", headers=self._headers())

    def get_logs(self, name: str, limit: int = 50) -> dict:
        return self._request(
            "GET", f"/v1/agents/{name}/logs", params={"limit": limit}, headers=self._headers()
        )

    def patch_agent(self, name: str, **fields) -> dict:
        return self._request("PATCH", f"/v1/agents/{name}", json=fields, headers=self._headers())

    # -- secrets -------------------------------------------------------------
    def put_secret(self, name: str, secret_name: str, value: str) -> dict:
        return self._request(
            "PUT",
            f"/v1/agents/{name}/secrets",
            json={"name": secret_name, "value": value},
            headers=self._headers(),
        )

    # -- deployments ---------------------------------------------------------
    def deploy_zip(self, name: str, zip_bytes: bytes) -> dict:
        headers = self._headers()
        headers["Content-Type"] = "application/zip"
        return self._request(
            "POST", f"/v1/agents/{name}/deployments", content=zip_bytes, headers=headers
        )

    # -- caller tokens / tasks ------------------------------------------------
    def create_caller_token(self, name: str) -> dict:
        return self._request(
            "POST", f"/v1/agents/{name}/caller-tokens", json={}, headers=self._headers()
        )

    def submit_task(
        self, name: str, text: str, payload: dict | None = None, caller_token: str | None = None
    ) -> dict:
        return self._request(
            "POST",
            f"/agents/{name}/tasks",
            json={"text": text, "payload": payload or {}},
            headers=self._headers(caller_token),
        )

    def get_task(self, name: str, task_id: str, token: str | None = None) -> dict:
        return self._request(
            "GET", f"/agents/{name}/tasks/{task_id}", headers=self._headers(token)
        )
