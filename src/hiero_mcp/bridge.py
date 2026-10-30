"""Client for the listener that runs inside Hiero."""

from __future__ import annotations

import itertools
import socket
import threading
from typing import Any

from .hiero_plugin.hiero_mcp_bridge import protocol


class HieroError(RuntimeError):
    """A command reached Hiero and failed there."""

    def __init__(self, kind: str, message: str, traceback: str | None = None) -> None:
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.traceback = traceback


class HieroConnectionError(ConnectionError):
    """Hiero is not running, the plugin is not installed, or the token is wrong."""


class BridgeClient:
    """Blocking, thread-safe client. Reconnects lazily after a dropped connection."""

    def __init__(self, host: str | None = None, port: int | None = None, token: str | None = None, timeout: float = 120.0) -> None:
        self.host = protocol.resolve_host(host)
        self.port = protocol.resolve_port(port)
        self._token = token
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._rfile: Any = None
        self._lock = threading.Lock()
        self._ids = itertools.count(1)

    @property
    def token(self) -> str | None:
        # Read lazily so a token created by Hiero after this process started is picked up.
        return self._token or protocol.load_token()

    def _connect(self) -> None:
        try:
            self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            raise HieroConnectionError(
                f"Cannot reach Hiero at {self.host}:{self.port} ({exc}). "
                "Is Hiero running with the hiero-mcp plugin installed (`hiero-mcp install-plugin`)?"
            ) from exc
        self._rfile = self._sock.makefile("rb")

    def close(self) -> None:
        with self._lock:
            self._close()

    def _close(self) -> None:
        for closable in (self._rfile, self._sock):
            if closable is not None:
                try:
                    closable.close()
                except OSError:
                    pass
        self._sock = self._rfile = None

    def call(self, command: str, **params: Any) -> Any:
        params = {k: v for k, v in params.items() if v is not None}
        request = {"id": next(self._ids), "command": command, "params": params, "token": self.token}
        with self._lock:
            response = self._roundtrip(request, retry=True)
        if not response.get("ok"):
            error = response.get("error") or {}
            kind = error.get("type", "Error")
            if kind == "AuthenticationError":
                raise HieroConnectionError(
                    f"Hiero rejected the token. Make sure both sides use the same token ({protocol.token_path()} or HIERO_MCP_TOKEN)."
                )
            raise HieroError(kind, error.get("message", ""), error.get("traceback"))
        return response.get("result")

    def _roundtrip(self, request: dict[str, Any], retry: bool) -> dict[str, Any]:
        if self._sock is None:
            self._connect()
        assert self._sock is not None
        try:
            self._sock.sendall(protocol.encode(request))
        except OSError as exc:
            # Stale connection (e.g. Hiero restarted): the command never ran, so resend once.
            self._close()
            if retry:
                return self._roundtrip(request, retry=False)
            raise HieroConnectionError(f"Lost connection to Hiero: {exc}") from exc
        try:
            response = protocol.read_message(self._rfile)
        except socket.timeout as exc:
            # The command may still be running in Hiero; never resend it.
            self._close()
            raise HieroConnectionError(f"Hiero did not answer within {self.timeout:.0f}s") from exc
        except (OSError, ValueError) as exc:
            self._close()
            raise HieroConnectionError(f"Lost connection to Hiero: {exc}") from exc
        if response is None:
            self._close()
            if retry:
                return self._roundtrip(request, retry=False)
            raise HieroConnectionError("Hiero closed the connection")
        return response
