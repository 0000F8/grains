"""`grains ship` -- the one command: sign in, scaffold, deploy, live.

Collapses the whole funnel: browser sign-in if needed (PKCE, no token
pasting), `grains init` if the directory has no agent yet, deploy, poll
until live, print the endpoint. `uvx grains-cli ship` is the marketing
one-liner; this module has to keep it honest.
"""
from __future__ import annotations

import argparse
import sys
import time
import tomllib
from argparse import Namespace
from pathlib import Path

from . import init as init_cmd
from .apiclient import GrainsAPIError, GrainsClient, resolve_api, zip_project
from .login import ensure_token

POLL_INTERVAL_S = 3
BUILD_TIMEOUT_S = 600  # container-tier first builds take minutes


def _status(client: GrainsClient, name: str, dep: dict) -> str:
    if dep.get("status") != "building":
        return dep.get("status", "unknown")
    # lazy-reconciled container build: poll the deployment until it settles
    dep_id = dep.get("id")
    deadline = time.monotonic() + BUILD_TIMEOUT_S
    while time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL_S)
        cur = client._req("GET", f"/v1/agents/{name}/deployments/{dep_id}")
        status = cur.get("deployment", cur).get("status")
        if status not in ("building", "pending"):
            return status
        print("  building…", flush=True)
    return "timeout"


def cmd_ship(args: argparse.Namespace) -> int:
    path = Path(args.path).resolve()
    api = resolve_api(getattr(args, "api", None))

    try:
        token = ensure_token(api)
    except Exception as e:  # noqa: BLE001
        print(f"error: {e}", file=sys.stderr)
        return 1

    if not (path / "grains.toml").exists():
        print(f"no grains.toml in {path.name}/ -- scaffolding")
        rc = init_cmd.cmd_init(Namespace(path=str(path), force=False, template=None))
        if rc != 0:
            return rc

    name = tomllib.loads((path / "grains.toml").read_text())["agent"]["name"]
    client = GrainsClient(api, token)
    try:
        try:
            client.create_agent(name)
        except GrainsAPIError as e:
            if e.status != 409:
                raise
        result = client.deploy(name, zip_project(path))
    except GrainsAPIError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    dep = result.get("deployment", result)
    status = _status(client, name, dep)
    agents_base = api.replace("api.", "agents.")
    print()
    print(f"  endpoint   {agents_base.removeprefix('https://')}/{name}")
    if result.get("agent", {}).get("did") or dep.get("did"):
        print(f"  identity   {result.get('agent', {}).get('did') or dep.get('did')}")
    print(f"  status     {status}")
    print(f"  dashboard  grains.run/dashboard.html")
    return 0 if status == "live" else 1
