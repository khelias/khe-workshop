"""Shared helpers for the workshop scripts: parts, OpenSCAD renders and STL meshes."""
from __future__ import annotations

import datetime
import functools
import hashlib
import json
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
PUBLISHED_BUDGET = 5 * 1024 * 1024

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


def triangles(path: Path) -> list[tuple]:
    """The facets with vertices in micrometres, each turned to start at its lowest vertex so the
    winding stays, then sorted: equal for the same mesh rendered on another platform. As in
    read_mesh, a facet with two equal vertices is left out."""
    found = []
    for values in facets(path):
        corners = [tuple(round(value * 1000) for value in values[n:n + 3]) for n in (0, 3, 6)]
        if len(set(corners)) < 3:
            continue
        first = corners.index(min(corners))
        found.append(tuple(corners[first:] + corners[:first]))
    return sorted(found)


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
    named = {item.get("file"): item.get("sha256") for item in (check or {}).get("exports", []) if isinstance(item, dict)}
    for export in part["exports"]:
        stl = folder / export["file"]
        if not stl.exists():
            problems.append(f"published/{export['file']} is missing")
        elif check is not None and sha256(stl) != named.get(export["file"]):
            problems.append(f"published/{export['file']} is not the file published/check.json names")
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
            layers = len(replay_format.read_meta(replay_file)["layers"])
        except (OSError, EOFError, ValueError, KeyError) as broken:
            problems.append(f"published/replay.bin.gz cannot be read: {broken}")
        else:
            if layers != part["replay"]["last_layer"]:
                problems.append(f"the replay has {layers} layers, it must stop at {part['replay']['last_layer']}")
    return problems
