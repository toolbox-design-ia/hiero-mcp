"""Bridge command logic against a minimal fake of hiero.core (Hiero itself is not importable here)."""

from __future__ import annotations

import importlib
import sys
import types
from typing import Any

import pytest


class _Base:
    def __init__(self, name: str = "") -> None:
        self._name = name

    def name(self) -> str:
        return self._name

    def guid(self) -> str:
        return "guid-" + self._name


def _fake_hiero() -> types.ModuleType:
    core = types.ModuleType("hiero.core")
    for cls in ("Bin", "BinItem", "Clip", "Tag", "AudioTrack", "VideoTrack", "TrackItem", "ItemWrapper", "TimeBase"):
        setattr(core, cls, type(cls, (_Base,), {}))

    class TrackItem(core.TrackItem):  # type: ignore[name-defined]
        """Follows Hiero's documented semantics: move() is relative, trims keep playback speed."""

        def __init__(self, name: str, tin: int, tout: int, sin: float, speed: float = 1.0) -> None:
            super().__init__(name)
            self.tin, self.tout, self.sin, self.speed = tin, tout, sin, speed
            self.track: Any = None

        def timelineIn(self) -> int:
            return self.tin

        def timelineOut(self) -> int:
            return self.tout

        def sourceIn(self) -> float:
            return self.sin

        def sourceOut(self) -> float:
            return self.sin + (self.tout - self.tin) * self.speed

        def playbackSpeed(self) -> float:
            return self.speed

        def setPlaybackSpeed(self, speed: float) -> None:
            self.speed = speed

        def move(self, delta: int) -> None:
            self.tin += delta
            self.tout += delta

        def trimIn(self, frames: int) -> None:
            self.tin += frames
            self.sin += frames * self.speed

        def trimOut(self, frames: int) -> None:
            self.tout -= frames

        def parentTrack(self) -> Any:
            return self.track

    class VideoTrack(core.VideoTrack):  # type: ignore[name-defined]
        def __init__(self, name: str, items: list[Any]) -> None:
            super().__init__(name)
            self._items = items
            for item in items:
                item.track = self

        def items(self) -> list[Any]:
            return self._items

    class Project(_Base):
        kStartupProjects = 2

        def __init__(self, name: str, seq: Any) -> None:
            super().__init__(name)
            self._seq = seq
            self.undo_log: list[str] = []

        def sequences(self) -> list[Any]:
            return [self._seq]

        def beginUndo(self, label: str) -> None:
            self.undo_log.append("begin " + label)

        def endUndo(self) -> None:
            self.undo_log.append("end")

    class Sequence(_Base):
        def __init__(self, name: str, tracks: list[Any]) -> None:
            super().__init__(name)
            self._tracks = tracks
            self._project: Any = None

        def videoTracks(self) -> list[Any]:
            return self._tracks

        def audioTracks(self) -> list[Any]:
            return []

        def project(self) -> Any:
            return self._project

    core.TrackItem = TrackItem
    core.VideoTrack = VideoTrack
    core.Sequence = Sequence
    core.Project = Project
    return core


@pytest.fixture()
def env(monkeypatch: pytest.MonkeyPatch):
    core = _fake_hiero()
    hiero = types.ModuleType("hiero")
    hiero.core = core  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hiero", hiero)
    monkeypatch.setitem(sys.modules, "hiero.core", core)
    monkeypatch.setitem(sys.modules, "hiero.ui", None)  # import fails -> terminal mode

    shot = core.TrackItem("sh010", tin=10, tout=57, sin=0)
    other = core.TrackItem("sh020", tin=100, tout=147, sin=0, speed=2.0)
    seq = core.Sequence("edit", [core.VideoTrack("V1", [shot, other])])
    project = core.Project("demo", seq)
    seq._project = project
    core.projects = lambda *flags: [project]

    sys.modules.pop("hiero_mcp.hiero_plugin.hiero_mcp_bridge.commands", None)
    commands = importlib.import_module("hiero_mcp.hiero_plugin.hiero_mcp_bridge.commands")
    yield commands, shot, other, project
    sys.modules.pop("hiero_mcp.hiero_plugin.hiero_mcp_bridge.commands", None)


def _update(commands: Any, item: str, monkeypatch: pytest.MonkeyPatch, **kw: Any) -> None:
    # Skip the result serialiser, which would need many more fake methods.
    monkeypatch.setattr(commands, "_track_item_detail", lambda ti: None)
    commands.update_track_item(item=item, sequence="edit", **kw)


def test_move_to_is_absolute(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    commands, shot, _, project = env
    _update(commands, "sh010", monkeypatch, move_to=60)
    assert (shot.tin, shot.tout, shot.sin) == (60, 107, 0)
    assert project.undo_log == ["begin MCP: update track item", "end"]


def test_source_in_trims_head_without_retiming(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    commands, shot, _, _ = env
    _update(commands, "sh010", monkeypatch, source_in=4)
    assert (shot.tin, shot.sin, shot.speed) == (14, 4, 1.0)


def test_source_out_trims_tail(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    commands, shot, _, _ = env
    _update(commands, "sh010", monkeypatch, source_out=40)
    assert (shot.tout, shot.sourceOut(), shot.speed) == (50, 40, 1.0)


def test_source_trims_respect_playback_speed(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    commands, _, other, _ = env
    _update(commands, "sh020", monkeypatch, source_in=10)
    assert (other.tin, other.sin, other.speed) == (105, 10, 2.0)


def test_timeline_trims(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    commands, shot, _, _ = env
    _update(commands, "sh010", monkeypatch, timeline_in=12, timeline_out=50)
    assert (shot.tin, shot.tout, shot.sin) == (12, 50, 2)
