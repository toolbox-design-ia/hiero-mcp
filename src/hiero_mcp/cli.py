"""Command line entry point: run the MCP server or manage the Hiero plugin."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from .hiero_plugin.hiero_mcp_bridge import protocol

PLUGIN_SRC = Path(__file__).parent / "hiero_plugin"
STARTUP_FILE = Path("Python") / "Startup" / "hiero_mcp_startup.py"
BRIDGE_DIR = Path("hiero_mcp_bridge")


def _serve(args: argparse.Namespace) -> None:
    from .bridge import BridgeClient
    from .server import configure, mcp

    configure(BridgeClient(host=args.hiero_host, port=args.hiero_port, timeout=args.timeout))
    if args.transport == "stdio":
        mcp.run("stdio")
        return

    import uvicorn

    from .http_app import MCP_PATH, build_http_app, load_http_token

    if args.no_auth and args.host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("--no-auth is only allowed when binding to localhost")
    if not args.allow_python:
        # Over HTTP the server may be reachable from the internet: no arbitrary code by default.
        mcp.remove_tool("execute_python")
    token = None if args.no_auth else load_http_token(create=True)

    base = f"http://{args.host}:{args.port}"
    print(f"hiero-mcp HTTP server on {base}{MCP_PATH}", file=sys.stderr)
    if token:
        print(f"  header auth:  Authorization: Bearer {token}", file=sys.stderr)
        print(f"  URL-only clients:  {base}/{token}{MCP_PATH}  (swap in your tunnel's https host)", file=sys.stderr)
    print(f"  execute_python: {'enabled' if args.allow_python else 'disabled (use --allow-python)'}", file=sys.stderr)
    uvicorn.run(build_http_app(mcp, token), host=args.host, port=args.port, log_level="warning")


def install_plugin(nuke_dir: Path) -> list[Path]:
    """Copy the startup hook and bridge package into a Nuke user directory (~/.nuke)."""
    nuke_dir = nuke_dir.expanduser()
    startup_dst = nuke_dir / STARTUP_FILE
    bridge_dst = nuke_dir / BRIDGE_DIR
    startup_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PLUGIN_SRC / STARTUP_FILE, startup_dst)
    if bridge_dst.exists():
        shutil.rmtree(bridge_dst)
    shutil.copytree(PLUGIN_SRC / BRIDGE_DIR, bridge_dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    protocol.load_token(create=True)
    return [startup_dst, bridge_dst]


def uninstall_plugin(nuke_dir: Path) -> list[Path]:
    nuke_dir = nuke_dir.expanduser()
    removed = []
    startup = nuke_dir / STARTUP_FILE
    if startup.exists():
        startup.unlink()
        removed.append(startup)
    bridge = nuke_dir / BRIDGE_DIR
    if bridge.exists():
        shutil.rmtree(bridge)
        removed.append(bridge)
    return removed


def _install(args: argparse.Namespace) -> None:
    for path in install_plugin(Path(args.nuke_dir)):
        print(f"installed {path}")
    print("Restart Hiero / Nuke Studio to load the plugin.")


def _uninstall(args: argparse.Namespace) -> None:
    removed = uninstall_plugin(Path(args.nuke_dir))
    for path in removed:
        print(f"removed {path}")
    if not removed:
        print("nothing to remove")


def _http_token(args: argparse.Namespace) -> None:
    from .http_app import HTTP_TOKEN_FILE, load_http_token

    if args.rotate:
        protocol.token_path(HTTP_TOKEN_FILE).unlink(missing_ok=True)
    print(load_http_token(create=True))


def _status(args: argparse.Namespace) -> None:
    from .bridge import BridgeClient, HieroConnectionError

    client = BridgeClient(host=args.hiero_host, port=args.hiero_port, timeout=10)
    try:
        info = client.call("get_app_info")
    except HieroConnectionError as exc:
        print(f"not connected: {exc}", file=sys.stderr)
        raise SystemExit(1)
    finally:
        client.close()
    print(json.dumps(info, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hiero-mcp", description="MCP server for Hiero / Nuke Studio 17.")
    sub = parser.add_subparsers(dest="cmd")

    def hiero_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--hiero-host", default=None, help="Hiero listener host (default 127.0.0.1 or $HIERO_MCP_HOST)")
        p.add_argument("--hiero-port", type=int, default=None, help=f"Hiero listener port (default {protocol.DEFAULT_PORT} or $HIERO_MCP_PORT)")

    serve = sub.add_parser("serve", help="run the MCP server (default)")
    serve.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    serve.add_argument("--host", default="127.0.0.1", help="HTTP bind address (http transport)")
    serve.add_argument("--port", type=int, default=8765, help="HTTP port (http transport)")
    serve.add_argument("--timeout", type=float, default=600.0, help="seconds to wait for a Hiero command")
    serve.add_argument("--allow-python", action="store_true", help="expose execute_python over HTTP (always on for stdio)")
    serve.add_argument("--no-auth", action="store_true", help="HTTP without a token (localhost only)")
    hiero_args(serve)
    serve.set_defaults(func=_serve)

    nuke_default = str(Path("~/.nuke"))
    install = sub.add_parser("install-plugin", help="install the Hiero startup plugin")
    install.add_argument("--nuke-dir", default=nuke_default, help="Nuke user directory (default ~/.nuke)")
    install.set_defaults(func=_install)

    uninstall = sub.add_parser("uninstall-plugin", help="remove the Hiero startup plugin")
    uninstall.add_argument("--nuke-dir", default=nuke_default)
    uninstall.set_defaults(func=_uninstall)

    http_token = sub.add_parser("http-token", help="print the HTTP token (creates it if missing); --rotate makes a new one")
    http_token.add_argument("--rotate", action="store_true")
    http_token.set_defaults(func=_http_token)

    status = sub.add_parser("status", help="check the connection to a running Hiero")
    hiero_args(status)
    status.set_defaults(func=_status)
    return parser


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    # `hiero-mcp` and `hiero-mcp --transport http` both mean `serve`.
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
        argv.insert(0, "serve")
    args = build_parser().parse_args(argv)
    args.func(args)
