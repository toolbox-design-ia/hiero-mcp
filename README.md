# hiero-mcp

Servidor [MCP](https://modelcontextprotocol.io) para **Foundry Hiero / Nuke Studio 17**. Permite que cualquier agente compatible con MCP (Claude, ChatGPT/Codex, Gemini y otros) lea y edite proyectos, bins, secuencias, tracks, shots, tags, efectos y exports de una sesión de Hiero abierta.

```
Agente (Claude / Codex / Gemini)
        │  MCP (stdio o HTTP)
        ▼
  hiero-mcp  (este paquete, Python ≥ 3.11, fuera de Hiero)
        │  JSON por socket TCP en 127.0.0.1:7392 + token
        ▼
  plugin hiero_mcp_bridge  (dentro de Hiero, hilo principal)
        │  hiero.core / hiero.ui
        ▼
     Hiero 17
```

El servidor MCP corre en la **misma máquina** que Hiero. Lo que se publica es el paquete: cada artista lo instala y lo registra en su agente.

## Requisitos

- Hiero, Hiero Player o Nuke Studio **17.x** (probado contra la API de 17.1v2, Python 3.11).
- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`).

## Instalación

### 1. Plugin de Hiero (una vez por máquina)

```bash
uvx --from git+https://github.com/hramirezedc/hiero-mcp hiero-mcp install-plugin
```

Copia `hiero_mcp_startup.py` en `~/.nuke/Python/Startup/` y el paquete `hiero_mcp_bridge` en `~/.nuke/`. También crea el token compartido en `~/.hiero_mcp/token`. Reinicia Hiero y comprueba la conexión:

```bash
uvx --from git+https://github.com/hramirezedc/hiero-mcp hiero-mcp status
```

Para desactivarlo en una sesión concreta, lanza Hiero con `HIERO_MCP_DISABLE=1`. Para quitarlo: `hiero-mcp uninstall-plugin`.

### 2. Registrar el servidor en tu agente

En todos los casos el comando es `uvx --from git+https://github.com/hramirezedc/hiero-mcp hiero-mcp`. Cuando el paquete esté en PyPI bastará con `uvx hiero-mcp`. Las apps de escritorio no siempre heredan tu `PATH`: si no encuentran `uvx`, usa la ruta completa (`which uvx`).

**Claude Code**

```bash
claude mcp add hiero -- uvx --from git+https://github.com/hramirezedc/hiero-mcp hiero-mcp
```

**Claude Desktop**: en `~/Library/Application Support/Claude/claude_desktop_config.json`

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

**OpenAI Codex CLI**: en `~/.codex/config.toml`

```toml
[mcp_servers.hiero]
command = "uvx"
args = ["--from", "git+https://github.com/hramirezedc/hiero-mcp", "hiero-mcp"]
```

**Gemini CLI**: en `~/.gemini/settings.json`

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

**Clientes que solo aceptan una URL (HTTP)**

```bash
hiero-mcp --transport http --port 8765   # sirve http://127.0.0.1:8765/mcp
```

Los conectores remotos (por ejemplo ChatGPT) necesitan una URL HTTPS pública. El transporte HTTP todavía **no tiene autenticación**, y `execute_python` permite ejecutar código en tu máquina, así que no lo expongas fuera de `127.0.0.1` hasta que exista esa capa.

## Herramientas

| Área | Herramientas |
|---|---|
| Aplicación | `get_app_info`, `list_formats`, `execute_python` |
| Proyectos | `list_projects`, `get_project`, `new_project`, `open_project`, `save_project`, `close_project`, `undo`, `redo` |
| Bins y clips | `list_bin`, `create_bin`, `import_media`, `get_clip`, `rename_bin_item`, `move_bin_item`, `delete_bin_item`, `set_clip_version`, `reconnect_media` |
| Secuencias y tracks | `list_sequences`, `get_sequence`, `create_sequence`, `update_sequence`, `add_track`, `update_track`, `delete_track` |
| Shots | `list_track_items`, `get_track_item`, `add_clip_to_track`, `update_track_item`, `delete_track_items`, `razor`, `add_effect` |
| Tags | `list_project_tags`, `add_tag`, `remove_tag` |
| Interfaz | `get_selection`, `set_selection`, `open_in_timeline`, `open_in_viewer`, `get_playhead`, `set_playhead` |
| Export | `list_export_presets`, `run_export` |

Cada cambio es **un solo paso de undo** en Hiero. Las herramientas que borran o sobrescriben están marcadas como `destructiveHint`, para que el agente pida confirmación.

## Configuración

| Variable | Dónde | Por defecto |
|---|---|---|
| `HIERO_MCP_PORT` | Hiero y servidor | `7392` |
| `HIERO_MCP_HOST` | Hiero y servidor | `127.0.0.1` |
| `HIERO_MCP_TOKEN` | Hiero y servidor | contenido de `~/.hiero_mcp/token` |
| `HIERO_MCP_HOME` | Hiero y servidor | `~/.hiero_mcp` |
| `HIERO_MCP_DISABLE` | Hiero | no definida |

## Desarrollo

```bash
uv sync
uv run pytest
uv run hiero-mcp status
uv run python scripts/live_check.py   # con Hiero abierto: prueba las 45 herramientas en un proyecto "mcp_test"
```

Tras cambiar el plugin, `uv run hiero-mcp install-plugin` y reinicia Hiero (o recarga `hiero_mcp_bridge.commands` desde `execute_python`).

`src/hiero_mcp/server.py` define las herramientas MCP. `src/hiero_mcp/hiero_plugin/hiero_mcp_bridge/commands.py` las implementa con la API de Hiero. Cada herramienta tiene un comando con el mismo nombre y los mismos parámetros, y los tests lo comprueban.
