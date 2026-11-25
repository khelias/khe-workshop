#!/usr/bin/env python3
"""Write one self-contained page that shows a part from outside the repo in the room's stage.

  preview.py DIR/part.json --out OUT.html [--lang et|en]

The part.json names ready STL files with their colours and, optionally, the sliced G-code:
  {"title": {"et": "...", "en": "..."},
   "items": [{"id": "body", "stl": "body.stl", "colour": "#ffffff"}, ...],
   "gcode": "part.gcode.3mf", "facts": ["2 h 5 min", ...]}
Paths are relative to the part.json. The page is the room's part stage (stage.js, room.css and the
controls): the model in its colours, the colour parts apart, and the replay of the G-code with each
tool in its colour. The modules, three.js and the data are inlined, so the one file opens anywhere.
It is a private preview: it never enters the room or a public build, and nothing in it is checked
like a part of the repo.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import posixpath
import re
import struct
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import replay as replay_format  # noqa: E402
import site_build  # noqa: E402
import workshop as ws  # noqa: E402

MODULE_ROOT = "khe-room/"
WHOLE = "whole.stl"
REPLAY = "replay.bin.gz"  # the name the room's stage gives a one-plate replay (workshop.published_replay)
# The colour parts rise apart by this much each in the parts view, to show what hides inside.
APART_MM = 12
TEXT = {"et": {"label": "Värvid", "lead": "Eelvaade enne printimist"},
        "en": {"label": "Colours", "lead": "Preview before printing"}}

# Runs before any module: unpacks the data into blob URLs, joins the colour parts into the whole
# model the stage frames and cuts, puts the URLs into the stage config, then starts the room.
BOOT = """(async () => {
  const payload = document.querySelector('[data-preview-files]');
  const files = JSON.parse(payload.textContent);
  payload.remove();
  const unpack = async (text) => {
    const stream = (await fetch(`data:application/gzip;base64,${text}`)).body.pipeThrough(new DecompressionStream('gzip'));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  };
  const data = Object.fromEntries(await Promise.all(Object.entries(files.data).map(async ([name, text]) => [name, await unpack(text)])));
  const parts = files.whole.map((name) => data[name]);
  const count = parts.reduce((sum, stl) => sum + (stl.length - 84) / 50, 0);
  const whole = new Uint8Array(84 + count * 50);
  new DataView(whole.buffer).setUint32(80, count, true);
  let at = 84;
  for (const stl of parts) { whole.set(stl.subarray(84), at); at += stl.length - 84; }
  data[files.wholeName] = whole;
  const urls = Object.fromEntries(Object.entries(data).map(([name, bytes]) => [name, URL.createObjectURL(new Blob([bytes]))]));
  const fill = (value) => {
    if (typeof value === 'string') return value.startsWith('preview:') ? urls[value.slice(8)] : value;
    if (Array.isArray(value)) return value.map(fill);
    if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, fill(item)]));
    return value;
  };
  for (const node of document.querySelectorAll('[data-stage-config]')) {
    node.textContent = JSON.stringify(fill(JSON.parse(node.textContent)));
  }
  const start = document.createElement('script');
  start.type = 'module';
  start.textContent = "import 'khe-room/src/main.js';";
  document.head.append(start);
})();"""


class Refused(Exception):
    """The part.json cannot be previewed as it is."""


class PreviewSite(site_build.Site):
    """The room's stage for one external part, its data named for the boot script to fill in."""

    close_up = True

    def __init__(self) -> None:
        self.out, self.base, self.parts = None, None, []

    def data_link(self, part: dict, depth: int, name: str) -> str:
        return f"preview:{name}"


def module_map() -> dict[str, str]:
    """Every module of web/ as a data URL under a bare name, its relative imports made bare too."""
    web = ws.ROOT / "web"
    modules = {}
    for path in sorted([*(web / "src").glob("*.js"), *(web / "vendor").rglob("*.js")]):
        here = path.parent.relative_to(web).as_posix()

        def bare(match: re.Match) -> str:
            target = posixpath.normpath(posixpath.join(here, match[3]))
            if target.startswith("../"):
                raise SystemExit(f"FAIL: {path.name} imports {match[3]}, outside web/")
            return f"{match[1]}{match[2]}{MODULE_ROOT}{target}{match[2]}"

        code = site_build.SPECIFIER.sub(bare, path.read_text(encoding="utf-8"))
        modules[MODULE_ROOT + path.relative_to(web).as_posix()] = (
            "data:text/javascript;base64," + base64.b64encode(code.encode("utf-8")).decode("ascii"))
    return modules


def read_gcode(path: Path) -> str:
    if path.suffix == ".3mf":
        with zipfile.ZipFile(path) as archive:
            return archive.read("Metadata/plate_1.gcode").decode("utf-8", "replace")
    raw = path.read_bytes()
    return (gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw).decode("utf-8", "replace")


def load(spec_path: Path) -> tuple[dict, dict[str, bytes], tuple[dict, dict] | None]:
    """The part's settings, its files' bytes by name and the replay's plate and metadata."""
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    folder = spec_path.parent
    items = spec.get("items") or []
    if not items:
        raise Refused("part.json lists no items")
    files, seen = {}, set()
    for item in items:
        if not (isinstance(item.get("id"), str) and re.fullmatch(r"[\w-]+", item["id"]) and item["id"] not in seen):
            raise Refused(f"each item needs its own id of letters, digits, - or _, not {item.get('id')!r}")
        seen.add(item["id"])
        if not ws._colour(item.get("colour")):
            raise Refused(f"item {item['id']} needs a colour as #rrggbb")
        path = folder / item["stl"]
        ws.facets(path)
        files[f"{item['id']}.stl"] = path.read_bytes()
    plate = None
    if spec.get("gcode"):
        text = read_gcode(folder / spec["gcode"])
        total = replay_format._TOTAL_LAYERS.search(text)
        if not total:
            raise Refused(f"{spec['gcode']} does not say how many layers it has")
        meta, records = replay_format.parse(text, int(total.group(1)), tool_colours=True)
        plate = ({"id": None, "stage": True, "rotate_deg": 0}, meta)
        files[REPLAY] = replay_format.encode(meta, records)
    return spec, files, plate


def page(spec: dict, files: dict[str, bytes], plate: tuple[dict, dict] | None, lang: str) -> str:
    given = spec.get("title") or {}
    title = {code: given.get(code) or given.get("et") or given.get("en") or "Preview" for code in site_build.LANGS}
    items = spec["items"]
    part = {
        "id": "preview", "_dir": Path("."), "title": title, "stage_export": "whole",
        "exports": [{"id": "whole", "file": WHOLE}] + [{"id": item["id"], "file": f"{item['id']}.stl"} for item in items],
        "assembly": {"start": 0, "label": {code: TEXT[code]["label"] for code in site_build.LANGS},
                     "items": [{"id": item["id"], "export": item["id"], "colour": item["colour"],
                                "path": [[0, 0, 0, 0], [1, 0, 0, index * APART_MM]]} for index, item in enumerate(items)]},
        "stage_items": [item["id"] for item in items],
    }
    if not plate:
        part["stage_colour"] = items[0]["colour"]
    metas = [plate] if plate else []
    stage = PreviewSite().stage(part, lang, 0, metas)
    facts = "".join(f'<li class="fact">{site_build.esc(fact)}</li>' for fact in spec.get("facts") or [])
    payload = {"data": {name: base64.b64encode(gzip.compress(data, 6, mtime=0)).decode("ascii") for name, data in files.items()},
               "whole": [f"{item['id']}.stl" for item in items], "wholeName": WHOLE}
    importmap = json.dumps({"imports": module_map()})
    css = (ws.ROOT / "web" / "src" / "room.css").read_text(encoding="utf-8")
    return f"""<!doctype html>
<html lang="{lang}" data-room="workshop">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{site_build.esc(title[lang])}</title>
<style>{css}</style>
<script type="importmap">{importmap}</script>
<script type="application/json" data-preview-files>{json.dumps(payload)}</script>
<script>{BOOT}</script>
</head>
<body>
<main class="room">
<section class="band">
<header class="room__head">
<p class="label">{TEXT[lang]['lead']}</p>
<h1>{site_build.esc(title[lang])}</h1>
<ul class="facts">{facts}</ul>
</header>
{stage}
</section>
</main>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("part", type=Path, help="the part.json of the external part")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--lang", choices=site_build.LANGS, default="et")
    args = parser.parse_args()
    try:
        spec, files, plate = load(args.part)
    except Refused as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, struct.error, zipfile.BadZipFile) as error:
        print(f"FAIL: cannot read {args.part}: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page(spec, files, plate, args.lang), encoding="utf-8")
    print(f"preview: {args.out} ({args.out.stat().st_size // 1024} kB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
