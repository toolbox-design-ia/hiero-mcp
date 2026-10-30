# hiero-mcp

An [MCP](https://modelcontextprotocol.io) server for **Foundry Hiero / Nuke Studio 17**. It lets any MCP-capable agent (Claude, ChatGPT / Codex, Gemini and others) read and edit the projects, bins, sequences, tracks, shots, tags, soft effects and exports of a running Hiero session.

```
Agent (Claude / Codex / Gemini / ChatGPT)
        │  MCP (stdio, or HTTP through a tunnel)
        ▼
  hiero-mcp  (this package, Python ≥ 3.11, outside Hiero)
        │  JSON over a TCP socket on 127.0.0.1:7392 + shared token
        ▼
  hiero_mcp_bridge plugin  (inside Hiero, main thread)
        │  hiero.core / hiero.ui
        ▼
     Hiero 17
```

The MCP server runs on the **same machine** as Hiero. Each artist installs the package and registers it with their agent.

## Requirements

- Hiero, Hiero Player or Nuke Studio **17.x** (tested on 17.1v2, Python 3.11).
- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`).

## Installation

The examples install straight from GitHub. If you install from a wheel file instead (for example one downloaded from a website), replace `git+https://github.com/hramirezedc/hiero-mcp` with the wheel's path or URL.

### 1. Hiero plugin (once per machine)

```bash
uvx --from git+https://github.com/hramirezedc/hiero-mcp hiero-mcp install-plugin
```

This copies `hiero_mcp_startup.py` into `~/.nuke/Python/Startup/` and the `hiero_mcp_bridge` package into `~/.nuke/`. It also creates the shared token in `~/.hiero_mcp/token`. Restart Hiero, then check the connection:

```bash
uvx --from git+https://github.com/hramirezedc/hiero-mcp hiero-mcp status
```

To skip the plugin for one session, launch Hiero with `HIERO_MCP_DISABLE=1`. To remove it: `hiero-mcp uninstall-plugin`.

### 2. Register the server with your agent

In every case the command is `uvx --from git+https://github.com/hramirezedc/hiero-mcp hiero-mcp`. Desktop apps don't always inherit your shell `PATH`: if they can't find `uvx`, use its full path (`which uvx`).

**Claude Code**

```bash
claude mcp add hiero -- uvx --from git+https://github.com/hramirezedc/hiero-mcp hiero-mcp
```

**Claude Desktop**: in `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "hiero": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/hramirezedc/hiero-mcp", "hiero-mcp"]
    }
  }
}
```

**OpenAI Codex CLI**: in `~/.codex/config.toml`

```toml
[mcp_servers.hiero]
command = "uvx"
args = ["--from", "git+https://github.com/hramirezedc/hiero-mcp", "hiero-mcp"]
```

**Gemini CLI**: in `~/.gemini/settings.json`

```json
{
  "mcpServers": {
    "hiero": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/hramirezedc/hiero-mcp", "hiero-mcp"]
    }
  }
}
```

## Remote clients (HTTP + Cloudflare Tunnel)

You only need this for clients that run in the cloud and connect by URL, such as ChatGPT connectors or claude.ai. The local agents above use stdio and need no network setup.

**1. Start the HTTP server** on the Hiero machine:

```bash
hiero-mcp --transport http --port 8765
```

It serves `http://127.0.0.1:8765/mcp` and **requires a token**, stored in `~/.hiero_mcp/http_token`. Show it with `hiero-mcp http-token`; replace it with `hiero-mcp http-token --rotate`. A client can send the token in either of two ways:

- `Authorization: Bearer <token>` header, for clients that let you set headers;
- inside the URL, `https://<host>/<token>/mcp`, for clients that only accept a URL. Treat that URL like a password.

Over HTTP, `execute_python` is **disabled** unless you start the server with `--allow-python`.

**2. Expose it with a tunnel.** A Cloudflare Tunnel gives you a public HTTPS address without opening ports on your router.

- To try it out, a quick tunnel gives you a random `https://….trycloudflare.com` address:

  ```bash
  brew install cloudflared
  cloudflared tunnel --url http://127.0.0.1:8765
  ```

- For a fixed address on your own domain, use a named tunnel:

  ```bash
  cloudflared tunnel login
  cloudflared tunnel create hiero
  cloudflared tunnel route dns hiero hiero.example.com
  cloudflared tunnel run --url http://127.0.0.1:8765 hiero
  ```

**3. Connect the client** to `https://hiero.example.com/mcp` with the bearer token, or to `https://hiero.example.com/<token>/mcp`.

The tunnel only provides HTTPS and a public address. The token is what keeps other people out. If you also put the hostname behind Cloudflare Access, the client has to be able to send Access service-token headers; most MCP clients cannot.

## Tools

| Area | Tools |
|---|---|
| Application | `get_app_info`, `list_formats`, `execute_python` |
| Projects | `list_projects`, `get_project`, `new_project`, `open_project`, `save_project`, `close_project`, `undo`, `redo` |
| Bins and clips | `list_bin`, `create_bin`, `import_media`, `get_clip`, `rename_bin_item`, `move_bin_item`, `delete_bin_item`, `set_clip_version`, `reconnect_media` |
| Sequences and tracks | `list_sequences`, `get_sequence`, `create_sequence`, `update_sequence`, `add_track`, `update_track`, `delete_track` |
| Shots | `list_track_items`, `get_track_item`, `add_clip_to_track`, `update_track_item`, `delete_track_items`, `razor`, `add_effect` |
| Tags | `list_project_tags`, `add_tag`, `remove_tag` |
| UI | `get_selection`, `set_selection`, `open_in_timeline`, `open_in_viewer`, `get_playhead`, `set_playhead` |
| Export | `list_export_presets`, `run_export` |

Every change is **one undo step** in Hiero. Tools that delete or overwrite are marked with `destructiveHint`, so agents ask before using them. Trims keep a shot's playback speed, and `move_to` is an absolute timeline frame.

## Configuration

| Variable | Used by | Default |
|---|---|---|
| `HIERO_MCP_PORT` | Hiero and server | `7392` |
| `HIERO_MCP_HOST` | Hiero and server | `127.0.0.1` |
| `HIERO_MCP_TOKEN` | Hiero and server | contents of `~/.hiero_mcp/token` |
| `HIERO_MCP_HTTP_TOKEN` | HTTP server | contents of `~/.hiero_mcp/http_token` |
| `HIERO_MCP_HOME` | Hiero and server | `~/.hiero_mcp` |
| `HIERO_MCP_DISABLE` | Hiero | unset |

## Development

```bash
uv sync
uv run pytest
uv run hiero-mcp status
uv run python scripts/live_check.py   # with Hiero open: runs every tool in a project named "mcp_test"
```

To publish a release on the website, bump `version` in `pyproject.toml`, then run:

```bash
uv run python scripts/release.py --base-url https://<your-site>/hiero-mcp --live
```

It runs the tests (plus the live check with `--live`) and stops at the first failure. If everything passes, it writes `dist/site/`: the wheel, checksums, a package index for `uvx --index <base-url>/simple/ hiero-mcp@latest`, the license, and `download.html`, the block to paste into the download page. Upload the whole folder to the base URL, keeping its structure.

After changing the plugin, run `uv run hiero-mcp install-plugin` and restart Hiero, or reload `hiero_mcp_bridge.commands` from `execute_python`.

`src/hiero_mcp/server.py` defines the MCP tools. `src/hiero_mcp/hiero_plugin/hiero_mcp_bridge/commands.py` implements them with the Hiero API. Each tool has a command with the same name and parameters, and the tests check that they stay in sync.

## License

Freeware by Toolbox Design, all rights reserved: free to use, including commercially, but not to modify, redistribute or sell. See [LICENSE](LICENSE).
