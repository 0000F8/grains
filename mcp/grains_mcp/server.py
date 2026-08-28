"""Grains MCP server: exposes the control-plane API as MCP tools.

Auth model (v1): every tool call acts as ONE grains user, authenticated by that
user's deploy token (a "grains_dt_..." string) supplied via GRAINS_DEPLOY_TOKEN.
This is a bootstrap, not a full OAuth authorization-server flow -- hosted OAuth
at mcp.grains.run (dynamic client registration, per-request user tokens) is a
follow-up once this wedge is validated.

Tool functions are implemented as private module-level functions (`_scaffold`,
`_deploy`, ...) that take an explicit `client: GrainsClient` (or no client, for
the pure-local `_scaffold`) instead of closing over global state. `build_server`
wires them up as FastMCP tools. Tests call the private functions directly with a
fake client, so no MCP transport is needed to exercise the tool logic.
"""
from __future__ import annotations

import argparse
import os
import re
import time
from decimal import Decimal, InvalidOperation

from grains_cli.templates import render_app, render_toml
from mcp.server.fastmcp import FastMCP

from .client import GrainsAPIError, GrainsClient, zip_files

_VALID_FRAMEWORKS = ("none", "crewai", "langchain", "langgraph")
_REQUIRED_DEPLOY_FILES = ("grains_app.py", "grains.toml")
_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def _slugify(text: str) -> str:
    """Turn free-form text into an agent-name-ish slug for the scaffolded toml."""
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)
    if not slug or not slug[0].isalpha():
        slug = "my-agent"
    return slug[:39]


def _api_error(action: str, exc: GrainsAPIError) -> str:
    return f"error: {action} failed ({exc.status}): {exc.body!r}"


# -- tool implementations (no FastMCP dependency; directly testable) -------


def _scaffold(description: str, framework: str = "none") -> dict:
    fw = framework if framework in _VALID_FRAMEWORKS else "none"
    slug = _slugify(description)
    files = {"grains_app.py": render_app(fw), "grains.toml": render_toml(slug)}
    notes = f"Generated a '{fw}' wrapper (suggested agent name: '{slug}')."
    if fw != "none":
        notes += " Edit the marked TODO import in grains_app.py to point at your real object."
    notes += " Call grains_deploy with these files (and a chosen agent name) to ship it."
    return {"files": files, "notes": notes}


def _deploy(client: GrainsClient, name: str, files: dict[str, str]):
    missing = [f for f in _REQUIRED_DEPLOY_FILES if f not in files]
    if missing:
        return f"error: files must include {', '.join(_REQUIRED_DEPLOY_FILES)} (missing: {', '.join(missing)})"

    created = None
    try:
        created = client.create_agent(name)
    except GrainsAPIError as exc:
        if exc.status != 409:
            return _api_error(f"create agent '{name}'", exc)
        created = None  # already exists -- fine, deploy to it

    zip_bytes = zip_files({fname: content.encode("utf-8") for fname, content in files.items()})
    try:
        deployed = client.deploy_zip(name, zip_bytes)
    except GrainsAPIError as exc:
        return _api_error(f"deploy '{name}'", exc)

    deployment = deployed.get("deployment", deployed)
    result = {"status": deployment.get("status"), "deployment": deployment}
    if created is not None:
        result["did"] = created.get("agent", {}).get("did")
        result["identity_doc"] = created.get("identity_doc")
    return result


def _list_agents(client: GrainsClient):
    try:
        return client.list_agents()
    except GrainsAPIError as exc:
        return _api_error("list agents", exc)


def _agent_status(client: GrainsClient, name: str):
    try:
        return client.get_agent(name)
    except GrainsAPIError as exc:
        return _api_error(f"get agent '{name}'", exc)


def _logs(client: GrainsClient, name: str, limit: int = 50):
    try:
        return client.get_logs(name, limit)
    except GrainsAPIError as exc:
        return _api_error(f"get logs for '{name}'", exc)


def _secret_set(client: GrainsClient, name: str, secret_name: str, value: str):
    try:
        client.put_secret(name, secret_name, value)
    except GrainsAPIError as exc:
        return _api_error(f"set secret '{secret_name}' on '{name}'", exc)
    return {"ok": True, "name": secret_name}  # value is intentionally never echoed back


def _set_price(client: GrainsClient, name: str, price_value=None, public: bool | None = None):
    if price_value is not None:
        if not isinstance(price_value, str):
            return "error: price_value must be a decimal string (e.g. '1.50'), not a number"
        try:
            parsed = Decimal(price_value)
        except InvalidOperation:
            return f"error: price_value '{price_value}' is not a valid decimal string"
        # Decimal() accepts 'nan'/'inf'/'infinity' without raising; reject them
        # or a non-finite price would reach the billing rail.
        if not parsed.is_finite() or parsed < 0:
            return f"error: price_value '{price_value}' must be a finite, non-negative amount"

    fields: dict = {}
    if price_value is not None:
        fields["price_value"] = price_value
    if public is not None:
        fields["public"] = public
    if not fields:
        return "error: nothing to update; pass price_value and/or public"

    try:
        return client.patch_agent(name, **fields)
    except GrainsAPIError as exc:
        return _api_error(f"update price/visibility for '{name}'", exc)


def _invoke(
    client: GrainsClient,
    name: str,
    text: str,
    timeout_s: int = 60,
    sleep_fn=time.sleep,
):
    try:
        agent = client.get_agent(name)
    except GrainsAPIError as exc:
        return _api_error(f"get agent '{name}'", exc)

    token = None
    if not agent.get("agent", {}).get("public", False):
        try:
            token = client.create_caller_token(name).get("token")
        except GrainsAPIError as exc:
            return _api_error(f"create caller token for '{name}'", exc)

    try:
        submitted = client.submit_task(name, text, caller_token=token)
    except GrainsAPIError as exc:
        return _api_error(f"submit task to '{name}'", exc)

    task_id = submitted.get("task_id")
    if not task_id:
        return "error: submit_task response missing task_id"

    iterations = max(1, timeout_s // 2)
    last: dict = {}
    for _ in range(iterations):
        try:
            last = client.get_task(name, task_id, token=token)
        except GrainsAPIError as exc:
            return _api_error(f"poll task '{task_id}'", exc)
        if last.get("status") in ("done", "failed"):
            return {"status": last["status"], "reply": last.get("reply"), "error": last.get("error")}
        sleep_fn(2)

    return {
        "status": "timeout",
        "reply": None,
        "error": f"task '{task_id}' did not complete within {timeout_s}s",
    }


# -- FastMCP wiring ----------------------------------------------------------


def build_server(client, *, max_invoke_timeout_s: int | None = None) -> FastMCP:
    """`client` is a GrainsClient (stdio: one user for the process lifetime) or
    a zero-arg factory returning one (hosted: a fresh client per tool call,
    bound to the calling request's bearer token -- see remote.py).

    `max_invoke_timeout_s` caps grains_invoke's poll budget. The stdio server
    can wait as long as the user asked; the hosted server runs inside a 30s
    Lambda/API-GW window and must return its own timeout payload before the
    platform kills the invocation with an opaque 504.
    """
    client_factory = client if callable(client) else (lambda: client)
    mcp = FastMCP("grains")

    @mcp.tool()
    def grains_scaffold(description: str, framework: str = "none") -> dict:
        """Generate grains_app.py + grains.toml content locally (no API call)."""
        return _scaffold(description, framework)

    @mcp.tool()
    def grains_deploy(name: str, files: dict[str, str]):
        """Create the agent if needed, zip `files`, and deploy them."""
        return _deploy(client_factory(), name, files)

    @mcp.tool()
    def grains_list_agents():
        """List agents owned by the authenticated deploy token."""
        return _list_agents(client_factory())

    @mcp.tool()
    def grains_agent_status(name: str):
        """Get an agent's current status."""
        return _agent_status(client_factory(), name)

    @mcp.tool()
    def grains_logs(name: str, limit: int = 50):
        """Fetch recent log events for an agent."""
        return _logs(client_factory(), name, limit)

    @mcp.tool()
    def grains_secret_set(name: str, secret_name: str, value: str):
        """Set (upsert) a secret on an agent. The value is never echoed back."""
        return _secret_set(client_factory(), name, secret_name, value)

    @mcp.tool()
    def grains_invoke(name: str, text: str, timeout_s: int = 60):
        """Invoke an agent with a text task and poll until it completes or times out."""
        if max_invoke_timeout_s is not None:
            timeout_s = min(timeout_s, max_invoke_timeout_s)
        return _invoke(client_factory(), name, text, timeout_s)

    @mcp.tool()
    def grains_set_price(name: str, price_value: str | None = None, public: bool | None = None):
        """Update an agent's price (decimal string) and/or public visibility."""
        return _set_price(client_factory(), name, price_value, public)

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(prog="grains-mcp", description="Grains MCP deploy server")
    parser.add_argument(
        "--http", action="store_true", help="serve streamable-http instead of stdio"
    )
    parser.add_argument("--port", type=int, default=8931, help="port to use with --http")
    args = parser.parse_args()

    base_url = os.environ.get("GRAINS_API_URL")
    deploy_token = os.environ.get("GRAINS_DEPLOY_TOKEN")
    if not base_url:
        raise SystemExit("GRAINS_API_URL is required")
    if not deploy_token:
        raise SystemExit("GRAINS_DEPLOY_TOKEN is required")

    client = GrainsClient(base_url=base_url, deploy_token=deploy_token)
    mcp = build_server(client)

    if args.http:
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
