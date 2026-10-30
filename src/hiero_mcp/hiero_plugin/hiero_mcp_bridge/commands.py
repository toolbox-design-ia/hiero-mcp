"""Commands exposed by the bridge. Each one runs on Hiero's main thread.

Objects are addressed by name (or GUID) and results are plain JSON-friendly
dicts, so the MCP server never has to know about Hiero types. Commands that
change a project are wrapped in a single undo step.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import traceback
from typing import Any, Callable, Iterator

import hiero.core as hc

try:
    import hiero.ui as hui
except ImportError:  # terminal mode (-t) has no UI module
    hui = None

COMMANDS: dict[str, Callable[..., Any]] = {}


def command(fn: Callable[..., Any]) -> Callable[..., Any]:
    COMMANDS[fn.__name__] = fn
    return fn


# --------------------------------------------------------------------------- helpers


def _call(obj: Any, method: str, default: Any = None) -> Any:
    try:
        return getattr(obj, method)()
    except Exception:
        return default


def _metadata(obj: Any) -> dict[str, Any]:
    md = _call(obj, "metadata")
    if md is None:
        return {}
    try:
        return {str(k): str(v) for k, v in md.dict().items()}
    except Exception:
        try:
            return {str(k): str(md.value(k)) for k in md.keys()}
        except Exception:
            return {}


def _timebase(tb: Any) -> dict[str, Any] | None:
    if tb is None:
        return None
    try:
        num, den = tb.numerator(), tb.denominator()
        return {"fps": round(num / den, 3) if den else None, "numerator": num, "denominator": den}
    except Exception:
        return {"fps": str(tb)}


def _format(fmt: Any) -> dict[str, Any] | None:
    if fmt is None:
        return None
    return {
        "name": _call(fmt, "name"),
        "width": _call(fmt, "width"),
        "height": _call(fmt, "height"),
        "pixel_aspect": _call(fmt, "pixelAspect"),
    }


def _tag(tag: Any) -> dict[str, Any]:
    return {
        "name": tag.name(),
        "guid": _call(tag, "guid"),
        "note": _call(tag, "note"),
        "icon": _call(tag, "icon"),
        "in": _call(tag, "inTime"),
        "out": _call(tag, "outTime"),
        "visible": _call(tag, "visible"),
        "metadata": _metadata(tag),
    }


def _active_item(item: Any) -> Any:
    return item.activeItem() if isinstance(item, hc.BinItem) else item


def _media_source(clip: Any) -> dict[str, Any] | None:
    ms = _call(clip, "mediaSource")
    if ms is None:
        return None
    return {
        "path": _call(ms, "firstpath"),
        "filename": _call(ms, "filename"),
        "duration": _call(ms, "duration"),
        "start_time": _call(ms, "startTime"),
        "timecode_start": _call(ms, "timecodeStart"),
        "width": _call(ms, "width"),
        "height": _call(ms, "height"),
        "pixel_aspect": _call(ms, "pixelAspect"),
        "has_video": _call(ms, "hasVideo"),
        "has_audio": _call(ms, "hasAudio"),
        "offline": _call(ms, "isOffline"),
        "single_file": _call(ms, "singleFile"),
    }


def _clip_summary(clip: Any) -> dict[str, Any]:
    ms = _call(clip, "mediaSource")
    return {
        "type": "clip",
        "name": clip.name(),
        "guid": _call(clip, "guid"),
        "duration": _call(clip, "duration"),
        "framerate": _timebase(_call(clip, "framerate")),
        "format": _format(_call(clip, "format")),
        "path": _call(ms, "firstpath") if ms is not None else None,
        "offline": _call(ms, "isOffline") if ms is not None else None,
    }


def _sequence_summary(seq: Any) -> dict[str, Any]:
    return {
        "type": "sequence",
        "name": seq.name(),
        "guid": _call(seq, "guid"),
        "project": _call(_call(seq, "project"), "name"),
        "duration": _call(seq, "duration"),
        "framerate": _timebase(_call(seq, "framerate")),
        "format": _format(_call(seq, "format")),
        "timecode_start": _call(seq, "timecodeStart"),
        "in": _call(seq, "inTime") if _call(seq, "inOutEnabled") else None,
        "out": _call(seq, "outTime") if _call(seq, "inOutEnabled") else None,
        "video_tracks": _call(seq, "numVideoTracks"),
        "audio_tracks": _call(seq, "numAudioTracks"),
    }


def _track_kind(track: Any) -> str:
    return "audio" if isinstance(track, hc.AudioTrack) else "video"


def _track_summary(track: Any) -> dict[str, Any]:
    info = {
        "name": track.name(),
        "guid": _call(track, "guid"),
        "kind": _track_kind(track),
        "index": _call(track, "trackIndex"),
        "enabled": _call(track, "isEnabled"),
        "locked": _call(track, "isLocked"),
        "items": _call(track, "numItems"),
        "tags": [_tag(t) for t in (_call(track, "tags") or ())],
    }
    if info["kind"] == "video":
        info["blend_enabled"] = _call(track, "isBlendEnabled")
        info["blend_mode"] = _call(track, "blendMode")
        info["view"] = _call(track, "view")
    else:
        info["volume"] = _call(track, "volume")
    return info


def _track_item_summary(item: Any, index: int | None = None) -> dict[str, Any]:
    source = _call(item, "source")
    track = _call(item, "parentTrack") or _call(item, "parent")
    if index is None and track is not None:
        index = next((i for i, ti in enumerate(track.items()) if ti == item), None)
    return {
        "name": item.name(),
        "guid": _call(item, "guid"),
        "index": index,
        "track": _call(track, "name"),
        "enabled": _call(item, "isEnabled"),
        "timeline_in": _call(item, "timelineIn"),
        "timeline_out": _call(item, "timelineOut"),
        "source_in": _call(item, "sourceIn"),
        "source_out": _call(item, "sourceOut"),
        "duration": _call(item, "duration"),
        "source": _call(source, "name"),
    }


def _track_item_detail(item: Any) -> dict[str, Any]:
    info = _track_item_summary(item)
    source = _call(item, "source")
    version = _call(item, "currentVersion")
    info.update(
        {
            "event_number": _call(item, "eventNumber"),
            "kind": _track_kind(_call(item, "parentTrack")),
            "playback_speed": _call(item, "playbackSpeed"),
            "source_duration": _call(item, "sourceDuration"),
            "handle_in": _call(item, "handleInLength"),
            "handle_out": _call(item, "handleOutLength"),
            "media_present": _call(item, "isMediaPresent"),
            "media": _media_source(source) if source is not None else None,
            "version": _call(version, "name"),
            "num_versions": _call(item, "numVersions"),
            "version_linked_to_bin": _call(item, "versionLinkedToBin"),
            "linked_items": [li.name() for li in (_call(item, "linkedItems") or ())],
            "tags": [_tag(t) for t in (_call(item, "tags") or ())],
            "metadata": _metadata(item),
        }
    )
    return info


def _effect_summary(effect: Any) -> dict[str, Any]:
    node = _call(effect, "node")
    return {
        "name": effect.name(),
        "guid": _call(effect, "guid"),
        "node_class": _call(node, "Class"),
        "enabled": _call(effect, "isEnabled"),
        "timeline_in": _call(effect, "timelineIn"),
        "timeline_out": _call(effect, "timelineOut"),
        "subtrack": _call(effect, "subTrackIndex"),
    }


def _effects(track: Any) -> list[dict[str, Any]]:
    out = []
    for subtrack in _call(track, "subTrackItems") or ():
        for effect in subtrack:
            out.append(_effect_summary(effect))
    return out


@contextlib.contextmanager
def _undo(project: Any, label: str) -> Iterator[None]:
    project.beginUndo("MCP: " + label)
    try:
        yield
    except BaseException:
        project.endUndo()
        raise
    project.endUndo()


# --------------------------------------------------------------------------- lookups


def _projects() -> list[Any]:
    return list(hc.projects())


def _active_sequence() -> Any:
    if hui is None:
        return None
    try:
        seq = hui.activeSequence()
    except Exception:
        return None
    return seq if isinstance(seq, hc.Sequence) else None


def _get_project(project: str | None = None) -> Any:
    projects = _projects()
    if not projects:
        raise LookupError("No projects are open in Hiero")
    if project is None:
        seq = _active_sequence()
        if seq is not None and seq.project() is not None:
            return seq.project()
        return projects[-1]
    for p in projects:
        if project in (p.name(), p.path()):
            return p
    raise LookupError("Project not found: %r (open: %s)" % (project, [p.name() for p in projects]))


def _sequences(project: Any) -> list[Any]:
    return [_active_item(s) for s in project.sequences()]


def _get_sequence(sequence: str | None = None, project: str | None = None) -> Any:
    if sequence is None:
        seq = _active_sequence()
        if seq is None:
            raise LookupError("No active sequence in Hiero; pass a sequence name")
        return seq
    projects = [_get_project(project)] if project else _projects()
    for p in projects:
        for seq in _sequences(p):
            if sequence in (seq.name(), _call(seq, "guid")):
                return seq
    raise LookupError("Sequence not found: %r" % sequence)


def _get_track(seq: Any, track: int | str = 0, kind: str = "video") -> Any:
    tracks = list(seq.audioTracks() if kind == "audio" else seq.videoTracks())
    if isinstance(track, int) or (isinstance(track, str) and track.isdigit()):
        idx = int(track)
        if 0 <= idx < len(tracks):
            return tracks[idx]
        raise LookupError("%s track index %d out of range (0-%d)" % (kind, idx, len(tracks) - 1))
    for t in tracks:
        if track in (t.name(), _call(t, "guid")):
            return t
    raise LookupError("%s track not found: %r (tracks: %s)" % (kind, track, [t.name() for t in tracks]))


def _get_track_item(track: Any, item: int | str) -> Any:
    items = list(track.items())
    if isinstance(item, int) or (isinstance(item, str) and item.isdigit()):
        idx = int(item)
        if 0 <= idx < len(items):
            return items[idx]
        raise LookupError("Item index %d out of range on track %r" % (idx, track.name()))
    for ti in items:
        if item in (ti.name(), _call(ti, "guid")):
            return ti
    raise LookupError("Track item not found on %r: %r" % (track.name(), item))


def _split_path(path: str | None) -> list[str]:
    return [p for p in (path or "").replace("\\", "/").split("/") if p]


def _get_bin(project: Any, bin_path: str | None = "", create: bool = False) -> Any:
    current = project.clipsBin()
    for part in _split_path(bin_path):
        match = next((b for b in current.bins() if b.name() == part), None)
        if match is None:
            if not create:
                raise LookupError("Bin not found: %r" % bin_path)
            match = hc.Bin(part)
            current.addItem(match)
        current = match
    return current


def _get_bin_entry(project: Any, path: str) -> tuple[Any, Any]:
    """Return (parent_bin, child) for a bin path such as 'Footage/Day1/A001'."""
    parts = _split_path(path)
    if not parts:
        raise LookupError("Empty bin path")
    parent = _get_bin(project, "/".join(parts[:-1]))
    for child in parent.items():
        if child.name() == parts[-1]:
            return parent, child
    raise LookupError("Bin item not found: %r" % path)


def _get_clip(clip: str, project: str | None = None) -> Any:
    p = _get_project(project)
    if "/" in clip:
        _, entry = _get_bin_entry(p, clip)
        found = _active_item(entry)
        if isinstance(found, hc.Clip):
            return found
        raise LookupError("%r is not a clip" % clip)
    for c in p.clips():
        c = _active_item(c)
        if clip in (c.name(), _call(c, "guid")):
            return c
    raise LookupError("Clip not found: %r" % clip)


def _resolve_target(
    project: str | None = None,
    sequence: str | None = None,
    track: int | str | None = None,
    item: int | str | None = None,
    clip: str | None = None,
    kind: str = "video",
) -> Any:
    """Resolve a clip, sequence, track or track item from the usual address params."""
    if clip is not None:
        return _get_clip(clip, project)
    seq = _get_sequence(sequence, project)
    if track is None:
        return seq
    trk = _get_track(seq, track, kind)
    if item is None:
        return trk
    return _get_track_item(trk, item)


def _find_format(fmt: str) -> Any:
    for f in hc.formats():
        if f.name() == fmt:
            return f
    raise LookupError("Format not found: %r (see list_formats)" % fmt)


def _make_timebase(fps: float | str) -> Any:
    try:
        return hc.TimeBase(fps)
    except Exception:
        return hc.TimeBase(str(fps))


def _bin_tree(bin_: Any, depth: int) -> list[dict[str, Any]]:
    out = []
    for child in bin_.items():
        if isinstance(child, hc.Bin):
            entry = {"type": "bin", "name": child.name(), "items": child.numChildren()}
            if depth > 0:
                entry["children"] = _bin_tree(child, depth - 1)
            out.append(entry)
        elif isinstance(child, hc.BinItem):
            active = child.activeItem()
            if isinstance(active, hc.Sequence):
                entry = _sequence_summary(active)
            elif isinstance(active, hc.Clip):
                entry = _clip_summary(active)
            else:
                entry = {"type": type(active).__name__, "name": child.name()}
            entry["versions"] = _call(child, "numVersions")
            out.append(entry)
        elif isinstance(child, hc.Tag):
            out.append({"type": "tag", **_tag(child)})
        else:
            out.append({"type": type(child).__name__, "name": _call(child, "name")})
    return out


def _timeline_editor(seq: Any) -> Any:
    if hui is None:
        raise RuntimeError("Hiero UI is not available")
    return hui.getTimelineEditor(seq)


# --------------------------------------------------------------------------- application


@command
def ping() -> dict[str, Any]:
    return {"pong": True}


@command
def get_app_info() -> dict[str, Any]:
    env = hc.env
    keys = ("ProductName", "ApplicationName", "VersionString", "VersionMajor", "VersionMinor", "VersionRelease", "VersionDate")
    info = {k: env[k] for k in keys if k in env}
    info.update({"python": sys.version.split()[0], "pid": os.getpid(), "ui": hui is not None, "projects": [p.name() for p in _projects()]})
    return info


@command
def list_formats() -> list[dict[str, Any]]:
    return [_format(f) for f in hc.formats()]


@command
def execute_python(code: str) -> dict[str, Any]:
    """Run arbitrary Python in Hiero. Assign to ``result`` to return a value."""
    scope: dict[str, Any] = {"hiero": sys.modules["hiero"], "result": None}
    stdout, stderr = io.StringIO(), io.StringIO()
    error = None
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            exec(compile(code, "<hiero-mcp>", "exec"), scope)
        except Exception:
            error = traceback.format_exc()
    return {"result": scope.get("result"), "stdout": stdout.getvalue(), "stderr": stderr.getvalue(), "error": error}


# --------------------------------------------------------------------------- projects


@command
def list_projects() -> list[dict[str, Any]]:
    return [
        {
            "name": p.name(),
            "path": p.path(),
            "modified": _call(p, "modifiedSinceLastSave"),
            "editable": _call(p, "editable"),
            "sequences": len(p.sequences()),
            "clips": len(p.clips()),
        }
        for p in _projects()
    ]


@command
def get_project(project: str | None = None) -> dict[str, Any]:
    p = _get_project(project)
    return {
        "name": p.name(),
        "path": p.path(),
        "modified": _call(p, "modifiedSinceLastSave"),
        "editable": _call(p, "editable"),
        "framerate": _timebase(_call(p, "framerate")),
        "output_format": _format(_call(p, "outputFormat")),
        "start_timecode": _call(p, "startTimecode"),
        "project_directory": _call(p, "projectDirectory"),
        "export_root": _call(p, "exportRootDirectory"),
        "ocio_config": _call(p, "ocioConfigName"),
        "ocio_config_path": _call(p, "ocioConfigPath"),
        "views": list(_call(p, "views") or ()),
        "shot_preset": _call(p, "shotPresetName"),
        "undo": _call(p, "undoItemText"),
        "redo": _call(p, "redoItemText"),
        "sequences": [s.name() for s in _sequences(p)],
    }


@command
def new_project(name: str | None = None) -> dict[str, Any]:
    p = hc.newProject(name) if name else hc.newProject()
    return {"name": p.name()}


@command
def open_project(path: str) -> dict[str, Any]:
    p = hc.openProject(path)
    if p is None:
        raise RuntimeError("Hiero could not open %r" % path)
    return {"name": p.name(), "path": p.path()}


@command
def save_project(project: str | None = None, path: str | None = None) -> dict[str, Any]:
    p = _get_project(project)
    if path:
        p.saveAs(path)
    elif p.path():
        p.save()
    else:
        raise ValueError("Project %r has never been saved; pass a path" % p.name())
    return {"name": p.name(), "path": p.path()}


@command
def close_project(project: str, save: bool = False) -> dict[str, Any]:
    p = _get_project(project)
    if save:
        save_project(project)
    elif _call(p, "modifiedSinceLastSave"):
        raise RuntimeError("Project %r has unsaved changes; pass save=true or save it first" % p.name())
    name = p.name()
    p.close()
    return {"closed": name}


@command
def undo(project: str | None = None) -> dict[str, Any]:
    p = _get_project(project)
    text = _call(p, "undoItemText")
    p.undo()
    return {"undone": text}


@command
def redo(project: str | None = None) -> dict[str, Any]:
    p = _get_project(project)
    text = _call(p, "redoItemText")
    p.redo()
    return {"redone": text}


# --------------------------------------------------------------------------- bins and clips


@command
def list_bin(project: str | None = None, bin_path: str = "", depth: int = 3) -> dict[str, Any]:
    p = _get_project(project)
    b = _get_bin(p, bin_path)
    return {"project": p.name(), "bin": bin_path or "/", "items": _bin_tree(b, depth)}


@command
def create_bin(bin_path: str, project: str | None = None) -> dict[str, Any]:
    p = _get_project(project)
    with _undo(p, "create bin"):
        b = _get_bin(p, bin_path, create=True)
    return {"bin": bin_path, "name": b.name()}


@command
def import_media(paths: list[str], project: str | None = None, bin_path: str = "") -> dict[str, Any]:
    p = _get_project(project)
    imported, errors = [], []
    with _undo(p, "import media"):
        b = _get_bin(p, bin_path, create=True)
        for path in paths:
            try:
                if os.path.isdir(path):
                    before = {c.name() for c in b.clips()}
                    b.importFolder(path)
                    imported.extend(_clip_summary(_active_item(c)) for c in b.clips() if c.name() not in before)
                else:
                    imported.append(_clip_summary(_active_item(b.createClip(path))))
            except Exception as exc:
                errors.append({"path": path, "error": str(exc)})
    return {"bin": bin_path or "/", "imported": imported, "errors": errors}


@command
def get_clip(clip: str, project: str | None = None) -> dict[str, Any]:
    c = _get_clip(clip, project)
    info = _clip_summary(c)
    bin_item = _call(c, "binItem")
    info.update(
        {
            "source_in": _call(c, "sourceIn"),
            "source_out": _call(c, "sourceOut"),
            "timecode_start": _call(c, "timecodeStart"),
            "media": _media_source(c),
            "views": list(_call(c, "views") or ()),
            "error": _call(c, "hasError"),
            "versions": _call(bin_item, "numVersions"),
            "active_version": _call(_call(bin_item, "activeVersion"), "name"),
            "tags": [_tag(t) for t in (_call(c, "tags") or ())],
            "metadata": _metadata(c),
        }
    )
    return info


@command
def rename_bin_item(path: str, new_name: str, project: str | None = None) -> dict[str, Any]:
    p = _get_project(project)
    _, entry = _get_bin_entry(p, path)
    with _undo(p, "rename"):
        entry.setName(new_name)
    return {"path": path, "name": new_name}


@command
def delete_bin_item(path: str, project: str | None = None) -> dict[str, Any]:
    p = _get_project(project)
    parent, entry = _get_bin_entry(p, path)
    with _undo(p, "delete bin item"):
        parent.removeItem(entry)
    return {"deleted": path}


@command
def move_bin_item(path: str, to_bin: str, project: str | None = None) -> dict[str, Any]:
    p = _get_project(project)
    parent, entry = _get_bin_entry(p, path)
    with _undo(p, "move bin item"):
        target = _get_bin(p, to_bin, create=True)
        parent.removeItem(entry)
        target.addItem(entry)
    return {"moved": path, "to": to_bin or "/"}


@command
def set_clip_version(clip: str, version: str = "up", project: str | None = None) -> dict[str, Any]:
    """version: 'up', 'down', 'max', 'min' or an integer index."""
    c = _get_clip(clip, project)
    bin_item = c.binItem()
    with _undo(c.project(), "set clip version"):
        _apply_version(bin_item, version)
    return {"clip": c.name(), "active_version": _call(bin_item.activeVersion(), "name")}


def _apply_version(obj: Any, version: str | int) -> None:
    actions = {"up": "versionUp", "down": "versionDown", "max": "maxVersion", "min": "minVersion"}
    if str(version) in actions:
        getattr(obj, actions[str(version)])()
    elif isinstance(obj, hc.BinItem):
        obj.setActiveVersionIndex(int(version))
    else:
        obj.setCurrentVersionIndex(int(version))


@command
def reconnect_media(path: str, clip: str | None = None, sequence: str | None = None, project: str | None = None) -> dict[str, Any]:
    target = _get_clip(clip, project) if clip else _get_sequence(sequence, project)
    with _undo(target.project(), "reconnect media"):
        target.reconnectMedia(path)
    return {"reconnected": target.name(), "path": path}


# --------------------------------------------------------------------------- sequences and tracks


@command
def list_sequences(project: str | None = None) -> list[dict[str, Any]]:
    projects = [_get_project(project)] if project else _projects()
    return [_sequence_summary(s) for p in projects for s in _sequences(p)]


@command
def get_sequence(sequence: str | None = None, project: str | None = None, include_items: bool = False) -> dict[str, Any]:
    seq = _get_sequence(sequence, project)
    info = _sequence_summary(seq)
    info["tags"] = [_tag(t) for t in (_call(seq, "tags") or ())]
    info["metadata"] = _metadata(seq)
    tracks = []
    for track in list(seq.videoTracks()) + list(seq.audioTracks()):
        entry = _track_summary(track)
        if include_items:
            entry["track_items"] = [_track_item_summary(ti, i) for i, ti in enumerate(track.items())]
            if entry["kind"] == "video":
                entry["effects"] = _effects(track)
        tracks.append(entry)
    info["tracks"] = tracks
    return info


@command
def create_sequence(
    name: str,
    project: str | None = None,
    bin_path: str = "",
    framerate: float | None = None,
    format: str | None = None,
    timecode_start: int | None = None,
    video_tracks: int = 1,
    audio_tracks: int = 0,
) -> dict[str, Any]:
    p = _get_project(project)
    with _undo(p, "create sequence"):
        seq = hc.Sequence(name)
        _get_bin(p, bin_path, create=True).addItem(hc.BinItem(seq))
        if framerate is not None:
            seq.setFramerate(_make_timebase(framerate))
        if format is not None:
            seq.setFormat(_find_format(format))
        if timecode_start is not None:
            seq.setTimecodeStart(timecode_start)
        for i in range(video_tracks):
            seq.addTrack(hc.VideoTrack("Video %d" % (i + 1)))
        for i in range(audio_tracks):
            seq.addTrack(hc.AudioTrack("Audio %d" % (i + 1)))
    return _sequence_summary(seq)


@command
def update_sequence(
    sequence: str | None = None,
    project: str | None = None,
    name: str | None = None,
    framerate: float | None = None,
    format: str | None = None,
    timecode_start: int | None = None,
    in_time: int | None = None,
    out_time: int | None = None,
) -> dict[str, Any]:
    seq = _get_sequence(sequence, project)
    with _undo(seq.project(), "update sequence"):
        if name is not None:
            seq.setName(name)
        if framerate is not None:
            seq.setFramerate(_make_timebase(framerate))
        if format is not None:
            seq.setFormat(_find_format(format))
        if timecode_start is not None:
            seq.setTimecodeStart(timecode_start)
        if in_time is not None:
            seq.setInTime(in_time)
        if out_time is not None:
            seq.setOutTime(out_time)
    return _sequence_summary(seq)


@command
def add_track(sequence: str | None = None, project: str | None = None, name: str | None = None, kind: str = "video") -> dict[str, Any]:
    seq = _get_sequence(sequence, project)
    with _undo(seq.project(), "add track"):
        if kind == "audio":
            track = hc.AudioTrack(name or "Audio %d" % (seq.numAudioTracks() + 1))
        else:
            track = hc.VideoTrack(name or "Video %d" % (seq.numVideoTracks() + 1))
        seq.addTrack(track)
    return _track_summary(track)


@command
def update_track(
    track: int | str,
    sequence: str | None = None,
    project: str | None = None,
    kind: str = "video",
    name: str | None = None,
    enabled: bool | None = None,
    locked: bool | None = None,
    blend_enabled: bool | None = None,
    blend_mode: str | None = None,
    volume: float | None = None,
) -> dict[str, Any]:
    seq = _get_sequence(sequence, project)
    trk = _get_track(seq, track, kind)
    with _undo(seq.project(), "update track"):
        if name is not None:
            trk.setName(name)
        if enabled is not None:
            trk.setEnabled(enabled)
        if locked is not None:
            trk.setLocked(locked)
        if blend_enabled is not None:
            trk.setBlendEnabled(blend_enabled)
        if blend_mode is not None:
            trk.setBlendMode(blend_mode)
        if volume is not None:
            trk.setVolume(volume)
    return _track_summary(trk)


@command
def delete_track(track: int | str, sequence: str | None = None, project: str | None = None, kind: str = "video") -> dict[str, Any]:
    seq = _get_sequence(sequence, project)
    trk = _get_track(seq, track, kind)
    name = trk.name()
    with _undo(seq.project(), "delete track"):
        seq.removeTrack(trk)
    return {"deleted": name}


# --------------------------------------------------------------------------- track items


@command
def list_track_items(
    sequence: str | None = None,
    project: str | None = None,
    track: int | str | None = None,
    kind: str = "video",
) -> list[dict[str, Any]]:
    seq = _get_sequence(sequence, project)
    tracks = [_get_track(seq, track, kind)] if track is not None else list(seq.audioTracks() if kind == "audio" else seq.videoTracks())
    return [_track_item_summary(ti, i) for t in tracks for i, ti in enumerate(t.items())]


@command
def get_track_item(item: int | str, track: int | str = 0, sequence: str | None = None, project: str | None = None, kind: str = "video") -> dict[str, Any]:
    seq = _get_sequence(sequence, project)
    return _track_item_detail(_get_track_item(_get_track(seq, track, kind), item))


@command
def add_clip_to_track(
    clip: str,
    sequence: str | None = None,
    project: str | None = None,
    track: int | str = 0,
    kind: str = "video",
    timeline_in: int | None = None,
    source_in: int | None = None,
    source_out: int | None = None,
    audio_channel: int = 0,
) -> dict[str, Any]:
    seq = _get_sequence(sequence, project)
    c = _get_clip(clip, project or _call(seq.project(), "name"))
    trk = _get_track(seq, track, kind)
    if timeline_in is None:
        timeline_in = max([ti.timelineOut() + 1 for ti in trk.items()] or [0])
    with _undo(seq.project(), "add clip"):
        if kind == "audio":
            ti = trk.addTrackItem(c, audio_channel, timeline_in)
        else:
            ti = trk.addTrackItem(c, timeline_in)
        if source_in is not None:
            ti.setSourceIn(source_in)
        if source_out is not None:
            ti.setSourceOut(source_out)
    return _track_item_summary(ti)


@command
def update_track_item(
    item: int | str,
    track: int | str = 0,
    sequence: str | None = None,
    project: str | None = None,
    kind: str = "video",
    name: str | None = None,
    enabled: bool | None = None,
    move_to: int | None = None,
    timeline_in: int | None = None,
    timeline_out: int | None = None,
    source_in: int | None = None,
    source_out: int | None = None,
    playback_speed: float | None = None,
    version: str | None = None,
    replace_clip: str | None = None,
) -> dict[str, Any]:
    seq = _get_sequence(sequence, project)
    ti = _get_track_item(_get_track(seq, track, kind), item)
    with _undo(seq.project(), "update track item"):
        if replace_clip is not None:
            ti.setSource(_get_clip(replace_clip, _call(seq.project(), "name")))
        if name is not None:
            ti.setName(name)
        if enabled is not None:
            ti.setEnabled(enabled)
        if playback_speed is not None:
            ti.setPlaybackSpeed(playback_speed)
        # Hiero's move() is relative, and setSourceIn/Out retime the shot instead of
        # trimming it, so everything below goes through move/trimIn/trimOut, which keep speed.
        if move_to is not None:
            ti.move(move_to - ti.timelineIn())
        speed = ti.playbackSpeed() or 1.0
        if timeline_in is not None:
            ti.trimIn(timeline_in - ti.timelineIn())
        if timeline_out is not None:
            ti.trimOut(ti.timelineOut() - timeline_out)
        if source_in is not None:
            ti.trimIn(round((source_in - ti.sourceIn()) / speed))
        if source_out is not None:
            ti.trimOut(round((ti.sourceOut() - source_out) / speed))
        if version is not None:
            _apply_version(ti, version)
    return _track_item_detail(ti)


@command
def delete_track_items(items: list[int | str], track: int | str = 0, sequence: str | None = None, project: str | None = None, kind: str = "video") -> dict[str, Any]:
    seq = _get_sequence(sequence, project)
    trk = _get_track(seq, track, kind)
    targets = [_get_track_item(trk, i) for i in items]
    names = [t.name() for t in targets]
    with _undo(seq.project(), "delete track items"):
        for t in targets:
            trk.removeItem(t)
    return {"deleted": names}


@command
def razor(time: int, sequence: str | None = None, project: str | None = None, track: int | str | None = None, kind: str = "video") -> dict[str, Any]:
    seq = _get_sequence(sequence, project)
    with _undo(seq.project(), "razor"):
        if track is None:
            seq.razorAt(time)
        else:
            _get_track(seq, track, kind).razorAt(time)
    return {"razor_at": time}


@command
def add_effect(
    effect_type: str,
    track: int | str = 0,
    sequence: str | None = None,
    project: str | None = None,
    item: int | str | None = None,
    timeline_in: int | None = None,
    timeline_out: int | None = None,
    knobs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add a soft effect (e.g. Grade, Transform, Text2) over an item or a time range."""
    seq = _get_sequence(sequence, project)
    trk = _get_track(seq, track, "video")
    kwargs: dict[str, Any] = {"effectType": effect_type}
    if item is not None:
        kwargs["trackItem"] = _get_track_item(trk, item)
    else:
        if timeline_in is not None:
            kwargs["timelineIn"] = timeline_in
        if timeline_out is not None:
            kwargs["timelineOut"] = timeline_out
    with _undo(seq.project(), "add effect"):
        effect = trk.createEffect(**kwargs)
        node = effect.node()
        for knob, value in (knobs or {}).items():
            node[knob].setValue(value)
    return _effect_summary(effect)


# --------------------------------------------------------------------------- tags


def _walk_tags(bin_: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    for child in bin_.items():
        if isinstance(child, hc.Tag):
            yield path, child
        elif isinstance(child, hc.Bin):
            yield from _walk_tags(child, path + "/" + child.name() if path else child.name())


def _tag_sources(project: Any) -> list[Any]:
    """The project itself, then Hiero's built-in "Tag Presets" project."""
    startup = list(hc.projects(hc.Project.kStartupProjects))
    return [project] + [p for p in startup if p != project]


def _tag_template(project: Any, name: str) -> Any:
    for source in _tag_sources(project):
        for _, t in _walk_tags(source.tagsBin()):
            if t.name() == name:
                return t
    return None


@command
def list_project_tags(project: str | None = None) -> list[dict[str, Any]]:
    """Tags in the project's Tags bin plus Hiero's preset tags, with the bin they live in."""
    p = _get_project(project)
    out = []
    for source in _tag_sources(p):
        for path, t in _walk_tags(source.tagsBin()):
            out.append({"source": source.name(), "bin": path, "name": t.name(), "icon": _call(t, "icon"), "note": _call(t, "note")})
    return out


@command
def add_tag(
    tag: str,
    project: str | None = None,
    sequence: str | None = None,
    track: int | str | None = None,
    item: int | str | None = None,
    clip: str | None = None,
    kind: str = "video",
    note: str | None = None,
    icon: str | None = None,
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    target = _resolve_target(project, sequence, track, item, clip, kind)
    p = target.project()
    template = _tag_template(p, tag)
    new_tag = template.copy() if template is not None else hc.Tag(tag)
    if note is not None:
        new_tag.setNote(note)
    if icon is not None:
        new_tag.setIcon(icon)
    for key, value in (metadata or {}).items():
        new_tag.metadata().setValue(str(key), str(value))
    with _undo(p, "add tag"):
        target.addTag(new_tag)
    return {"target": target.name(), "tag": _tag(new_tag)}


@command
def remove_tag(
    tag: str,
    project: str | None = None,
    sequence: str | None = None,
    track: int | str | None = None,
    item: int | str | None = None,
    clip: str | None = None,
    kind: str = "video",
) -> dict[str, Any]:
    target = _resolve_target(project, sequence, track, item, clip, kind)
    matches = [t for t in target.tags() if tag in (t.name(), _call(t, "guid"))]
    if not matches:
        raise LookupError("Tag %r not found on %r" % (tag, target.name()))
    with _undo(target.project(), "remove tag"):
        for t in matches:
            target.removeTag(t)
    return {"target": target.name(), "removed": len(matches)}


# --------------------------------------------------------------------------- UI: selection, viewer, timeline


@command
def get_selection() -> dict[str, Any]:
    seq = _active_sequence()
    result: dict[str, Any] = {"sequence": _call(seq, "name"), "track_items": [], "bin_items": []}
    if seq is not None:
        for obj in _timeline_editor(seq).selection():
            if isinstance(obj, hc.TrackItem):
                result["track_items"].append(_track_item_summary(obj))
    if hui is not None:
        try:
            for obj in hui.getProjectBinView().selection():
                result["bin_items"].append({"name": _call(obj, "name"), "type": type(obj).__name__})
        except Exception:
            pass
    return result


@command
def set_selection(items: list[dict[str, Any]], sequence: str | None = None, project: str | None = None) -> dict[str, Any]:
    """items: [{"track": 0, "item": "shot010", "kind": "video"}, ...]"""
    seq = _get_sequence(sequence, project)
    targets = [_get_track_item(_get_track(seq, i.get("track", 0), i.get("kind", "video")), i["item"]) for i in items]
    _timeline_editor(seq).setSelection(targets)
    return {"selected": [t.name() for t in targets]}


@command
def open_in_timeline(sequence: str | None = None, clip: str | None = None, project: str | None = None) -> dict[str, Any]:
    if hui is None:
        raise RuntimeError("Hiero UI is not available")
    target = _get_clip(clip, project) if clip else _get_sequence(sequence, project)
    hui.openInTimeline(target)
    return {"opened": target.name()}


@command
def open_in_viewer(sequence: str | None = None, clip: str | None = None, project: str | None = None) -> dict[str, Any]:
    if hui is None:
        raise RuntimeError("Hiero UI is not available")
    target = _get_clip(clip, project) if clip else _get_sequence(sequence, project)
    hui.openInViewer(target)
    return {"opened": target.name()}


@command
def get_playhead() -> dict[str, Any]:
    viewer = hui.currentViewer() if hui is not None else None
    if viewer is None:
        raise RuntimeError("No viewer is open")
    return {"time": viewer.time(), "sequence": _call(_call(viewer.player(0), "sequence"), "name")}


@command
def set_playhead(time: int) -> dict[str, Any]:
    viewer = hui.currentViewer() if hui is not None else None
    if viewer is None:
        raise RuntimeError("No viewer is open")
    viewer.setTime(time)
    return {"time": viewer.time()}


# --------------------------------------------------------------------------- export


def _preset_summary(preset: Any) -> dict[str, Any]:
    return {
        "name": preset.name(),
        "project": _call(_call(preset, "project"), "name"),
        "type": type(preset).__name__,
        "read_only": _call(preset, "readOnly"),
    }


@command
def list_export_presets(project: str | None = None) -> list[dict[str, Any]]:
    registry = hc.taskRegistry
    presets = list(registry.localPresets())
    if project or _projects():
        presets += list(registry.projectPresets(_get_project(project)))
    return [_preset_summary(p) for p in presets]


@command
def run_export(
    preset: str,
    sequence: str | None = None,
    project: str | None = None,
    track_items: list[dict[str, Any]] | None = None,
    export_root: str | None = None,
    synchronous: bool = False,
) -> dict[str, Any]:
    """Export a sequence (or some of its track items) with a named processor preset.

    track_items: [{"track": 0, "item": "shot010"}]; omit to export the whole sequence.
    export_root overrides the preset's export root on a copy, so the saved preset is untouched.
    """
    registry = hc.taskRegistry
    seq = _get_sequence(sequence, project)
    found = registry.processorPresetByName(preset, seq.project()) or registry.processorPresetByName(preset)
    if found is None:
        raise LookupError("Export preset not found: %r (see list_export_presets)" % preset)
    job = registry.copyPreset(found)
    if export_root:
        job.properties()["exportRoot"] = export_root
    if track_items:
        items = [hc.ItemWrapper(_get_track_item(_get_track(seq, t.get("track", 0), t.get("kind", "video")), t["item"])) for t in track_items]
    else:
        items = [hc.ItemWrapper(seq)]
    registry.createAndExecuteProcessor(job, items, synchronous=synchronous)
    return {"preset": preset, "sequence": seq.name(), "items": len(items), "export_root": export_root or job.properties().get("exportRoot"), "synchronous": synchronous}
