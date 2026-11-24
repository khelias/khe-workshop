#!/usr/bin/env python3
"""Print the layout of one of a part's batch plates: where each copy's centre stands on the bed.

  plate.py <part> <plate> [--json]

With --json it prints the layout as k2_slice.py --layout reads it. The footprint comes from the
part's published files, so run scripts/build.py first.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import workshop as ws  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("part")
    parser.add_argument("plate")
    parser.add_argument("--json", action="store_true", help="print the layout as JSON")
    args = parser.parse_args()
    part = next((part for part in ws.load_parts() if part["id"] == args.part), None)
    plate = next((plate for plate in (part or {}).get("batch") or [] if plate.get("id") == args.plate), None)
    if plate is None:
        print(f"FAIL: {args.part} has no batch plate {args.plate}", file=sys.stderr)
        return 1
    problems = ws.batch_problems(part)
    if problems:
        print(f"FAIL {part['id']}: {'; '.join(problems)}", file=sys.stderr)
        return 1
    layout = ws.plate_layout(part, plate)
    if args.json:
        print(json.dumps(layout))
    else:
        width, depth = layout["footprint"]
        print(f"{len(layout['positions'])} copies of {width} x {depth} mm at {layout['pitch']} mm on the {ws.BED_MM:.0f} mm bed")
        for x, y in layout["positions"]:
            print(f"  {x:8.2f} {y:8.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
