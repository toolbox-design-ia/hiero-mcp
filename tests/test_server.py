from __future__ import annotations

import ast
from pathlib import Path

import pytest
from mcp.client import Client

from hiero_mcp import server
from hiero_mcp.bridge import BridgeClient

COMMANDS_FILE = Path(server.__file__).parent / "hiero_plugin" / "hiero_mcp_bridge" / "commands.py"


def _bridge_commands() -> dict[str, set[str]]:
    """Names and parameters of every @command in commands.py, read without importing hiero."""
    tree = ast.parse(COMMANDS_FILE.read_text(encoding="utf-8"))
    out = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and any(getattr(d, "id", None) == "command" for d in node.decorator_list):
            out[node.name] = {a.arg for a in node.args.args + node.args.kwonlyargs}
    return out


@pytest.fixture()
def configured(bridge: BridgeClient):
    server.configure(bridge)
    yield
    server.configure(None)  # type: ignore[arg-type]


async def test_every_tool_maps_to_a_bridge_command_with_matching_params() -> None:
    commands = _bridge_commands()
    async with Client(server.mcp) as client:
        tools = (await client.list_tools()).tools
    assert tools
    for tool in tools:
        assert tool.name in commands, f"tool {tool.name} has no bridge command"
        params = set(tool.input_schema.get("properties", {}))
        assert params == commands[tool.name], f"{tool.name}: tool {params} != bridge {commands[tool.name]}"


async def test_every_bridge_command_is_exposed() -> None:
    async with Client(server.mcp) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert set(_bridge_commands()) - names == {"ping"}


async def test_destructive_tools_are_annotated() -> None:
    async with Client(server.mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    for name in ("delete_bin_item", "delete_track", "delete_track_items", "close_project", "execute_python", "run_export"):
        assert tools[name].annotations.destructive_hint is True
    for name in ("list_projects", "get_sequence", "get_track_item"):
        assert tools[name].annotations.read_only_hint is True


async def test_tool_call_goes_through_bridge(configured: None) -> None:
    async with Client(server.mcp) as client:
        result = await client.call_tool("list_projects", {})
    assert not result.is_error
    assert result.structured_content == {"result": [{"name": "demo", "path": "/tmp/demo.hrox", "modified": False}]}


async def test_hiero_errors_become_tool_errors(configured: None) -> None:
    async with Client(server.mcp) as client:
        result = await client.call_tool("get_sequence", {"sequence": "missing"})
    assert result.is_error
    assert "Sequence not found" in result.content[0].text
