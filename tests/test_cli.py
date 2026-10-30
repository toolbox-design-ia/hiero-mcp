from __future__ import annotations

import ast
from pathlib import Path

import pytest

from hiero_mcp import cli


def test_install_and_uninstall_plugin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIERO_MCP_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("HIERO_MCP_TOKEN", raising=False)
    nuke = tmp_path / ".nuke"

    cli.install_plugin(nuke)
    startup = nuke / "Python" / "Startup" / "hiero_mcp_startup.py"
    assert startup.is_file()
    assert (nuke / "hiero_mcp_bridge" / "commands.py").is_file()
    assert not list((nuke / "hiero_mcp_bridge").rglob("__pycache__"))
    token = tmp_path / "home" / "token"
    assert token.is_file() and oct(token.stat().st_mode & 0o777) == "0o600"

    # The startup hook resolves the bridge relative to itself: <nuke>/Python/Startup -> <nuke>.
    assert Path(startup).parents[2] == nuke

    removed = cli.uninstall_plugin(nuke)
    assert len(removed) == 2 and not startup.exists()


def test_plugin_sources_are_python_311_compatible() -> None:
    """The bridge runs on Hiero 17's bundled Python 3.11."""
    for path in cli.PLUGIN_SRC.rglob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), feature_version=(3, 11))


def test_bare_invocation_means_serve(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}
    monkeypatch.setattr(cli, "_serve", lambda args: seen.update(vars(args)))
    cli.main(["--transport", "http", "--port", "9000"])
    assert seen["transport"] == "http" and seen["port"] == 9000
