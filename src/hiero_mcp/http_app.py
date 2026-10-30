"""Streamable HTTP transport with token authentication, for remote clients behind a tunnel."""

from __future__ import annotations

import hmac
import json
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp, Receive, Scope, Send

from .hiero_plugin.hiero_mcp_bridge import protocol

HTTP_TOKEN_FILE = "http_token"
HTTP_TOKEN_ENV = "HIERO_MCP_HTTP_TOKEN"
MCP_PATH = "/mcp"


def load_http_token(create: bool = True) -> str | None:
    return protocol.load_token(create=create, name=HTTP_TOKEN_FILE, env_var=HTTP_TOKEN_ENV)


class TokenAuthMiddleware:
    """Accept a request if it carries the token, either way:

    - ``Authorization: Bearer <token>`` for clients that can send headers;
    - a ``/<token>`` path prefix (``https://host/<token>/mcp``) for clients that only take a URL.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token
        self.prefix = "/" + token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":  # lifespan events
            await self.app(scope, receive, send)
            return

        path: str = scope["path"]
        if path == self.prefix or path.startswith(self.prefix + "/"):
            inner = path[len(self.prefix) :] or "/"
            await self.app({**scope, "path": inner, "raw_path": inner.encode()}, receive, send)
            return

        auth = _header(scope, b"authorization")
        if auth[:7].lower() == "bearer " and hmac.compare_digest(auth[7:].strip(), self.token):
            await self.app(scope, receive, send)
            return

        await _unauthorized(send)


def _header(scope: Scope, name: bytes) -> str:
    for key, value in scope.get("headers", ()):
        if key.lower() == name:
            return value.decode("latin-1")
    return ""


async def _unauthorized(send: Send) -> None:
    body = json.dumps({"error": "unauthorized", "hint": "send Authorization: Bearer <token> or use the /<token>/mcp URL"}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})


def build_http_app(mcp: MCPServer, token: str | None) -> Any:
    """The MCP app, wrapped in token auth unless ``token`` is None.

    With a token, Host/Origin checks are turned off so the server works behind a tunnel
    (Cloudflare, ngrok) under any hostname: the token is what keeps other people out.
    Without one, the SDK's localhost-only DNS-rebinding protection stays on.
    """
    if token is None:
        return mcp.streamable_http_app(streamable_http_path=MCP_PATH, host="127.0.0.1")
    security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    app = mcp.streamable_http_app(streamable_http_path=MCP_PATH, transport_security=security)
    return TokenAuthMiddleware(app, token)
