"""MCP egress proxy: call a platform-bound MCP server from agent code.

    result = task.mcp("aws").call_tool("list_instances", region="us-east-1")

The credential and endpoint live in the platform (KMS); this proxy just names
the connector. Configuration is injected by the trusted harness runner from the
task's stdin channel -- never exposed on the Task object user code holds, so a
handler can't read the egress token. Outside the harness (local `grains dev`),
egress is unconfigured and raises a clear error.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

_CFG: dict = {"url": None, "events_url": None, "token": None, "task_id": None}


def configure(egress_url: str | None, events_url: str | None,
              egress_token: str, task_id: str) -> None:
    # The token here authorizes egress + events on THIS task only, never the
    # result callback -- so even though it lives in-process, reading it grants
    # nothing beyond what the handler could already do.
    _CFG.update(url=egress_url, events_url=events_url, token=egress_token, task_id=task_id)


def emit_chunk(chunk: str) -> None:
    """POST one event chunk live (called by Task.emit inside the harness)."""
    if not _CFG.get("events_url"):
        return  # local dev / no harness: batch-only, silently skipped
    body = json.dumps({"chunk": str(chunk)}).encode()
    req = urllib.request.Request(
        f"{_CFG['events_url'].rstrip('/')}/internal/tasks/{_CFG['task_id']}/events",
        data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {_CFG['token']}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except Exception:  # noqa: BLE001 -- streaming is best-effort; never fail the task
        pass


class MCPProxy:
    def __init__(self, name: str):
        self._name = name

    def call_tool(self, tool: str, arguments: dict | None = None, **kwargs) -> dict:
        arguments = {**(arguments or {}), **kwargs}
        if not _CFG["url"]:
            raise RuntimeError(
                "MCP egress is only available for deployed agents; add an 'mcp' "
                "connector to this agent and run it on Grains.")
        body = json.dumps({"task_id": _CFG["task_id"], "name": self._name,
                           "tool": tool, "arguments": arguments}).encode()  # noqa: E501
        req = urllib.request.Request(
            _CFG["url"], data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {_CFG['token']}"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())


def internal_call(path: str, body: dict, timeout: int = 20) -> dict | None:
    """POST an internal control-plane route with the task's egress token.
    Returns parsed JSON, or None when unconfigured (local dev) / on failure --
    memory and history are conveniences, never a reason for a task to die."""
    if not _CFG.get("events_url"):
        return None
    req = urllib.request.Request(
        f"{_CFG['events_url'].rstrip('/')}{path}",
        data=json.dumps({**body, "task_id": _CFG["task_id"]}).encode(),
        method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {_CFG['token']}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode() or "null")
    except urllib.error.HTTPError as e:
        # A refusal is an ANSWER, not a failure: "the account kill switch is
        # on" or "over your daily cap" is exactly what the agent needs to say
        # back to its user. Swallowing it left callers reporting a shrug.
        try:
            err = json.loads(e.read().decode() or "null")
        except Exception:  # noqa: BLE001
            err = None
        detail = err.get("detail") if isinstance(err, dict) else None
        return {"detail": detail or f"refused with HTTP {e.code}", "status": e.code}
    except Exception:  # noqa: BLE001
        return None


class HTTPProxy:
    def __init__(self, name: str):
        self._name = name

    def request(self, method: str, path: str, params: dict | None = None,
                json_body=None) -> dict:
        if not _CFG.get("url"):
            raise RuntimeError(
                "http egress is not configured (local dev, or the agent has "
                "no enabled egress connectors)")
        body = json.dumps({
            "task_id": _CFG["task_id"], "name": self._name,
            "method": method, "path": path, "params": params, "json": json_body,
        }).encode()
        req = urllib.request.Request(
            _CFG["url"], data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {_CFG['token']}"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())

    def get(self, path: str, params: dict | None = None) -> dict:
        return self.request("GET", path, params=params)

    def post(self, path: str, json_body=None) -> dict:
        return self.request("POST", path, json_body=json_body)
