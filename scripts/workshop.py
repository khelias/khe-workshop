"""Shared helpers for the workshop scripts: parts, OpenSCAD renders and STL meshes."""
from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

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


def read_mesh(path: Path) -> Mesh:
    data = path.read_bytes()
    count = struct.unpack_from("<I", data, 80)[0]
    if len(data) != 84 + 50 * count:
        raise ValueError(f"{path.name} is not a binary STL")
    edges: Counter = Counter()
    low = [float("inf")] * 3
    high = [float("-inf")] * 3
    volume = 0.0
    kept = 0
    for values in struct.iter_unpack("<12x9f2x", memoryview(data)[84:]):
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
