from __future__ import annotations

import httpx
import pytest

from hiero_mcp import server
from hiero_mcp.http_app import build_http_app

TOKEN = "s3cret"
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}},
}
HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


async def _post(app, path: str, headers: dict[str, str] | None = None, host: str = "hiero.example.com") -> httpx.Response:
    """POST an MCP initialize. Each app's session manager can only start once, so build a fresh app per call."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=f"https://{host}") as client:
        # The session manager needs the app's lifespan running.
        async with _lifespan(app):
            return await client.post(path, json=INIT, headers={**HEADERS, **(headers or {})})


class _lifespan:
    """Drive the ASGI lifespan protocol by hand (httpx's transport does not)."""

    def __init__(self, app) -> None:
        self.app = app

    async def __aenter__(self):
        import anyio

        self._send_stream, receive_stream = anyio.create_memory_object_stream(10)
        self._events_send, self._events = anyio.create_memory_object_stream(10)

        async def receive():
            return await receive_stream.receive()

        async def send(message):
            await self._events_send.send(message)

        self._tg = anyio.create_task_group()
        await self._tg.__aenter__()
        self._tg.start_soon(self.app, {"type": "lifespan", "asgi": {"version": "3.0"}}, receive, send)
        await self._send_stream.send({"type": "lifespan.startup"})
        assert (await self._events.receive())["type"] == "lifespan.startup.complete"
        return self

    async def __aexit__(self, *exc):
        await self._send_stream.send({"type": "lifespan.shutdown"})
        await self._events.receive()
        await self._tg.__aexit__(*exc)


@pytest.fixture()
def app():
    return build_http_app(server.mcp, TOKEN)


def _fresh():
    return build_http_app(server.mcp, TOKEN)


async def test_rejects_requests_without_token(app) -> None:
    response = await _post(app, "/mcp")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_rejects_wrong_token(app) -> None:
    assert (await _post(app, "/mcp", {"authorization": "Bearer nope"})).status_code == 401
    assert (await _post(_fresh(), "/nope/mcp")).status_code == 401


async def test_bearer_header_works_under_any_host(app) -> None:
    response = await _post(app, "/mcp", {"authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200, response.text
    assert "hiero" in response.text


async def test_token_in_path_works(app) -> None:
    response = await _post(app, f"/{TOKEN}/mcp")
    assert response.status_code == 200, response.text


async def test_no_auth_mode_only_accepts_localhost() -> None:
    assert (await _post(build_http_app(server.mcp, None), "/mcp", host="127.0.0.1:8765")).status_code == 200
    assert (await _post(build_http_app(server.mcp, None), "/mcp", host="evil.example.com")).status_code == 421
