"""Run every hiero-mcp tool against a live Hiero through the MCP stdio server.

Usage:  uv run python scripts/live_check.py [--width 260]

Hiero must be running with the plugin installed. The script closes and recreates a
project named "mcp_test" (and nothing else), generates a small PNG test media set
with macOS `sips`, and saves the project to a temporary folder.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import anyio
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

REPO = Path(__file__).resolve().parents[1]
WORK = Path(tempfile.mkdtemp(prefix="hiero-mcp-live-"))
MEDIA, OUT = WORK / "media", WORK / "out"


def make_media() -> None:
    """Two 48-frame 320x180 PNG sequences (shotA, shotB) starting at frame 1001."""
    width, height = 320, 180
    for shot, (r0, g0, b0) in {"shotA": (200, 60, 40), "shotB": (40, 90, 200)}.items():
        folder = MEDIA / shot
        folder.mkdir(parents=True, exist_ok=True)
        for frame in range(1001, 1049):
            k = (frame - 1001) / 47
            pixels = bytearray()
            for y in range(height):
                for x in range(width):
                    pixels += bytes((int(r0 + (255 - r0) * x / width * k) % 256, g0, int(b0 * (1 - y / height))))
            ppm = folder / f"{shot}.{frame}.ppm"
            ppm.write_bytes(b"P6 %d %d 255\n" % (width, height) + pixels)
            subprocess.run(["sips", "-s", "format", "png", str(ppm), "--out", str(ppm.with_suffix(".png"))], check=True, capture_output=True)
            ppm.unlink()


P = "mcp_test"
STEPS = [
    ("execute_python", {"code": "import hiero.core\nfor p in hiero.core.projects():\n    if p.name() == 'mcp_test':\n        p.close()\nresult = [p.name() for p in hiero.core.projects()]"}),
    ("get_app_info", {}),
    ("list_formats", {}),
    ("execute_python", {"code": "import hiero.core\nresult = sorted(k for k in hiero.core.env.keys())"}),
    ("new_project", {"name": P}),
    ("list_projects", {}),
    ("get_project", {"project": P}),
    ("create_bin", {"project": P, "bin_path": "Footage/Day1"}),
    ("import_media", {"project": P, "bin_path": "Footage/Day1", "paths": [f"{MEDIA}/shotA/shotA.1001.png", f"{MEDIA}/shotB"]}),
    ("list_bin", {"project": P}),
    ("get_clip", {"project": P, "clip": "Footage/Day1/shotA"}),
    ("create_sequence", {"project": P, "name": "edit_v001", "bin_path": "Edit", "framerate": 24, "format": "HD_1080", "video_tracks": 1, "audio_tracks": 1}),
    ("list_sequences", {"project": P}),
    ("add_clip_to_track", {"project": P, "sequence": "edit_v001", "clip": "Footage/Day1/shotA"}),
    ("add_clip_to_track", {"project": P, "sequence": "edit_v001", "clip": "shotB"}),
    ("add_track", {"project": P, "sequence": "edit_v001", "name": "VFX"}),
    ("update_track", {"project": P, "sequence": "edit_v001", "track": "VFX", "locked": False, "enabled": True, "blend_enabled": False}),
    ("list_track_items", {"project": P, "sequence": "edit_v001"}),
    ("get_track_item", {"project": P, "sequence": "edit_v001", "track": 0, "item": 0}),
    ("update_track_item", {"project": P, "sequence": "edit_v001", "track": 0, "item": 0, "name": "sh010", "source_in": 4}),
    ("update_track_item", {"project": P, "sequence": "edit_v001", "track": 0, "item": 1, "name": "sh020", "move_to": 60}),
    ("update_track_item", {"project": P, "sequence": "edit_v001", "track": 0, "item": "sh020", "source_out": 40, "timeline_in": 62}),
    ("add_tag", {"project": P, "sequence": "edit_v001", "track": 0, "item": "sh020", "tag": "Approved"}),
    ("razor", {"project": P, "sequence": "edit_v001", "time": 80, "track": 0}),
    ("add_effect", {"project": P, "sequence": "edit_v001", "track": 0, "item": "sh010", "effect_type": "Grade", "knobs": {"white": 1.2}}),
    ("add_tag", {"project": P, "sequence": "edit_v001", "track": 0, "item": "sh010", "tag": "Note", "note": "check edge", "metadata": {"status": "wip"}}),
    ("add_tag", {"project": P, "clip": "Footage/Day1/shotA", "tag": "Approved"}),
    ("list_project_tags", {"project": P}),
    ("get_sequence", {"project": P, "sequence": "edit_v001", "include_items": True}),
    ("open_in_timeline", {"project": P, "sequence": "edit_v001"}),
    ("set_selection", {"project": P, "sequence": "edit_v001", "items": [{"track": 0, "item": "sh010"}]}),
    ("get_selection", {}),
    ("open_in_viewer", {"project": P, "sequence": "edit_v001"}),
    ("set_playhead", {"time": 12}),
    ("get_playhead", {}),
    ("remove_tag", {"project": P, "sequence": "edit_v001", "track": 0, "item": "sh010", "tag": "Note"}),
    ("update_sequence", {"project": P, "sequence": "edit_v001", "timecode_start": 86400, "in_time": 0, "out_time": 40}),
    ("set_clip_version", {"project": P, "clip": "shotB", "version": "max"}),
    ("rename_bin_item", {"project": P, "path": "Footage/Day1/shotB", "new_name": "shotB_plate"}),
    ("move_bin_item", {"project": P, "path": "Footage/Day1/shotB_plate", "to_bin": "Footage/Day2"}),
    ("reconnect_media", {"project": P, "clip": "Footage/Day1/shotA", "path": f"{MEDIA}/shotA"}),
    ("list_export_presets", {"project": P}),
    ("delete_track_items", {"project": P, "sequence": "edit_v001", "track": 0, "items": [0]}),
    ("undo", {"project": P}),
    ("redo", {"project": P}),
    ("delete_track", {"project": P, "sequence": "edit_v001", "track": "VFX"}),
    ("save_project", {"project": P, "path": f"{OUT}/mcp_test.hrox"}),
    ("delete_bin_item", {"project": P, "path": "Footage/Day2"}),
]

async def main(width: int) -> int:
    params = StdioServerParameters(command="uv", args=["run", "--project", str(REPO), "hiero-mcp"])
    ok = fail = 0
    async with Client(params, read_timeout_seconds=120) as c:
        for name, args in STEPS:
            r = await c.call_tool(name, args)
            if r.is_error:
                fail += 1
                print(f"FAIL {name}: {r.content[0].text[:700]}")
            else:
                ok += 1
                sc = r.structured_content
                if sc is not None and set(sc) == {"result"}:
                    sc = sc["result"]
                body = json.dumps(sc if sc is not None else r.content[0].text, default=str)
                print(f"ok   {name}: {body[:width]}")
    print(f"\n{ok} ok, {fail} failed  (work dir: {WORK})")
    return 1 if fail else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--width", type=int, default=260, help="max characters of each result to print")
    opts = parser.parse_args()
    make_media()
    OUT.mkdir(parents=True, exist_ok=True)
    sys.exit(anyio.run(main, opts.width))
