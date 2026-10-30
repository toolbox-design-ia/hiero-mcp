from __future__ import annotations

from typing import Any, Iterator

import pytest

from hiero_mcp.bridge import BridgeClient
from hiero_mcp.hiero_plugin.hiero_mcp_bridge import listener

TOKEN = "test-token"


def _fake_commands() -> dict[str, Any]:
    def ping() -> dict[str, Any]:
        return {"pong": True}

    def list_projects() -> list[dict[str, Any]]:
        return [{"name": "demo", "path": "/tmp/demo.hrox", "modified": False}]

    def get_sequence(sequence: str | None = None, project: str | None = None, include_items: bool = False) -> dict[str, Any]:
        if sequence == "missing":
            raise LookupError("Sequence not found: 'missing'")
        return {"name": sequence or "active", "include_items": include_items}

    return {"ping": ping, "list_projects": list_projects, "get_sequence": get_sequence}


@pytest.fixture()
def hiero_listener(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Iterator[tuple[str, int]]:
    """A real listener on a free port, running fake commands inline instead of in Hiero."""
    monkeypatch.setenv("HIERO_MCP_HOME", str(tmp_path))
    monkeypatch.delenv("HIERO_MCP_TOKEN", raising=False)
    address = listener.start(host="127.0.0.1", port=0, commands=_fake_commands(), token=TOKEN, run_on_main=listener.run_inline)
    try:
        yield address
    finally:
        listener.stop()


@pytest.fixture()
def bridge(hiero_listener: tuple[str, int]) -> Iterator[BridgeClient]:
    host, port = hiero_listener
    client = BridgeClient(host=host, port=port, token=TOKEN, timeout=5)
    try:
        yield client
    finally:
        client.close()
