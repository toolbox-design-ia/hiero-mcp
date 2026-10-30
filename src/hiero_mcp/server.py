"""MCP server exposing Hiero / Nuke Studio 17 to any MCP client."""

from __future__ import annotations

import functools
from typing import Any, Literal

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import __version__
from .bridge import BridgeClient, HieroConnectionError, HieroError

INSTRUCTIONS = """\
Controls a running Hiero / Nuke Studio 17 session through the hiero-mcp plugin.

Addressing: projects, sequences, clips and tracks are referenced by name (or GUID).
When `sequence` is omitted the sequence active in Hiero's timeline is used; when
`project` is omitted the active sequence's project (or the last opened one) is used.
Tracks are a 0-based index or a name, with `kind` = "video" | "audio". Track items are
a 0-based index on their track, a name or a GUID. Times are frame numbers on the
sequence timeline. Bin paths look like "Footage/Day1/A001".

Every change made by a tool is a single undo step in Hiero (see `undo`).
Start with `get_app_info` and `list_projects` to see what is open.
"""

ReadOnly = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
Edit = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
Destructive = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)

TrackKind = Literal["video", "audio"]
TrackRef = int | str
VersionRef = Literal["up", "down", "max", "min"] | int

mcp = MCPServer(name="hiero", title="Hiero MCP", version=__version__, instructions=INSTRUCTIONS)
_bridge: BridgeClient | None = None


def configure(bridge: BridgeClient) -> None:
    global _bridge
    _bridge = bridge


async def _call(command: str, **params: Any) -> Any:
    global _bridge
    if _bridge is None:
        _bridge = BridgeClient()
    try:
        return await anyio.to_thread.run_sync(functools.partial(_bridge.call, command, **params))
    except HieroConnectionError as exc:
        raise ToolError(str(exc)) from exc
    except HieroError as exc:
        # Lookup and validation errors explain themselves; anything else gets Hiero's traceback tail.
        message = str(exc)
        if exc.traceback and exc.kind not in ("LookupError", "ValueError"):
            message += "\n\nHiero traceback (last lines):\n" + "\n".join(exc.traceback.strip().splitlines()[-8:])
        raise ToolError(message) from exc


# --------------------------------------------------------------------------- application


@mcp.tool(annotations=ReadOnly)
async def get_app_info() -> dict[str, Any]:
    """Hiero product, version, mode (Hiero / Nuke Studio), Python version and open projects."""
    return await _call("get_app_info")


@mcp.tool(annotations=ReadOnly)
async def list_formats() -> list[dict[str, Any]]:
    """All image formats Hiero knows about (name, width, height, pixel aspect)."""
    return await _call("list_formats")


@mcp.tool(annotations=Destructive)
async def execute_python(code: str) -> dict[str, Any]:
    """Run Python inside Hiero's main thread for anything the other tools do not cover.

    `hiero` is pre-imported (hiero.core, hiero.ui). Assign to a variable named `result`
    to return a JSON-serialisable value; stdout, stderr and any traceback are returned too.
    """
    return await _call("execute_python", code=code)


# --------------------------------------------------------------------------- projects


@mcp.tool(annotations=ReadOnly)
async def list_projects() -> list[dict[str, Any]]:
    """Open projects with path, unsaved-changes flag and counts of sequences and clips."""
    return await _call("list_projects")


@mcp.tool(annotations=ReadOnly)
async def get_project(project: str | None = None) -> dict[str, Any]:
    """Project settings: frame rate, output format, OCIO, views, export root, undo/redo state, sequences."""
    return await _call("get_project", project=project)


@mcp.tool(annotations=Edit)
async def new_project(name: str | None = None) -> dict[str, Any]:
    """Create a new empty project."""
    return await _call("new_project", name=name)


@mcp.tool(annotations=Edit)
async def open_project(path: str) -> dict[str, Any]:
    """Open a .hrox project from disk."""
    return await _call("open_project", path=path)


@mcp.tool(annotations=Edit)
async def save_project(project: str | None = None, path: str | None = None) -> dict[str, Any]:
    """Save a project, or save it to a new .hrox path ("save as") when `path` is given."""
    return await _call("save_project", project=project, path=path)


@mcp.tool(annotations=Destructive)
async def close_project(project: str, save: bool = False) -> dict[str, Any]:
    """Close a project. Refuses if it has unsaved changes unless `save` is true."""
    return await _call("close_project", project=project, save=save)


@mcp.tool(annotations=Edit)
async def undo(project: str | None = None) -> dict[str, Any]:
    """Undo the last action in a project."""
    return await _call("undo", project=project)


@mcp.tool(annotations=Edit)
async def redo(project: str | None = None) -> dict[str, Any]:
    """Redo the last undone action in a project."""
    return await _call("redo", project=project)


# --------------------------------------------------------------------------- bins and clips


@mcp.tool(annotations=ReadOnly)
async def list_bin(project: str | None = None, bin_path: str = "", depth: int = 3) -> dict[str, Any]:
    """Tree of bins, clips, sequences and tags under a bin ("" is the project root)."""
    return await _call("list_bin", project=project, bin_path=bin_path, depth=depth)


@mcp.tool(annotations=Edit)
async def create_bin(bin_path: str, project: str | None = None) -> dict[str, Any]:
    """Create a bin, including any missing parent bins (e.g. "Footage/Day1")."""
    return await _call("create_bin", bin_path=bin_path, project=project)


@mcp.tool(annotations=Edit)
async def import_media(paths: list[str], project: str | None = None, bin_path: str = "") -> dict[str, Any]:
    """Import files or folders (image sequences, movies) as clips into a bin, creating it if needed."""
    return await _call("import_media", paths=paths, project=project, bin_path=bin_path)


@mcp.tool(annotations=ReadOnly)
async def get_clip(clip: str, project: str | None = None) -> dict[str, Any]:
    """Clip details: media path, resolution, timecode, versions, tags and media metadata.

    `clip` is a bin path ("Footage/A001"), a clip name or a GUID.
    """
    return await _call("get_clip", clip=clip, project=project)


@mcp.tool(annotations=Edit)
async def rename_bin_item(path: str, new_name: str, project: str | None = None) -> dict[str, Any]:
    """Rename a bin, clip or sequence by its bin path."""
    return await _call("rename_bin_item", path=path, new_name=new_name, project=project)


@mcp.tool(annotations=Edit)
async def move_bin_item(path: str, to_bin: str, project: str | None = None) -> dict[str, Any]:
    """Move a bin, clip or sequence into another bin ("" is the project root)."""
    return await _call("move_bin_item", path=path, to_bin=to_bin, project=project)


@mcp.tool(annotations=Destructive)
async def delete_bin_item(path: str, project: str | None = None) -> dict[str, Any]:
    """Remove a bin, clip or sequence from the project (undoable)."""
    return await _call("delete_bin_item", path=path, project=project)


@mcp.tool(annotations=Edit)
async def set_clip_version(clip: str, version: VersionRef = "up", project: str | None = None) -> dict[str, Any]:
    """Change a clip's active version: "up", "down", "max", "min" or a version index."""
    return await _call("set_clip_version", clip=clip, version=version, project=project)


@mcp.tool(annotations=Edit)
async def reconnect_media(path: str, clip: str | None = None, sequence: str | None = None, project: str | None = None) -> dict[str, Any]:
    """Reconnect offline media for a clip, or for every clip in a sequence, from a folder."""
    return await _call("reconnect_media", path=path, clip=clip, sequence=sequence, project=project)


# --------------------------------------------------------------------------- sequences and tracks


@mcp.tool(annotations=ReadOnly)
async def list_sequences(project: str | None = None) -> list[dict[str, Any]]:
    """Sequences in one project (or all open projects) with duration, frame rate and format."""
    return await _call("list_sequences", project=project)


@mcp.tool(annotations=ReadOnly)
async def get_sequence(sequence: str | None = None, project: str | None = None, include_items: bool = False) -> dict[str, Any]:
    """Sequence details and tracks; with `include_items` also every track item and soft effect."""
    return await _call("get_sequence", sequence=sequence, project=project, include_items=include_items)


@mcp.tool(annotations=Edit)
async def create_sequence(
    name: str,
    project: str | None = None,
    bin_path: str = "",
    framerate: float | None = None,
    format: str | None = None,
    timecode_start: int | None = None,
    video_tracks: int = 1,
    audio_tracks: int = 0,
) -> dict[str, Any]:
    """Create a sequence in a bin. `format` is a name from `list_formats`; `timecode_start` is in frames."""
    return await _call(
        "create_sequence",
        name=name,
        project=project,
        bin_path=bin_path,
        framerate=framerate,
        format=format,
        timecode_start=timecode_start,
        video_tracks=video_tracks,
        audio_tracks=audio_tracks,
    )


@mcp.tool(annotations=Edit)
async def update_sequence(
    sequence: str | None = None,
    project: str | None = None,
    name: str | None = None,
    framerate: float | None = None,
    format: str | None = None,
    timecode_start: int | None = None,
    in_time: int | None = None,
    out_time: int | None = None,
) -> dict[str, Any]:
    """Rename a sequence or change its frame rate, format, start timecode or in/out points."""
    return await _call(
        "update_sequence",
        sequence=sequence,
        project=project,
        name=name,
        framerate=framerate,
        format=format,
        timecode_start=timecode_start,
        in_time=in_time,
        out_time=out_time,
    )


@mcp.tool(annotations=Edit)
async def add_track(sequence: str | None = None, project: str | None = None, name: str | None = None, kind: TrackKind = "video") -> dict[str, Any]:
    """Add a video or audio track to a sequence."""
    return await _call("add_track", sequence=sequence, project=project, name=name, kind=kind)


@mcp.tool(annotations=Edit)
async def update_track(
    track: TrackRef,
    sequence: str | None = None,
    project: str | None = None,
    kind: TrackKind = "video",
    name: str | None = None,
    enabled: bool | None = None,
    locked: bool | None = None,
    blend_enabled: bool | None = None,
    blend_mode: str | None = None,
    volume: float | None = None,
) -> dict[str, Any]:
    """Rename, enable/disable, lock/unlock a track; set blend mode (video) or volume 0-1 (audio)."""
    return await _call(
        "update_track",
        track=track,
        sequence=sequence,
        project=project,
        kind=kind,
        name=name,
        enabled=enabled,
        locked=locked,
        blend_enabled=blend_enabled,
        blend_mode=blend_mode,
        volume=volume,
    )


@mcp.tool(annotations=Destructive)
async def delete_track(track: TrackRef, sequence: str | None = None, project: str | None = None, kind: TrackKind = "video") -> dict[str, Any]:
    """Remove a track and everything on it (undoable)."""
    return await _call("delete_track", track=track, sequence=sequence, project=project, kind=kind)


# --------------------------------------------------------------------------- track items


@mcp.tool(annotations=ReadOnly)
async def list_track_items(sequence: str | None = None, project: str | None = None, track: TrackRef | None = None, kind: TrackKind = "video") -> list[dict[str, Any]]:
    """Shots on one track, or on every track of `kind`, with timeline and source ranges."""
    return await _call("list_track_items", sequence=sequence, project=project, track=track, kind=kind)


@mcp.tool(annotations=ReadOnly)
async def get_track_item(item: TrackRef, track: TrackRef = 0, sequence: str | None = None, project: str | None = None, kind: TrackKind = "video") -> dict[str, Any]:
    """Full shot details: ranges, handles, speed, media, versions, linked items, tags, metadata."""
    return await _call("get_track_item", item=item, track=track, sequence=sequence, project=project, kind=kind)


@mcp.tool(annotations=Edit)
async def add_clip_to_track(
    clip: str,
    sequence: str | None = None,
    project: str | None = None,
    track: TrackRef = 0,
    kind: TrackKind = "video",
    timeline_in: int | None = None,
    source_in: int | None = None,
    source_out: int | None = None,
    audio_channel: int = 0,
) -> dict[str, Any]:
    """Cut a clip into a track at `timeline_in` (default: after the last item). Overlapping items are overwritten."""
    return await _call(
        "add_clip_to_track",
        clip=clip,
        sequence=sequence,
        project=project,
        track=track,
        kind=kind,
        timeline_in=timeline_in,
        source_in=source_in,
        source_out=source_out,
        audio_channel=audio_channel,
    )


@mcp.tool(annotations=Edit)
async def update_track_item(
    item: TrackRef,
    track: TrackRef = 0,
    sequence: str | None = None,
    project: str | None = None,
    kind: TrackKind = "video",
    name: str | None = None,
    enabled: bool | None = None,
    move_to: int | None = None,
    timeline_in: int | None = None,
    timeline_out: int | None = None,
    source_in: int | None = None,
    source_out: int | None = None,
    playback_speed: float | None = None,
    version: VersionRef | None = None,
    replace_clip: str | None = None,
) -> dict[str, Any]:
    """Edit a shot: rename, enable, retime, move (`move_to` = new timeline in, keeps duration), trim, version, swap clip.

    Trims keep playback speed: `timeline_in`/`timeline_out` and `source_in`/`source_out` trim the head or tail.
    Source frames are relative to the start of the clip (0 = first frame of the media).
    """
    return await _call(
        "update_track_item",
        item=item,
        track=track,
        sequence=sequence,
        project=project,
        kind=kind,
        name=name,
        enabled=enabled,
        move_to=move_to,
        timeline_in=timeline_in,
        timeline_out=timeline_out,
        source_in=source_in,
        source_out=source_out,
        playback_speed=playback_speed,
        version=version,
        replace_clip=replace_clip,
    )


@mcp.tool(annotations=Destructive)
async def delete_track_items(items: list[TrackRef], track: TrackRef = 0, sequence: str | None = None, project: str | None = None, kind: TrackKind = "video") -> dict[str, Any]:
    """Remove shots from a track (undoable)."""
    return await _call("delete_track_items", items=items, track=track, sequence=sequence, project=project, kind=kind)


@mcp.tool(annotations=Edit)
async def razor(time: int, sequence: str | None = None, project: str | None = None, track: TrackRef | None = None, kind: TrackKind = "video") -> dict[str, Any]:
    """Cut every unlocked track (or one track) at a frame."""
    return await _call("razor", time=time, sequence=sequence, project=project, track=track, kind=kind)


@mcp.tool(annotations=Edit)
async def add_effect(
    effect_type: str,
    track: TrackRef = 0,
    sequence: str | None = None,
    project: str | None = None,
    item: TrackRef | None = None,
    timeline_in: int | None = None,
    timeline_out: int | None = None,
    knobs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add a soft effect (Nuke node class, e.g. "Grade", "Transform", "Text2") over a shot or a frame range.

    `knobs` sets node knob values, e.g. {"white": 1.2}. Without item or range it covers the whole sequence.
    """
    return await _call(
        "add_effect",
        effect_type=effect_type,
        track=track,
        sequence=sequence,
        project=project,
        item=item,
        timeline_in=timeline_in,
        timeline_out=timeline_out,
        knobs=knobs,
    )


# --------------------------------------------------------------------------- tags


@mcp.tool(annotations=ReadOnly)
async def list_project_tags(project: str | None = None) -> list[dict[str, Any]]:
    """Tags available to the project: its own Tags bin plus Hiero's preset tags (Status, Review, Shots...)."""
    return await _call("list_project_tags", project=project)


@mcp.tool(annotations=Edit)
async def add_tag(
    tag: str,
    project: str | None = None,
    sequence: str | None = None,
    track: TrackRef | None = None,
    item: TrackRef | None = None,
    clip: str | None = None,
    kind: TrackKind = "video",
    note: str | None = None,
    icon: str | None = None,
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Tag a clip, sequence, track or shot. Reuses a project tag of the same name if it exists.

    Target: `clip`; or `sequence` alone; or `sequence`+`track`; or `sequence`+`track`+`item`.
    """
    return await _call(
        "add_tag",
        tag=tag,
        project=project,
        sequence=sequence,
        track=track,
        item=item,
        clip=clip,
        kind=kind,
        note=note,
        icon=icon,
        metadata=metadata,
    )


@mcp.tool(annotations=Destructive)
async def remove_tag(
    tag: str,
    project: str | None = None,
    sequence: str | None = None,
    track: TrackRef | None = None,
    item: TrackRef | None = None,
    clip: str | None = None,
    kind: TrackKind = "video",
) -> dict[str, Any]:
    """Remove a tag (by name or GUID) from a clip, sequence, track or shot."""
    return await _call("remove_tag", tag=tag, project=project, sequence=sequence, track=track, item=item, clip=clip, kind=kind)


# --------------------------------------------------------------------------- UI


@mcp.tool(annotations=ReadOnly)
async def get_selection() -> dict[str, Any]:
    """What the artist has selected in the active timeline and in the project bin."""
    return await _call("get_selection")


@mcp.tool(annotations=Edit)
async def set_selection(items: list[dict[str, Any]], sequence: str | None = None, project: str | None = None) -> dict[str, Any]:
    """Select shots in the timeline. items: [{"track": 0, "item": "shot010", "kind": "video"}]."""
    return await _call("set_selection", items=items, sequence=sequence, project=project)


@mcp.tool(annotations=Edit)
async def open_in_timeline(sequence: str | None = None, clip: str | None = None, project: str | None = None) -> dict[str, Any]:
    """Open a sequence or clip in a timeline tab."""
    return await _call("open_in_timeline", sequence=sequence, clip=clip, project=project)


@mcp.tool(annotations=Edit)
async def open_in_viewer(sequence: str | None = None, clip: str | None = None, project: str | None = None) -> dict[str, Any]:
    """Show a sequence or clip in the viewer."""
    return await _call("open_in_viewer", sequence=sequence, clip=clip, project=project)


@mcp.tool(annotations=ReadOnly)
async def get_playhead() -> dict[str, Any]:
    """Current viewer frame and the sequence being viewed."""
    return await _call("get_playhead")


@mcp.tool(annotations=Edit)
async def set_playhead(time: int) -> dict[str, Any]:
    """Move the viewer playhead to a frame."""
    return await _call("set_playhead", time=time)


# --------------------------------------------------------------------------- export


@mcp.tool(annotations=ReadOnly)
async def list_export_presets(project: str | None = None) -> list[dict[str, Any]]:
    """Export (processor) presets available locally and in the project."""
    return await _call("list_export_presets", project=project)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False))
async def run_export(
    preset: str,
    sequence: str | None = None,
    project: str | None = None,
    track_items: list[dict[str, Any]] | None = None,
    export_root: str | None = None,
    synchronous: bool = False,
) -> dict[str, Any]:
    """Export a sequence, or selected shots, with a named export preset (may overwrite files on disk).

    track_items: [{"track": 0, "item": "shot010"}]. `export_root` overrides the preset's root for this run only.
    Asynchronous by default; Hiero's export queue shows progress.
    """
    return await _call(
        "run_export",
        preset=preset,
        sequence=sequence,
        project=project,
        track_items=track_items,
        export_root=export_root,
        synchronous=synchronous,
    )
