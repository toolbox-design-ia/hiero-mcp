"""MCP server for Foundry Hiero / Nuke Studio 17."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("hiero-mcp")
except PackageNotFoundError:  # running from a source tree without install
    __version__ = "0.0.0"


def main() -> None:
    from .cli import main as cli_main

    cli_main()
