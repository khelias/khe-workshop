#!/usr/bin/env python3
"""Turn printed G-code into compact replay data for the room.

The file is gzip over: magic, a u32 metadata length, JSON metadata, then one column
each of record kinds, dx low bytes, dx high bytes, dy low bytes and dy high bytes.
A record moves the head by (dx, dy) in units of 1/scale mm. Kind 0 is a travel move;
any other kind is an extrusion of the feature kinds[kind - 1]. Deltas are zigzag coded.
With tool colours (metadata tool_colours, for the private preview of a slice) an extrusion's kind
byte also holds its tool in the high four bits, and tool_colours[tool] is that tool's colour.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import re
import struct
import sys
from array import array
from pathlib import Path

MAGIC = b"KHERPL01"
SCALE = 100
TOLERANCE = 2.0
ARC_TOLERANCE_MM = 0.02
MAX_MERGED = 64
BUDGET = 1_500_000

FEATURES = {
    "outer wall": "outer-wall", "overhang wall": "outer-wall", "inner wall": "inner-wall",
    "sparse infill": "infill", "internal solid infill": "solid", "solid infill": "solid",
    "top surface": "solid", "bottom surface": "solid", "gap infill": "gap",
    "bridge": "bridge", "internal bridge": "bridge", "support": "support",
    "support interface": "support", "brim": "brim",
}
KINDS = ["outer-wall", "inner-wall", "infill", "solid", "gap", "bridge", "support", "brim", "other"]
WALL_KIND = KINDS.index("outer-wall") + 1
KIND_MASK = 15  # the low bits of a kind byte; with tool colours the tool is above them
OTHER_KIND = KINDS.index("other") + 1
MOVES = {"G0", "G1", "G2", "G3"}
_REMAINING = re.compile(r"\bR(\d+)")
_WORD = re.compile(r"([XYIJEF])(-?\d*\.?\d+)")
_LAYER_Z = re.compile(r"^;Z?:(-?\d*\.?\d+)")
_TOTAL_LAYERS = re.compile(r"^; total lay(?:ers count = |er number: )(\d+)", re.M)
_COLOURS = re.compile(r"^; filament_colour = ([#\w;]+)", re.M)
_ESTIMATE = re.compile(r"^; estimated printing time \(normal mode\) = (.+)$", re.M)
_FILAMENT = re.compile(r"^; filament used \[g\] = ([\d., ]+)$", re.M)


def setting(text: str, key: str) -> str | None:
    found = re.search(rf"^; {key} = (.+)$", text, re.M)
    return found.group(1).split(";")[0].strip() if found else None


def read_meta(path: Path) -> dict:
    with gzip.open(path, "rb") as stream:
        if stream.read(len(MAGIC)) != MAGIC:
            raise ValueError(f"{path.name} is not replay data")
        size = struct.unpack("<I", stream.read(4))[0]
        return json.loads(stream.read(size))


def unzigzag(value: int) -> int:
    return (value >> 1) ^ -(value & 1)


def read_replay(path: Path) -> tuple[dict, bytes, list[float], list[float]]:
    """The metadata, record kinds and absolute positions in mm, the reader beside encode()."""
    body = gzip.decompress(path.read_bytes())
    if not body.startswith(MAGIC):
        raise ValueError(f"{path.name} is not replay data")
    size = struct.unpack_from("<I", body, len(MAGIC))[0]
    start = len(MAGIC) + 4 + size
    meta = json.loads(body[len(MAGIC) + 4:start])
    count = meta["records"]
    kinds, dx_low, dx_high, dy_low, dy_high = (body[start + count * n:start + count * (n + 1)] for n in range(5))
    if meta.get("tool_colours"):
        kinds = bytes(kind & KIND_MASK for kind in kinds)
    xs: list[float] = []
    ys: list[float] = []
    x = y = 0
    for index in range(count):
        x += unzigzag(dx_low[index] | dx_high[index] << 8)
        y += unzigzag(dy_low[index] | dy_high[index] << 8)
        xs.append(x / meta["scale"])
        ys.append(y / meta["scale"])
    return meta, kinds, xs, ys


def duration_seconds(text: str) -> float:
    units = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    return float(sum(int(value) * units[unit] for value, unit in re.findall(r"(\d+)([dhms])", text)))


def arc_points(x0: float, y0: float, x1: float, y1: float, i: float, j: float, clockwise: bool) -> list[tuple[float, float]]:
    cx, cy = x0 + i, y0 + j
    radius = math.hypot(i, j)
    start = math.atan2(y0 - cy, x0 - cx)
    sweep = math.atan2(y1 - cy, x1 - cx) - start
    if clockwise and sweep >= 0:
        sweep -= math.tau
    elif not clockwise and sweep <= 0:
        sweep += math.tau
    step = 2 * math.acos(max(0.0, 1 - ARC_TOLERANCE_MM / radius)) if radius > ARC_TOLERANCE_MM else math.pi
    count = max(1, math.ceil(abs(sweep) / step))
    points = [(cx + radius * math.cos(start + sweep * n / count), cy + radius * math.sin(start + sweep * n / count))
              for n in range(1, count)]
    return points + [(x1, y1)]


class Records:
    """Quantised records, with nearly straight runs of one feature merged."""

    def __init__(self, tolerance: float = TOLERANCE) -> None:
        self.tolerance = tolerance
        self.kinds = array("B")
        self.xs = array("i")
        self.ys = array("i")
        self.barrier = 0
        self.merged: list[tuple[int, int]] = []

    def mark_layer(self) -> int:
        self.barrier = len(self.kinds)
        self.merged = []
        return self.barrier

    def _replace_last(self, kind: int, x: int, y: int) -> None:
        self.kinds[-1], self.xs[-1], self.ys[-1] = kind, x, y

    def _straight(self, x: int, y: int) -> bool:
        ax, ay = self.xs[-2], self.ys[-2]
        dx, dy = x - ax, y - ay
        length = math.hypot(dx, dy)
        if length == 0:
            return False
        return all(abs((px - ax) * dy - (py - ay) * dx) / length <= self.tolerance for px, py in self.merged)

    def add(self, kind: int, x_mm: float, y_mm: float) -> None:
        x, y = round(x_mm * SCALE), round(y_mm * SCALE)
        count = len(self.kinds)
        if count and self.xs[-1] == x and self.ys[-1] == y:
            return
        if kind == 0 and count > self.barrier and self.kinds[-1] == 0:
            self._replace_last(0, x, y)
            return
        mergeable = kind and count >= self.barrier + 2 and self.kinds[-1] == kind and len(self.merged) < MAX_MERGED
        if mergeable:
            self.merged.append((self.xs[-1], self.ys[-1]))
            if self._straight(x, y):
                self._replace_last(kind, x, y)
                return
        self.merged = []
        self.kinds.append(kind)
        self.xs.append(x)
        self.ys.append(y)


def spread_times(times: list[float]) -> list[float]:
    """Slicers report time coarsely, so layers sharing a value are spaced evenly to the next one."""
    spread = list(times)
    start = 0
    while start < len(times):
        end = start
        while end + 1 < len(times) and times[end + 1] == times[start]:
            end += 1
        if end > start and end + 1 < len(times):
            gap = (times[end + 1] - times[start]) / (end + 1 - start)
            for index in range(start, end + 1):
                spread[index] = times[start] + gap * (index - start)
        start = end + 1
    return spread


def layer_span(settings: dict) -> tuple[int, int]:
    """The first and last layer a part's replay settings cover."""
    return settings.get("first_layer", 1), settings["last_layer"]


def parse(text: str, last_layer: int, first_layer: int = 1, tolerance: float = TOLERANCE,
          tool_colours: bool = False) -> tuple[dict, Records]:
    """Layers first_layer to last_layer. Layers below first_layer are followed but not recorded;
    with first_layer above 1 the metadata says where the replay starts and what lay below it.
    With tool_colours each extrusion records its tool, so a viewer draws it in that tool's colour."""
    records = Records(tolerance)
    estimate = _ESTIMATE.search(text)
    total_seconds = duration_seconds(estimate.group(1)) if estimate else 0.0
    colours_match = _COLOURS.search(text)
    colours = colours_match.group(1).split(";") if colours_match else ["#808080"]
    total_match = _TOTAL_LAYERS.search(text)
    layers: list[list[float]] = []
    times: list[float] = []
    changes: list[dict] = []
    x = y = e = 0.0
    relative_e = True
    exact_times = ";TIME_ELAPSED:" in text
    kind = OTHER_KIND
    tool = 0
    start_tool = None
    now = 0.0
    layer = 0
    await_z = False
    low_x = low_y = math.inf
    high_x = high_y = -math.inf
    cut_below = first_layer > 1
    below_z = 0.0
    below_colours: list[str] = []

    def colour_of(tool: int) -> str:
        return colours[min(tool, len(colours) - 1)]
    cut_seconds = None

    for line in text.split("\n"):
        if await_z:
            await_z = False
            found = _LAYER_Z.match(line)
            if found and layer < first_layer:
                below_z = round(float(found.group(1)), 3)
            elif found and layer <= last_layer:
                layers.append([round(float(found.group(1)), 3), records.mark_layer()])
                times.append(now)
                if cut_below and layer == first_layer:
                    records.add(0, x, y)
            continue
        if line.startswith(";"):
            if line == ";LAYER_CHANGE":
                layer += 1
                if layer == last_layer + 1:
                    cut_seconds = now
                elif layer > last_layer + 1:
                    break
                await_z = True
            elif line.startswith(";TYPE:"):
                name = FEATURES.get(line[6:].strip().casefold(), "other")
                kind = KINDS.index(name) + 1
            elif line.startswith(";TIME_ELAPSED:"):
                now = float(line[14:])
            continue
        if line.startswith("M73 ") and " R" in line and total_seconds and not exact_times:
            found = _REMAINING.search(line)
            if found:
                now = max(now, total_seconds - int(found.group(1)) * 60)
            continue
        if line.startswith("M82"):
            relative_e = False
        elif line.startswith("M83"):
            relative_e = True
        elif line.startswith("G92") and " E" in line:
            e = float(dict(_WORD.findall(line)).get("E", 0))
        elif line[:1] == "T" and line[1:].strip().isdigit():
            tool = int(line[1:].strip())
            if start_tool is None:
                # A replay from above layer 1 takes the tool of its first extrusion instead.
                if not cut_below:
                    start_tool = tool
            elif layer >= 1:
                changes.append({"layer": layer, "seconds": round(now, 1), "colour": colour_of(tool)})
        if line[:1] != "G":
            continue
        code = line.split(" ", 1)[0]
        if code not in MOVES:
            continue
        words = dict(_WORD.findall(line.split(";", 1)[0]))
        extruded = float(words.get("E", 0 if relative_e else e))
        if not relative_e:
            extruded, e = extruded - e, extruded
        if "X" not in words and "Y" not in words:
            continue
        nx, ny = float(words.get("X", x)), float(words.get("Y", y))
        extruding = extruded > 0
        if layer < first_layer or layer > last_layer:
            if extruding and 1 <= layer < first_layer and colour_of(tool) not in below_colours:
                below_colours.append(colour_of(tool))
            x, y = nx, ny
            continue
        if cut_below and extruding and start_tool is None:
            start_tool = tool
        move_kind = kind if extruding else 0
        if tool_colours and extruding and tool > KIND_MASK:
            raise SystemExit(f"FAIL: tool T{tool} is above T{KIND_MASK}, which a kind byte cannot hold")
        recorded = move_kind | tool << 4 if tool_colours and extruding else move_kind
        if code in ("G2", "G3"):
            points = arc_points(x, y, nx, ny, float(words.get("I", 0)), float(words.get("J", 0)), code == "G2")
        else:
            points = [(nx, ny)]
        for px, py in points:
            records.add(recorded, px, py)
            if move_kind == WALL_KIND:
                low_x, low_y = min(low_x, px), min(low_y, py)
                high_x, high_y = max(high_x, px), max(high_y, py)
        x, y = nx, ny

    expected = last_layer - first_layer + 1
    if len(layers) != expected:
        raise SystemExit(f"FAIL: the G-code has {len(layers)} layers from {first_layer}, expected {expected}")
    end = cut_seconds if cut_seconds is not None else total_seconds or now
    for row, seconds in zip(layers, spread_times([*times, end])):
        row.append(round(seconds, 1))
    filament = _FILAMENT.search(text)
    meta = {
        "print_seconds": total_seconds or round(end, 1),
        "settings": {"material": setting(text, "filament_type"), "layer_height": setting(text, "layer_height"),
                     "infill": setting(text, "sparse_infill_density"), "walls": setting(text, "wall_loops"),
                     "supports": setting(text, "enable_support") == "1"},
        "filament_g": round(sum(float(value) for value in filament.group(1).split(",")), 2) if filament else None,
        "scale": SCALE, "records": len(records.kinds), "kinds": KINDS, "layers": layers,
        "total_layers": int(total_match.group(1)) if total_match else last_layer,
        "seconds": round(end, 1), "colour": colour_of(start_tool or 0),
        "colour_changes": changes,
        "walls": [round(low_x, 2), round(low_y, 2), round(high_x, 2), round(high_y, 2)],
    }
    if tool_colours:
        meta["tool_colours"] = colours
    if cut_below:
        colour = meta["colour"]
        meta["first_layer"] = first_layer
        meta["start_seconds"] = layers[0][2]
        meta["below"] = {"z": below_z, "colour": next((item for item in below_colours if item != colour), colour)}
    return meta, records


def zigzag(value: int) -> int:
    return (value << 1) ^ (value >> 31)


def encode(meta: dict, records: Records) -> bytes:
    count = len(records.kinds)
    columns = [bytearray(count) for _ in range(4)]
    px = py = 0
    for index in range(count):
        dx, dy = zigzag(records.xs[index] - px), zigzag(records.ys[index] - py)
        if dx > 0xFFFF or dy > 0xFFFF:
            raise SystemExit("FAIL: a move is too long for the replay format")
        columns[0][index], columns[1][index] = dx & 255, dx >> 8
        columns[2][index], columns[3][index] = dy & 255, dy >> 8
        px, py = records.xs[index], records.ys[index]
    head = json.dumps(meta, separators=(",", ":")).encode("utf-8")
    body = MAGIC + struct.pack("<I", len(head)) + head + records.kinds.tobytes() + b"".join(columns)
    return gzip.compress(body, 9, mtime=0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("gcode", type=Path)
    parser.add_argument("--part", help="part id: reads its replay settings from part.json, writes build/replay/<id>.bin.gz")
    parser.add_argument("--plate", help="plate id, for a part printed on several plates: writes build/replay/<part>-<plate>.bin.gz")
    parser.add_argument("--last-layer", type=int)
    parser.add_argument("--first-layer", type=int)
    parser.add_argument("--tolerance", type=float, help="how far, in 1/100 mm, a merged run may bend")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--tool-colours", action="store_true", help="record each extrusion's tool, for a preview in its colours")
    args = parser.parse_args()
    first_layer, last_layer, tolerance, out = args.first_layer, args.last_layer, args.tolerance, args.out
    if args.part:
        import workshop as ws
        part = next((item for item in ws.load_parts() if item["id"] == args.part), None)
        if part is None:
            parser.error(f"no part named {args.part}")
        plates = ws.plates_or_exit(part)
        if not plates:
            parser.error(f"{args.part} has no replay settings yet: add replay or plates to its part.json")
        plate = next((item for item in plates if item["id"] == args.plate), None)
        if plate is None:
            ids = [item["id"] for item in plates if item["id"]]
            parser.error(f"{args.part} is printed on plates, give --plate: {', '.join(ids)}" if ids
                         else f"{args.part} has no plates, leave out --plate")
        first, last = layer_span(plate)
        first_layer = first if first_layer is None else first_layer
        last_layer = last if last_layer is None else last_layer
        tolerance = plate.get("tolerance", TOLERANCE) if tolerance is None else tolerance
        out = out or ws.replay_path(part, plate)
    elif args.plate:
        parser.error("--plate needs --part")
    if last_layer is None or not out:
        parser.error("give --part, or both --last-layer and --out")
    first_layer = 1 if first_layer is None else first_layer
    tolerance = TOLERANCE if tolerance is None else tolerance
    if not 1 <= first_layer <= last_layer:
        parser.error("--first-layer is between 1 and the last layer")
    meta, records = parse(args.gcode.read_text(encoding="utf-8", errors="replace"), last_layer, first_layer, tolerance,
                          args.tool_colours)
    data = encode(meta, records)
    if len(data) > BUDGET:
        print(f"FAIL: replay is {len(data)} bytes, the budget is {BUDGET}", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(f"{out.name}: {len(meta['layers'])} layers, {meta['records']} records, {len(data)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
