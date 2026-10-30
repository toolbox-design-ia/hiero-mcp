"""Wire protocol shared by the Hiero listener and the MCP server.

Messages are UTF-8 JSON objects, one per line, over a localhost TCP socket.

Request:  {"id": 1, "command": "list_projects", "params": {...}, "token": "..."}
Response: {"id": 1, "ok": true, "result": ...}
          {"id": 1, "ok": false, "error": {"type": "...", "message": "...", "traceback": "..."}}

This module only uses the standard library because it runs inside Hiero's
bundled Python as well as in the MCP server's environment.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any, BinaryIO

PROTOCOL_VERSION = 1
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7392
MAX_MESSAGE_BYTES = 64 * 1024 * 1024


def config_dir() -> Path:
    return Path(os.environ.get("HIERO_MCP_HOME", "~/.hiero_mcp")).expanduser()


def token_path(name: str = "token") -> Path:
    return config_dir() / name


def load_token(create: bool = False, name: str = "token", env_var: str = "HIERO_MCP_TOKEN") -> str | None:
    """Return a secret from ``env_var`` or ``<config dir>/<name>``.

    With ``create=True`` a new random token is written (mode 0600) when none exists.
    """
    env = os.environ.get(env_var)
    if env:
        return env.strip()
    path = token_path(name)
    if path.is_file():
        return path.read_text(encoding="utf-8").strip() or None
    if not create:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(token)
    return token


def resolve_port(port: int | None = None) -> int:
    if port is not None:
        return int(port)
    return int(os.environ.get("HIERO_MCP_PORT", DEFAULT_PORT))


def resolve_host(host: str | None = None) -> str:
    return host or os.environ.get("HIERO_MCP_HOST", DEFAULT_HOST)


def encode(message: dict[str, Any]) -> bytes:
    return json.dumps(message, default=str, separators=(",", ":")).encode("utf-8") + b"\n"


def read_message(stream: BinaryIO) -> dict[str, Any] | None:
    """Read one message; ``None`` means the peer closed the connection."""
    line = stream.readline(MAX_MESSAGE_BYTES + 1)
    if not line:
        return None
    if len(line) > MAX_MESSAGE_BYTES:
        raise ValueError("message exceeds %d bytes" % MAX_MESSAGE_BYTES)
    message = json.loads(line.decode("utf-8"))
    if not isinstance(message, dict):
        raise ValueError("message must be a JSON object")
    return message
