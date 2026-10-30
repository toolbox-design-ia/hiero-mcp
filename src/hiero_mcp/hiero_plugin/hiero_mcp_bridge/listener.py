"""TCP listener that runs inside Hiero and executes commands on its main thread."""

from __future__ import annotations

import hmac
import socketserver
import threading
import traceback
from typing import Any, Callable

from . import protocol

Command = Callable[..., Any]
MainThreadRunner = Callable[[Callable[[], Any]], Any]

_server: "_BridgeServer | None" = None
_thread: threading.Thread | None = None


def run_in_hiero_main_thread(fn: Callable[[], Any]) -> Any:
    """Run ``fn`` on Hiero's main thread and return its result or re-raise its error."""
    import hiero.core

    box: dict[str, Any] = {}

    def call() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # re-raised in the caller's thread
            box["error"] = exc

    hiero.core.executeInMainThreadWithResult(call)
    if "error" in box:
        raise box["error"]
    return box.get("result")


def run_inline(fn: Callable[[], Any]) -> Any:
    return fn()


class _Handler(socketserver.StreamRequestHandler):
    server: "_BridgeServer"

    def handle(self) -> None:
        while True:
            try:
                request = protocol.read_message(self.rfile)
            except (ValueError, UnicodeDecodeError) as exc:
                self._send({"id": None, "ok": False, "error": {"type": "ProtocolError", "message": str(exc)}})
                return
            if request is None:
                return
            self._send(self.server.dispatch(request))

    def _send(self, message: dict[str, Any]) -> None:
        self.wfile.write(protocol.encode(message))
        self.wfile.flush()


class _BridgeServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        commands: dict[str, Command],
        token: str | None,
        run_on_main: MainThreadRunner,
    ) -> None:
        super().__init__(address, _Handler)
        self.commands = commands
        self.token = token
        self.run_on_main = run_on_main

    def dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        rid = request.get("id")
        if self.token and not hmac.compare_digest(str(request.get("token") or ""), self.token):
            return _error(rid, "AuthenticationError", "invalid or missing token")

        name = request.get("command")
        if name == "hello":
            return {"id": rid, "ok": True, "result": {"protocol": protocol.PROTOCOL_VERSION, "commands": sorted(self.commands)}}
        command = self.commands.get(name)
        if command is None:
            return _error(rid, "UnknownCommand", "unknown command: %r" % (name,))

        params = request.get("params") or {}
        if not isinstance(params, dict):
            return _error(rid, "TypeError", "params must be an object")
        try:
            result = self.run_on_main(lambda: command(**params))
        except Exception as exc:
            return _error(rid, type(exc).__name__, str(exc), traceback.format_exc())
        return {"id": rid, "ok": True, "result": result}


def _error(rid: Any, kind: str, message: str, tb: str | None = None) -> dict[str, Any]:
    error = {"type": kind, "message": message}
    if tb:
        error["traceback"] = tb
    return {"id": rid, "ok": False, "error": error}


def start(
    host: str | None = None,
    port: int | None = None,
    commands: dict[str, Command] | None = None,
    token: str | None = None,
    run_on_main: MainThreadRunner | None = None,
) -> tuple[str, int]:
    """Start the listener in a daemon thread and return the bound address."""
    global _server, _thread
    if _server is not None:
        return _server.server_address[:2]

    if commands is None:
        from .commands import COMMANDS as commands
    if token is None:
        token = protocol.load_token(create=True)

    _server = _BridgeServer(
        (protocol.resolve_host(host), protocol.resolve_port(port)),
        commands,
        token,
        run_on_main or run_in_hiero_main_thread,
    )
    _thread = threading.Thread(target=_server.serve_forever, name="hiero-mcp-bridge", daemon=True)
    _thread.start()
    return _server.server_address[:2]


def stop() -> None:
    global _server, _thread
    if _server is None:
        return
    _server.shutdown()
    _server.server_close()
    _server = None
    _thread = None


def is_running() -> bool:
    return _server is not None
