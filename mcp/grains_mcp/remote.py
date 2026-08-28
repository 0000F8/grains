"""Hosted (streamable-HTTP) grains MCP server with per-request bearer auth.

The stdio server in `server.py` acts as ONE user for its whole lifetime (token
from env). Hosted at mcp.grains.run, every HTTP request instead carries its own
`Authorization: Bearer grains_dt_...` and must act as THAT token's user. The
pieces here stay platform-agnostic -- the control plane injects `verify_token`
(it owns the deploy_tokens table) and mounts the returned ASGI app.

Auth flow per request:
  BearerAuthMiddleware extracts + verifies the token (401 with a
  WWW-Authenticate resource_metadata pointer otherwise -- the MCP spec's
  OAuth discovery entrypoint), stashes it in a ContextVar, and the
  client factory builds a GrainsClient bound to it for each tool call.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Callable

import httpx

from .client import GrainsClient
from .server import build_server

_REQUEST_TOKEN: ContextVar[str | None] = ContextVar("grains_request_token", default=None)


def current_token() -> str:
    token = _REQUEST_TOKEN.get()
    if token is None:  # middleware guarantees this never happens for tool calls
        raise RuntimeError("no bearer token bound to this request")
    return token


#: Self-calls must finish well inside the 30s Lambda/API-GW budget.
HOSTED_HTTP_TIMEOUT_S = 15.0

#: grains_invoke poll cap for the hosted server (see build_server docstring).
HOSTED_MAX_INVOKE_TIMEOUT_S = 20


def make_client_factory(
    api_base_url: str, http: httpx.Client | None = None
) -> Callable[[], GrainsClient]:
    """Per-call GrainsClient bound to the current request's bearer token.

    One shared httpx.Client (connection pool, hosted-appropriate timeout)
    backs every per-request GrainsClient -- identity rides per-call headers,
    never client state, so sharing the pool is safe.
    """
    if http is None:
        http = httpx.Client(timeout=HOSTED_HTTP_TIMEOUT_S)

    def factory() -> GrainsClient:
        return GrainsClient(api_base_url, current_token(), http=http)

    return factory


class BearerAuthMiddleware:
    """Pure-ASGI: require a valid grains deploy token on every http request.

    401 responses carry `WWW-Authenticate: Bearer resource_metadata="..."` so
    MCP clients (Claude Code) can discover the OAuth authorization server per
    RFC 9728 instead of dead-ending.
    """

    def __init__(self, app, verify_token: Callable[[str], bool], resource_metadata_url: str):
        self.app = app
        self.verify_token = verify_token
        self.resource_metadata_url = resource_metadata_url

    async def _unauthorized(self, send, detail: str) -> None:
        body = json.dumps({"error": "invalid_token", "error_description": detail}).encode()
        www = f'Bearer resource_metadata="{self.resource_metadata_url}"'
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"www-authenticate", www.encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        auth = ""
        for name, value in scope.get("headers") or []:
            if name == b"authorization":
                auth = value.decode("latin-1")
                break
        scheme, _, token = auth.partition(" ")
        if scheme.lower() != "bearer" or not token:
            await self._unauthorized(send, "missing bearer token")
            return
        token = token.strip()
        if not self.verify_token(token):
            await self._unauthorized(send, "invalid or revoked deploy token")
            return
        reset = _REQUEST_TOKEN.set(token)
        try:
            await self.app(scope, receive, send)
        finally:
            _REQUEST_TOKEN.reset(reset)


class RemoteMCP:
    """Mountable hosted-MCP endpoint with a re-entrant lifespan.

    StreamableHTTPSessionManager.run() is once-per-instance, but serverless
    adapters (Mangum) enter the app lifespan on EVERY invocation. Each
    lifespan entry therefore builds a fresh manager (+ Starlette app) on the
    current event loop; the mounted object is a stable shim delegating to
    whichever build is live. Stateless mode means no session survives a
    request anyway, so rebuilding per entry loses nothing.
    """

    def __init__(
        self,
        api_base_url: str,
        verify_token: Callable[[str], bool],
        resource_metadata_url: str,
        http: httpx.Client | None = None,
    ):
        self.server = build_server(
            make_client_factory(api_base_url, http=http),
            max_invoke_timeout_s=HOSTED_MAX_INVOKE_TIMEOUT_S,
        )
        # DNS-rebinding protection guards ambient-credential setups (cookies,
        # localhost). Every request here presents a bearer token, so Host
        # allow-listing adds nothing -- and would break API GW's execute-api
        # hostname and local tests.
        from mcp.server.transport_security import TransportSecuritySettings

        self.server.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        )
        self.server.settings.stateless_http = True
        self.server.settings.json_response = True
        self.server.settings.streamable_http_path = "/"  # mount path is the caller's
        self.verify_token = verify_token
        self.resource_metadata_url = resource_metadata_url
        self._current = None

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("method") == "GET":
            # Stateless JSON mode has no server-push channel; answering the
            # SSE GET would hold the connection open until the platform
            # timeout (a 30s Lambda burn per probe). Refuse fast -- clients
            # treat a 405 as "no push channel" and continue POST-only.
            body = b'{"error":"method_not_allowed"}'
            await send({
                "type": "http.response.start",
                "status": 405,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"allow", b"POST, DELETE"),
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return
        if self._current is None:
            raise RuntimeError("RemoteMCP.lifespan() is not running")
        await self._current(scope, receive, send)

    @asynccontextmanager
    async def lifespan(self):
        # Force a fresh manager bound to *this* event loop. The SDK caches
        # _session_manager (the Starlette app is rebuilt each call); resetting
        # the private attr is its only rebuild hook.
        self.server._session_manager = None
        inner = self.server.streamable_http_app()
        app = BearerAuthMiddleware(inner, self.verify_token, self.resource_metadata_url)
        async with self.server.session_manager.run():
            self._current = app
            try:
                yield
            finally:
                self._current = None
