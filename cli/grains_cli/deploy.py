"""`grains deploy` / `grains logs` / `grains agents` — CLI control-plane commands."""
from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

from .apiclient import GrainsAPIError, GrainsClient, resolve_api, resolve_token, zip_project


def _client_or_exit(args) -> GrainsClient:
    token = resolve_token(getattr(args, "token", None))
    if not token:
        print("error: provide --token or set GRAINS_DEPLOY_TOKEN "
              "(get one at https://api.grains.run/welcome)", file=sys.stderr)
        raise SystemExit(2)
    return GrainsClient(resolve_api(getattr(args, "api", None)), token)


def _agent_name(path: Path) -> str:
    toml_path = path / "grains.toml"
    if not toml_path.exists():
        print(f"error: no grains.toml in {path} (run `grains init` first)", file=sys.stderr)
        raise SystemExit(2)
    return tomllib.loads(toml_path.read_text())["agent"]["name"]


def cmd_deploy(args: argparse.Namespace) -> int:
    path = Path(args.path).resolve()
    name = _agent_name(path)
    client = _client_or_exit(args)
    try:
        try:
            client.create_agent(name)
            print(f"created agent {name}")
        except GrainsAPIError as e:
            if e.status != 409:  # already exists is fine
                raise
        result = client.deploy(name, zip_project(path))
    except GrainsAPIError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    dep = result.get("deployment", result)
    status = dep.get("status")
    print(f"deployed {name}: {status}")
    if dep.get("error"):
        print(f"  error: {dep['error']}", file=sys.stderr)
        return 1
    return 0 if status == "live" else 1


def cmd_logs(args: argparse.Namespace) -> int:
    client = _client_or_exit(args)
    try:
        events = client.logs(args.name, args.limit).get("events", [])
    except GrainsAPIError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if not events:
        print("(no logs)")
    for e in events:
        print(e.get("message", ""))
    return 0


def cmd_agents(args: argparse.Namespace) -> int:
    client = _client_or_exit(args)
    try:
        agents = client.list_agents().get("agents", [])
    except GrainsAPIError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if not agents:
        print("(no agents)")
    for a in agents:
        price = f" {a['price_value']} {a.get('price_currency', 'USDC')}" if a.get("price_value") else ""
        vis = "public" if a.get("public") else "private"
        print(f"{a['name']:<24} {a.get('status', ''):<8} {vis}{price}")
    return 0


def cmd_balance(args: argparse.Namespace) -> int:
    client = _client_or_exit(args)
    try:
        data = client._req("GET", "/v1/balance")
    except GrainsAPIError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    agents = data.get("agents", [])
    if not agents:
        print("No paid calls yet. Set a price with `grains_set_price` in Claude "
              "or from the dashboard, and this fills up.")
        return 0
    cur = data.get("currency", "USDC")
    print(f"{'agent':<24} {'calls':>6} {'gross':>12} {'fee':>10} {'net':>12}")
    for a in agents:
        print(f"{a['agent']:<24} {a['calls']:>6} {a['gross']:>12} {a['fee']:>10} {a['net']:>12}")
    t = data["total"]
    print("-" * 68)
    print(f"{'total':<24} {'':>6} {t['gross']:>12} {t['fee']:>10} {t['net']:>12}  {cur}")
    return 0
