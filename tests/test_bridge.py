from __future__ import annotations

import pytest

from hiero_mcp.bridge import BridgeClient, HieroConnectionError, HieroError


def test_call_returns_result(bridge: BridgeClient) -> None:
    assert bridge.call("ping") == {"pong": True}


def test_none_params_are_dropped(bridge: BridgeClient) -> None:
    assert bridge.call("get_sequence", sequence=None, include_items=True) == {"name": "active", "include_items": True}


def test_hello_lists_commands(bridge: BridgeClient) -> None:
    hello = bridge.call("hello")
    assert hello["protocol"] == 1
    assert "list_projects" in hello["commands"]


def test_command_error_is_raised(bridge: BridgeClient) -> None:
    with pytest.raises(HieroError) as info:
        bridge.call("get_sequence", sequence="missing")
    assert info.value.kind == "LookupError"
    assert "Traceback" in (info.value.traceback or "")


def test_unknown_command(bridge: BridgeClient) -> None:
    with pytest.raises(HieroError, match="UnknownCommand"):
        bridge.call("format_disk")


def test_bad_params_are_reported(bridge: BridgeClient) -> None:
    with pytest.raises(HieroError, match="TypeError"):
        bridge.call("ping", unexpected=1)


def test_wrong_token_is_rejected(hiero_listener: tuple[str, int]) -> None:
    host, port = hiero_listener
    client = BridgeClient(host=host, port=port, token="nope", timeout=5)
    with pytest.raises(HieroConnectionError, match="token"):
        client.call("ping")
    client.close()


def test_connection_survives_many_calls(bridge: BridgeClient) -> None:
    for _ in range(50):
        assert bridge.call("ping") == {"pong": True}


def test_reconnects_after_close(bridge: BridgeClient) -> None:
    bridge.call("ping")
    bridge.close()
    assert bridge.call("ping") == {"pong": True}


def test_hiero_not_running() -> None:
    client = BridgeClient(host="127.0.0.1", port=1, token="x", timeout=1)
    with pytest.raises(HieroConnectionError, match="Cannot reach Hiero"):
        client.call("ping")
