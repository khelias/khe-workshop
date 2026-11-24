"""Shared helpers for the workshop scripts: parts, OpenSCAD renders and STL meshes."""
from __future__ import annotations

import datetime
import functools
import hashlib
import itertools
import json
import math
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import replay as replay_format

ROOT = Path(__file__).resolve().parent.parent
PARTS = ROOT / "parts"
BUILD = ROOT / "build"
CHECK_RESULTS = BUILD / "check"
REPLAYS = BUILD / "replay"
BED_MM = 260.0
BRIM_MM = 5.0  # the K2 profile's outer brim, which a plate's copies keep clear of each other
PUBLISHED_BUDGET = 10 * 1024 * 1024

_PROBLEM = re.compile(r"^.*\b(?:WARNING|ERROR)\b.*$", re.M)


class OpenScadMissing(RuntimeError):
    pass


@functools.cache
def openscad() -> str:
    path = shutil.which("openscad")
    if not path:
        raise OpenScadMissing("OpenSCAD is not on PATH. Install it with: brew install --cask openscad@snapshot")
    return path


def require_openscad() -> bool:
    """Print the install hint and return False when OpenSCAD is missing; the caller exits 2."""
    try:
        openscad()
    except OpenScadMissing as missing:
        print(missing, file=sys.stderr)
        return False
    return True


@functools.cache
def openscad_version() -> str:
    run = subprocess.run([openscad(), "--version"], capture_output=True, text=True)
    return (run.stdout + run.stderr).strip().rsplit(" ", 1)[-1]


def platform_tag() -> str:
    """Where a render ran; renders compare byte for byte only on the same one."""
    return f"{sys.platform}-{platform.machine()}"


def load_parts() -> list[dict]:
    parts = []
    for path in sorted(PARTS.glob("*/part.json")):
        part = json.loads(path.read_text(encoding="utf-8"))
        part["_dir"] = path.parent
        parts.append(part)
    return parts


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


_INCLUDE = re.compile(r"^\s*(?:include|use)\s*<([^>]+)>", re.M)


def loaded_files(part: dict) -> list[Path]:
    """The part's source and every file it includes or uses, fonts too, in the order first met."""
    found: list[Path] = []
    todo = [part["_dir"] / part["source"]]
    while todo:
        path = todo.pop(0).resolve()
        if path in found:
            continue
        if not path.is_relative_to(ROOT.resolve()) or not path.exists():
            raise SystemExit(f"FAIL {part['id']}: {path.name} is not a file in this repo; a part loads only files beside it")
        found.append(path)
        if path.suffix == ".scad":
            todo += [path.parent / name for name in _INCLUDE.findall(path.read_text(encoding="utf-8"))]
    return found


def source_files(part: dict) -> list[Path]:
    """The OpenSCAD files of a part's source, its own first."""
    return [path for path in loaded_files(part) if path.suffix == ".scad"]


def source_sha256(part: dict) -> str:
    """The source's own hash, or for a source that loads other files, a hash over each file's path
    from the repo and hash, so a change in an included file or a font rebuilds the part."""
    files = loaded_files(part)
    if len(files) == 1:
        return sha256(files[0])
    listing = "".join(f"{path.relative_to(ROOT.resolve()).as_posix()} {sha256(path)}\n" for path in files)
    return hashlib.sha256(listing.encode("utf-8")).hexdigest()


@dataclass
class Render:
    log: str
    empty: bool
    problems: list[str]


def render(source: Path, out: Path, defines: dict) -> Render:
    args = [openscad(), "--backend=manifold", "--export-format=binstl", "-o", str(out)]
    for key, value in defines.items():
        args += ["-D", f"{key}={json.dumps(value, ensure_ascii=False)}"]
    run = subprocess.run(args + [str(source)], capture_output=True, encoding="utf-8", errors="replace",
                         env={**os.environ, "LC_ALL": "C.UTF-8"})
    log = run.stdout + run.stderr
    problems = _PROBLEM.findall(log)
    empty = "top level object is empty" in log.lower()
    if run.returncode and not problems and not empty:
        problems = [f"openscad exited {run.returncode}"]
    return Render(log, empty, problems)


@dataclass
class Mesh:
    triangles: int
    nonmanifold_edges: int
    size: tuple[float, float, float]
    volume_cm3: float
    volume_mm3: float


def facets(path: Path):
    """Each facet of a binary STL as its nine vertex coordinates."""
    data = path.read_bytes()
    count = struct.unpack_from("<I", data, 80)[0]
    if len(data) != 84 + 50 * count:
        raise ValueError(f"{path.name} is not a binary STL")
    return struct.iter_unpack("<12x9f2x", memoryview(data)[84:])


def read_mesh(path: Path) -> Mesh:
    edges: Counter = Counter()
    low = [float("inf")] * 3
    high = [float("-inf")] * 3
    volume = 0.0
    kept = 0
    for values in facets(path):
        a, b, c = values[:3], values[3:6], values[6:]
        if a == b or b == c or a == c:
            continue
        kept += 1
        for vertex in (a, b, c):
            for axis in range(3):
                low[axis] = min(low[axis], vertex[axis])
                high[axis] = max(high[axis], vertex[axis])
        for start, end in ((a, b), (b, c), (c, a)):
            edges[(start, end)] += 1
        volume += (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0])
                   + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6
    bad = {frozenset(edge) for edge, seen in edges.items() if seen != 1 or edges.get((edge[1], edge[0])) != 1}
    size = tuple(round(high[axis] - low[axis], 3) for axis in range(3)) if kept else (0.0, 0.0, 0.0)
    return Mesh(kept, len(bad), size, round(abs(volume) / 1000, 1), abs(volume))


def triangles(path: Path) -> Counter:
    """The facets with vertices in micrometres, each turned to start at its lowest vertex so the
    winding stays, counted: equal for the same mesh rendered on another platform. As in
    read_mesh, a facet with two equal vertices is left out."""
    found: Counter = Counter()
    for values in facets(path):
        corners = [tuple(round(value * 1000) for value in values[n:n + 3]) for n in (0, 3, 6)]
        if len(set(corners)) < 3:
            continue
        first = corners.index(min(corners))
        found[tuple(corners[first:] + corners[:first])] += 1
    return found


SURFACE_TOLERANCE_UM = 1
_CELL_UM = 4000
_SAMPLE_UM = 500


def sub(u, v) -> list:
    return [x - y for x, y in zip(u, v)]


def _dot(u, v) -> float:
    return sum(x * y for x, y in zip(u, v))


def _point_triangle(p: tuple, tri: tuple) -> float:
    """The distance from a point to a triangle (Ericson, Real-Time Collision Detection 5.1.5)."""
    a, b, c = tri
    ab, ac, ap, bp, cp = sub(b, a), sub(c, a), sub(p, a), sub(p, b), sub(p, c)
    d1, d2 = _dot(ab, ap), _dot(ac, ap)
    d3, d4 = _dot(ab, bp), _dot(ac, bp)
    d5, d6 = _dot(ab, cp), _dot(ac, cp)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
    if d1 <= 0 and d2 <= 0:
        q = a
    elif d3 >= 0 and d4 <= d3:
        q = b
    elif d6 >= 0 and d5 <= d6:
        q = c
    elif vc <= 0 and d1 >= 0 and d3 <= 0:
        q = [a[i] + d1 / (d1 - d3) * ab[i] for i in range(3)]
    elif vb <= 0 and d2 >= 0 and d6 <= 0:
        q = [a[i] + d2 / (d2 - d6) * ac[i] for i in range(3)]
    elif va <= 0 and d4 - d3 >= 0 and d5 - d6 >= 0:
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        q = [b[i] + w * (c[i] - b[i]) for i in range(3)]
    elif va + vb + vc <= 0:
        q = min((a, b, c), key=lambda corner: math.dist(p, corner))
    else:
        v, w = vb / (va + vb + vc), vc / (va + vb + vc)
        q = [a[i] + ab[i] * v + ac[i] * w for i in range(3)]
    return math.dist(p, q)


def _open_edges(patch: list[tuple]) -> Counter:
    """The directed edges no facet of the patch turns back on, so the winding counts."""
    edges = Counter((t[i], t[(i + 1) % 3]) for t in patch for i in range(3))
    return edges - Counter({(end, start): seen for (start, end), seen in edges.items()})


def _samples(tri: tuple):
    """Points over the facet, no more than _SAMPLE_UM apart along its edges."""
    x, y, z = tri
    steps = max(2, math.ceil(max(math.dist(x, y), math.dist(y, z), math.dist(z, x)) / _SAMPLE_UM))
    for i in range(steps + 1):
        for j in range(steps + 1 - i):
            u, v = i / steps, j / steps
            yield tuple(x[k] * (1 - u - v) + y[k] * u + z[k] * v for k in range(3))


def same_surface(a: Path, b: Path) -> bool:
    """Two STL files describe one surface within SURFACE_TOLERANCE_UM. Another platform's
    floating point can triangulate a few small patches differently, so the facets that differ
    must close the same holes, and points sampled over each patch must lie within the
    tolerance of the other."""
    first, second = triangles(a), triangles(b)
    one, other = list((first - second).elements()), list((second - first).elements())
    # a few patches, not a different mesh, which would take minutes to sample
    if len(one) + len(other) > sum(first.values()) // 20 or _open_edges(one) != _open_edges(other):
        return False
    for patch, against in ((one, other), (other, one)):
        grid = _grid(against)
        if not all(any(_point_triangle(point, near) <= SURFACE_TOLERANCE_UM for near in grid.get(_cell(point), ()))
                   for tri in patch for point in _samples(tri)):
            return False
    return True


def _cell(point) -> tuple:
    return tuple(int(value // _CELL_UM) for value in point)


def _grid(tris: list[tuple]) -> dict:
    """Each triangle under every cell its box, grown by the tolerance, touches, so a point finds
    every triangle within the tolerance in its own cell."""
    grid: dict = {}
    for tri in tris:
        low = _cell([min(v[k] for v in tri) - SURFACE_TOLERANCE_UM for k in range(3)])
        high = _cell([max(v[k] for v in tri) + SURFACE_TOLERANCE_UM for k in range(3)])
        for cell in itertools.product(*(range(low[k], high[k] + 1) for k in range(3))):
            grid.setdefault(cell, []).append(tri)
    return grid


def published_exports(part: dict) -> list[dict]:
    """The exports a page offers and published/ holds; a `check_only` export is rendered by the check alone."""
    return [export for export in part["exports"] if not export.get("check_only")]


def export_problems(part: dict) -> list[str]:
    """What is wrong with the exports' `object` and `check_only` fields."""
    by_id = {export["id"]: export for export in part["exports"]}
    problems = []
    for export in part["exports"]:
        if "check_only" in export and not isinstance(export["check_only"], bool):
            problems.append(f"{export['id']}: check_only is true or false")
        if "object" not in export:
            continue
        named = by_id.get(export["object"])
        if named is None:
            problems.append(f"{export['id']}: object names no export {export['object']!r}")
        elif "object" in named:
            problems.append(f"{export['id']}: object {named['id']} is itself part of an object")
    return problems


def rendered_items(part: dict) -> list[dict]:
    """The assembly items rendered from their own defines; an export item reuses the export's file."""
    return [item for item in (part.get("assembly") or {}).get("items", []) if "defines" in item]


def item_file(part: dict, item: dict) -> str:
    if "export" in item:
        file = next((export["file"] for export in part["exports"] if export["id"] == item["export"]), None)
        if file is None:
            raise SystemExit(f"FAIL {part['id']}: assembly item {item.get('id')} names no export {item['export']!r}")
        return file
    return f"assembly-{item['id']}.stl"


def render_or_exit(part: dict, out: Path, defines: dict, what: str) -> None:
    done = render(part["_dir"] / part["source"], out, defines)
    if done.problems or done.empty:
        raise SystemExit(f"FAIL {part['id']}: {what} did not render cleanly")


def _number(value: object) -> bool:
    return type(value) in (int, float)


def _bilingual(value: object) -> bool:
    return isinstance(value, dict) and bool(value.get("et")) and bool(value.get("en"))


def _colour(value: object) -> bool:
    return bool(re.fullmatch(r"#[0-9a-fA-F]{6}", str(value)))


def _path_ok(path: object) -> bool:
    """Rows of [t, dx, dy, dz], t rising from 0 to 1."""
    if not (isinstance(path, list) and len(path) >= 2
            and all(isinstance(row, list) and len(row) == 4 and all(map(_number, row)) for row in path)):
        return False
    times = [row[0] for row in path]
    return times[0] == 0 and times[-1] == 1 and all(b > a for a, b in zip(times, times[1:]))


def assembly_problems(part: dict) -> list[str]:
    """What is wrong with the shape of a part's assembly; the renders are checked apart."""
    assembly = part.get("assembly")
    if assembly is None:
        return ["stage_items name assembly items, so they need an assembly"] if "stage_items" in part else []
    if not isinstance(assembly, dict):
        return ["assembly is an object with label, start and items"]
    problems = []
    if not _bilingual(assembly.get("label")):
        problems.append("assembly.label needs et and en")
    if not (_number(assembly.get("start")) and 0 <= assembly["start"] <= 1):
        problems.append("assembly.start is a number from 0 to 1")
    items = assembly.get("items")
    if not (isinstance(items, list) and items and all(isinstance(item, dict) for item in items)):
        return problems + ["assembly.items is a list of objects"]
    exports = {export["id"] for export in part["exports"]}
    seen = set()
    for item in items:
        name = item.get("id")
        if not (isinstance(name, str) and re.fullmatch(r"[a-z0-9-]+", name)) or name in seen:
            problems.append(f"assembly item {name!r} needs an id of its own in a-z, 0-9 and -")
        seen.add(name)
        if ("export" in item) == ("defines" in item):
            problems.append(f"assembly item {name}: give either export or defines")
        elif "export" in item and item["export"] not in exports:
            problems.append(f"assembly item {name}: no export {item['export']!r}")
        if not _colour(item.get("colour")):
            problems.append(f"assembly item {name}: colour is #rrggbb")
        if "path" in item and not _path_ok(item["path"]):
            problems.append(f"assembly item {name}: path rows are [t, dx, dy, dz], t rising from 0 to 1")
    shown = part.get("stage_items")
    if shown is not None and not (isinstance(shown, list) and shown and all(name in seen for name in shown)):
        problems.append("stage_items are ids of assembly items, the colour parts the model view draws")
    return problems


STAGE_ONLY = ("before_label", "after_label")


def plates(part: dict) -> list[dict]:
    """The plates a part was printed on, in print order. A part without `plates` is one stage
    plate made from its `replay`, and a draft, with neither, has none."""
    if "plates" in part:
        return part["plates"]
    if "replay" not in part:
        return []
    return [{"id": None, "stage": True, **part["replay"]}]


def replay_path(part: dict, plate: dict) -> Path:
    name = f"{part['id']}-{plate['id']}" if plate["id"] else part["id"]
    return REPLAYS / f"{name}.bin.gz"


def published_replay(part: dict, plate: dict) -> Path:
    name = f"replay-{plate['id']}" if plate["id"] else "replay"
    return part["_dir"] / "published" / f"{name}.bin.gz"


def plates_or_exit(part: dict) -> list[dict]:
    """The plates, for a tool that uses them before the check has looked at them."""
    problems = plate_problems(part)
    if problems:
        raise SystemExit(f"FAIL {part['id']}: {'; '.join(problems)}")
    return plates(part)


def stage_plate(part: dict) -> dict | None:
    return next((plate for plate in plates(part) if plate.get("stage")), None)


def plate_problems(part: dict) -> list[str]:
    """What is wrong with the shape of a part's plates."""
    listed = part.get("plates")
    if listed is None:
        return []
    if not (isinstance(listed, list) and listed and all(isinstance(plate, dict) for plate in listed)):
        return ["plates is a list of objects"]
    problems = []
    if "replay" in part:
        problems.append("give either replay or plates, not both")
    seen = set()
    for plate in listed:
        name = plate.get("id")
        if not (isinstance(name, str) and re.fullmatch(r"[a-z0-9-]+", name)) or name in seen:
            problems.append(f"plate {name!r} needs an id of its own in a-z, 0-9 and -")
        seen.add(name)
        if not _bilingual(plate.get("title")):
            problems.append(f"plate {name}: title needs et and en")
        if "colour" in plate and not _colour(plate["colour"]):
            problems.append(f"plate {name}: colour is #rrggbb")
        if not isinstance(plate.get("last_layer"), int):
            problems.append(f"plate {name}: last_layer is a layer number")
        if not _number(plate.get("rotate_deg")):
            problems.append(f"plate {name}: rotate_deg is a number")
        if not plate.get("stage") and any(key in plate for key in STAGE_ONLY):
            problems.append(f"plate {name}: before_label and after_label belong to the stage plate")
    if sum(bool(plate.get("stage")) for plate in listed) > 1:
        problems.append("at most one plate is the stage plate")
    if part.get("stage_inlay") and not any(plate.get("stage") for plate in listed):
        problems.append("stage_inlay needs a stage plate")
    return problems


def draft_problems(part: dict) -> list[str]:
    """A draft is published before it is printed: no proof or replay yet, and a colour for its model."""
    if "draft" not in part:
        return []
    if part["draft"] is not True or not part.get("published"):
        return ["draft is true, and only beside published: true"]
    problems = []
    if any(key in part for key in ("proof", "replay", "plates")):
        problems.append("a part with its proof and replay is no longer a draft; remove draft")
    if not _colour(part.get("stage_colour")):
        problems.append("a draft needs stage_colour, #rrggbb, since no plate gives its model a colour")
    return problems


def batch_problems(part: dict) -> list[str]:
    """What is wrong with the shape of a part's batch plates; their layout is checked apart."""
    batch = part.get("batch")
    if batch is None:
        return []
    if not (isinstance(batch, list) and batch and all(isinstance(plate, dict) for plate in batch)):
        return ["batch is a list of objects"]
    items = {item.get("id") for item in (part.get("assembly") or {}).get("items", [])}
    problems, seen = [], set()
    for plate in batch:
        name = plate.get("id")
        if not (isinstance(name, str) and re.fullmatch(r"[a-z0-9-]+", name)) or name in seen:
            problems.append(f"batch plate {name!r} needs an id of its own in a-z, 0-9 and -")
        seen.add(name)
        if not _bilingual(plate.get("title")):
            problems.append(f"batch plate {name}: title needs et and en")
        listed = plate.get("items")
        if not (isinstance(listed, list) and listed and all(item in items for item in listed)):
            problems.append(f"batch plate {name}: items are ids of assembly items")
        if not (_number(plate.get("pitch")) and plate["pitch"] > 0):
            problems.append(f"batch plate {name}: pitch is a length in mm")
        sliced = plate.get("sliced")
        if sliced is not None and not (isinstance(sliced, dict) and set(sliced) == {"seconds", "changes"}
                                       and all(type(sliced[key]) is int and sliced[key] >= 0 for key in sliced)):
            problems.append(f"batch plate {name}: sliced is {{seconds, changes}}, whole numbers")
    return problems


def stl_box(path: Path) -> tuple[list[float], list[float]]:
    """The lowest and highest corner of a binary STL's vertices."""
    columns = list(zip(*facets(path)))
    return ([min(min(column) for column in columns[axis::3]) for axis in range(3)],
            [max(max(column) for column in columns[axis::3]) for axis in range(3)])


def plate_layout(part: dict, plate: dict, path_of=None) -> dict:
    """The copies of a batch plate: a grid at the plate's pitch, centred on the bed, with as many
    rows and columns as fit with their brims inside it. Positions are each copy's centre in mm from
    the bed's centre. The footprint is read from the items' files, published/ unless `path_of`
    gives another place for a file name."""
    path_of = path_of or (lambda name: part["_dir"] / "published" / name)
    by_id = {item["id"]: item for item in part["assembly"]["items"]}
    boxes = [stl_box(path_of(item_file(part, by_id[name]))) for name in plate["items"]]
    footprint = [round(max(box[1][axis] for box in boxes) - min(box[0][axis] for box in boxes), 3) for axis in (0, 1)]
    pitch = plate["pitch"]
    counts = [max(1, math.floor((BED_MM - size - 2 * BRIM_MM) / pitch) + 1) for size in footprint]
    positions = [[round((column - (counts[0] - 1) / 2) * pitch, 3), round((row - (counts[1] - 1) / 2) * pitch, 3)]
                 for row in range(counts[1]) for column in range(counts[0])]
    return {"part": part["id"], "plate": plate["id"], "bed": BED_MM, "brim": BRIM_MM, "pitch": pitch,
            "footprint": footprint, "positions": positions}


def layout_problems(layout: dict) -> list[str]:
    """Every copy with its brim inside the bed, and no two copies' brims touching."""
    name, pitch = layout["plate"], layout["pitch"]
    problems = []
    for axis, size in enumerate(layout["footprint"]):
        reach = max(abs(position[axis]) for position in layout["positions"]) + size / 2 + BRIM_MM
        if reach > BED_MM / 2:
            problems.append(f"batch plate {name}: a copy's brim reaches {reach - BED_MM / 2:.1f} mm past the bed")
        if size + 2 * BRIM_MM >= pitch and len({position[axis] for position in layout["positions"]}) > 1:
            problems.append(f"batch plate {name}: a pitch of {pitch} mm lets the brims of copies {size:.1f} mm across touch")
    return problems


def read_published(part: dict, name: str) -> dict | None:
    """A JSON object from published/, or None when it is missing or not an object."""
    try:
        value = json.loads((part["_dir"] / "published" / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def published_problems(part: dict) -> list[str]:
    """What is wrong with a published part's files and proof, read with the standard library only."""
    folder = part["_dir"] / "published"
    problems = plate_problems(part)
    if problems:
        return problems
    build = read_published(part, "build.json")
    if build is None:
        return ["published/build.json is missing or unreadable; run scripts/build.py"]
    if build.get("source_sha256") != source_sha256(part):
        problems.append("the source changed since published/ was built")
    check = read_published(part, "check.json")
    if check is None:
        problems.append("published/check.json is missing or unreadable; run scripts/build.py")
    named = {entry.get("file"): entry.get("sha256") for key in ("exports", "assembly")
             for entry in (check or {}).get(key, []) if isinstance(entry, dict)}
    for name in [export["file"] for export in published_exports(part)] + [item_file(part, item) for item in rendered_items(part)]:
        if not (folder / name).exists():
            problems.append(f"published/{name} is missing")
        elif check is not None and sha256(folder / name) != named.get(name):
            problems.append(f"published/{name} is not the file published/check.json names")
    if part.get("draft"):
        return problems
    if not plates(part):
        problems.append("a published part needs its replay or plates, or draft: true")
    proof = part.get("proof") or {}
    printed = str(proof.get("printed"))
    try:
        valid_date = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", printed)) and bool(datetime.date.fromisoformat(printed))
    except ValueError:
        valid_date = False
    if not valid_date:
        problems.append("proof.printed is not a YYYY-MM-DD date")
    if not _bilingual(proof.get("use")):
        problems.append("proof.use needs a sentence in et and en")
    if proof.get("photo") and not (folder / proof["photo"]).exists():
        problems.append(f"proof photo published/{proof['photo']} is missing")
    for plate in plates(part):
        replay_file = published_replay(part, plate)
        name = f"published/{replay_file.name}"
        if not replay_file.exists():
            problems.append(f"{name} is missing")
            continue
        try:
            meta = replay_format.read_meta(replay_file)
            layers, starts = len(meta["layers"]), meta.get("first_layer", 1)
        except (OSError, EOFError, ValueError, KeyError) as broken:
            problems.append(f"{name} cannot be read: {broken}")
            continue
        first, last = replay_format.layer_span(plate)
        if starts != first or layers != last - first + 1:
            problems.append(f"{name} runs from layer {starts} over {layers} layers, it must run from {first} to {last}")
    return problems
