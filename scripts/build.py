#!/usr/bin/env python3
"""Write published/ for every part marked published: STL files, replay, check results and build.json."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import workshop as ws  # noqa: E402


def build(part: dict) -> None:
    folder = part["_dir"] / "published"
    folder.mkdir(exist_ok=True)
    source = part["_dir"] / part["source"]
    for export in part["exports"]:
        ws.render_or_exit(part, folder / export["file"], export["defines"], export["id"])
    for item in ws.rendered_items(part):
        ws.render_or_exit(part, folder / ws.item_file(part, item), item["defines"], f"assembly {item['id']}")
    named = set()
    for plate in ws.plates_or_exit(part):
        replay = ws.replay_path(part, plate)
        if not replay.exists():
            raise SystemExit(f"FAIL {part['id']}: run scripts/replay.py first, {replay.name} is missing")
        target = ws.published_replay(part, plate)
        shutil.copyfile(replay, target)
        named.add(target.name)
    for stale in folder.glob("replay*.bin.gz"):
        if stale.name not in named:
            stale.unlink()
    results = ws.CHECK_RESULTS / f"{part['id']}.json"
    if not results.exists():
        raise SystemExit(f"FAIL {part['id']}: run scripts/check.py first")
    shutil.copyfile(results, folder / "check.json")
    (folder / "build.json").write_text(json.dumps({
        "openscad": ws.openscad_version(), "platform": ws.platform_tag(),
        "source_sha256": ws.sha256(source)}, indent=1) + "\n", encoding="utf-8")


def main() -> int:
    if not ws.require_openscad():
        return 2
    for part in ws.load_parts():
        if part.get("published"):
            build(part)
            print(f"built {part['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
