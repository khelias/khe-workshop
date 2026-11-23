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
    return Mesh(kept, len(bad), size, round(abs(volume) / 1000, 1))


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
        return []
    if not isinstance(assembly, dict):
        return ["assembly is an object with label, start and items"]
    problems = []
    label = assembly.get("label") or {}
    if not (isinstance(label, dict) and label.get("et") and label.get("en")):
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
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(item.get("colour"))):
            problems.append(f"assembly item {name}: colour is #rrggbb")
        if "path" in item and not _path_ok(item["path"]):
            problems.append(f"assembly item {name}: path rows are [t, dx, dy, dz], t rising from 0 to 1")
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
    problems = []
    build = read_published(part, "build.json")
    if build is None:
        return ["published/build.json is missing or unreadable; run scripts/build.py"]
    if build.get("source_sha256") != sha256(part["_dir"] / part["source"]):
        problems.append("the source changed since published/ was built")
    check = read_published(part, "check.json")
    if check is None:
        problems.append("published/check.json is missing or unreadable; run scripts/build.py")
    named = {entry.get("file"): entry.get("sha256") for key in ("exports", "assembly")
             for entry in (check or {}).get(key, []) if isinstance(entry, dict)}
    for name in [export["file"] for export in part["exports"]] + [item_file(part, item) for item in rendered_items(part)]:
        if not (folder / name).exists():
            problems.append(f"published/{name} is missing")
        elif check is not None and sha256(folder / name) != named.get(name):
            problems.append(f"published/{name} is not the file published/check.json names")
    proof = part.get("proof") or {}
    printed = str(proof.get("printed"))
    try:
        valid_date = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", printed)) and bool(datetime.date.fromisoformat(printed))
    except ValueError:
        valid_date = False
    if not valid_date:
        problems.append("proof.printed is not a YYYY-MM-DD date")
    use = proof.get("use") or {}
    if not (isinstance(use, dict) and use.get("et") and use.get("en")):
        problems.append("proof.use needs a sentence in et and en")
    if proof.get("photo") and not (folder / proof["photo"]).exists():
        problems.append(f"proof photo published/{proof['photo']} is missing")
    replay_file = folder / "replay.bin.gz"
    if not replay_file.exists():
        problems.append("published/replay.bin.gz is missing")
    else:
        try:
            meta = replay_format.read_meta(replay_file)
            layers, starts = len(meta["layers"]), meta.get("first_layer", 1)
        except (OSError, EOFError, ValueError, KeyError) as broken:
            problems.append(f"published/replay.bin.gz cannot be read: {broken}")
        else:
            first, last = replay_format.layer_span(part["replay"])
            if starts != first or layers != last - first + 1:
                problems.append(f"the replay runs from layer {starts} over {layers} layers, it must run from {first} to {last}")
    return problems
