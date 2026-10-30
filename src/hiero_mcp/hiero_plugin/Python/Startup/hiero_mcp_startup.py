"""Hiero startup hook for hiero-mcp.

Hiero runs every file in <plugin path>/Python/Startup when it launches. This one
puts the bridge package on sys.path and starts the localhost listener so MCP
clients can talk to this Hiero session.

Set HIERO_MCP_DISABLE=1 to skip it for a session.
"""

import os
import sys

_PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _start() -> None:
    if os.environ.get("HIERO_MCP_DISABLE"):
        return
    if _PLUGIN_ROOT not in sys.path:
        sys.path.insert(0, _PLUGIN_ROOT)

    import hiero.core
    import hiero_mcp_bridge

    try:
        host, port = hiero_mcp_bridge.start()
    except OSError as exc:
        hiero.core.log.error("hiero-mcp: could not start listener: %s", exc)
        return
    hiero.core.log.info("hiero-mcp: listening on %s:%s", host, port)


_start()
