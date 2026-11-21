#!/usr/bin/env python3
"""Prepare the Estonia relief map's height grids and outline from open data (ADR-003).

Run by hand from the repo root, never in the check or CI:

  uv run --no-project --python 3.12 --with numpy==2.5.5 --with rasterio==1.5.2 \
    --with pyshp==3.1.9 --with shapely==2.2.0 --with scipy==1.18.1 \
    python -I parts/estonia-relief/data/prep.py [--download] [--preview PNG]

--download fetches the sources into build/estonia-relief/; without it the cached
files are used. The outputs beside this script are rewritten, and the same
downloads give the same files byte for byte.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import urllib.request
import zipfile
import zlib
from pathlib import Path

import numpy as np
import rasterio
import shapefile
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject, transform as warp_points, transform_geom
import shapely
from shapely.geometry import MultiPolygon, Point, Polygon, mapping, shape
from shapely.affinity import affine_transform
from shapely.geometry import box as box_shape
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "scripts"))
import workshop as ws  # noqa: E402  the standard library only, so it loads under uv too

CACHE = ws.BUILD / "estonia-relief"

SOURCES = {
    "dtm": ("DTM_25m_eesti.tif",
            "https://geoportaal.maaamet.ee/index.php?lang_id=1&plugin_act=otsing&andmetyyp=mp_korgusmudelid"
            "&dl=1&f=DTM_25m_eesti.tif&page_id=614"),
    "counties": ("maakond_shp.zip", "https://geoportaal.maaamet.ee/docs/haldus_asustus/maakond_shp.zip"),
    "lakes": ("tuletiskihid-eelis_tervikseisuveed_shp.zip",
              "https://geoportaal.maaamet.ee/index.php?lang_id=1&plugin_act=otsing&andmetyyp=ETAK&dl=1"
              "&f=tuletiskihid-eelis_tervikseisuveed_shp.zip&page_id=609"),
    "countries": ("ne_10m_admin_0_countries.zip",
                  "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip"),
}

CRS = "EPSG:3301"  # L-EST97, the Estonian grid the terrain model comes in
SCALE = 800_000  # 1 mm on the map is 800 m
CELL_MM = 0.5
CELL_M = CELL_MM * SCALE / 1000
X0, Y0, X1, Y1 = 355_000, 6_365_000, 755_000, 6_645_000  # grid bounds, wide enough for the sea outline
BASE_MM = 5.0  # the sea floor of the print, all of it under the land too
COAST_MM = 0.6  # the step from the sea to the lowest land
EXAG_MM_PER_M = 11.0 / 318.0  # Suur Munamägi (318 m) about 11 mm above the land floor
BROWN_M = 70  # the preview's brown above this; the print's change height is set from the histogram
SMALL = {"factor": 2, "base_mm": 3.0}  # the one-print version: half size, same proportions apart from its base
MIN_ISLAND_KM2 = 1.44  # an island under about 1.5 mm across is dropped
MIN_LAKE_KM2 = 1.0
RUHNU = (23.25, 57.81)
CLOSE_MM, GROW_MM = 30.0, 8.0  # the sea outline: gaps up to 30 mm closed, then 8 mm around everything
MAX_TILE_MM = 245.0
KEY_BOX_MM = (34.0, 18.0)  # room a butterfly key's recess needs, across and along its seam
KEY_SPACING_MM = 50.0
KEYHOLE_BOX_MM = (16.0, 28.0)  # room a keyhole slot needs under land, with its head at the bottom
KEYHOLE_HEAD_MM = 6.0  # the head's centre above the room's lower edge
KEYHOLE_CLEAR_MM = 15.0  # from a seam


def fetch(download: bool) -> dict[str, Path]:
    CACHE.mkdir(parents=True, exist_ok=True)
    paths = {}
    for key, (name, url) in SOURCES.items():
        path = CACHE / name
        if download or not path.exists():
            request = urllib.request.Request(url, headers={"User-Agent": "khe-workshop prep"})
            partial = path.with_name(path.name + ".part")
            with urllib.request.urlopen(request, timeout=600) as response, partial.open("wb") as out:
                while chunk := response.read(1 << 20):
                    out.write(chunk)
            partial.replace(path)
        paths[key] = path
    return paths


def read_zip_shapes(path: Path, stem: str, encoding: str):
    """The records and geometries of one shapefile inside a zip, as (dict, shapely geometry)."""
    with zipfile.ZipFile(path) as archive:
        members = {Path(name).suffix.lower(): name for name in archive.namelist() if Path(name).stem == stem}
        reader = shapefile.Reader(shp=archive.open(members[".shp"]), dbf=archive.open(members[".dbf"]),
                                  shx=archive.open(members[".shx"]), encoding=encoding)
        names = [field[0] for field in reader.fields[1:]]
        return [(dict(zip(names, rec)), shape(shp.__geo_interface__))
                for rec, shp in zip(reader.records(), reader.shapes())]


def parts(geometry) -> list[Polygon]:
    if geometry.is_empty:
        return []
    return list(geometry.geoms) if isinstance(geometry, MultiPolygon) else [geometry]


def build_vectors(paths: dict[str, Path]) -> dict:
    counties = read_zip_shapes(paths["counties"], "maakond", "cp1257")
    estonia = unary_union([geometry.buffer(0) for _, geometry in counties])
    ruhnu = Point(*[value[0] for value in warp_points("EPSG:4326", CRS, [RUHNU[0]], [RUHNU[1]])])
    islands = [p for p in parts(estonia) if p.area >= MIN_ISLAND_KM2 * 1e6 and not p.contains(ruhnu)]
    estonia = unary_union(islands)

    countries = read_zip_shapes(paths["countries"], "ne_10m_admin_0_countries", "utf-8")
    def country(name: str):
        found = [g for rec, g in countries if rec.get("ADMIN") == name]
        return shape(transform_geom("EPSG:4326", CRS, mapping(unary_union(found)))).buffer(0)
    ne_estonia = country("Estonia")
    neighbours = unary_union([country(name) for name in ("Latvia", "Russia", "Finland")])
    neighbours = neighbours.difference(ne_estonia).buffer(1000).difference(estonia)

    lakes = [g.buffer(0) for _, g in read_zip_shapes(paths["lakes"], "eelis_tervikseisuveed", "utf-8")]
    lakes = unary_union([g for g in lakes if g.area >= MIN_LAKE_KM2 * 1e6])
    # the county polygons leave the largest lakes out whole; the border lakes are cut at the state border
    lakes = lakes.intersection(ne_estonia.union(estonia))
    land = estonia.difference(lakes)

    mm = SCALE / 1000
    closed = land.buffer(CLOSE_MM * mm).buffer(-CLOSE_MM * mm)
    sea = closed.buffer(GROW_MM * mm).difference(neighbours)
    outline = unary_union([sea, land, lakes])
    outline = max(parts(outline), key=lambda p: p.area)
    outline = Polygon(outline.exterior).simplify(0.1 * mm)  # no holes: lakes print as water, not openings
    if not outline.buffer(mm).contains(land):
        raise SystemExit("some land lies outside the outline")
    return {"land": land, "outline": outline}


def grid_transform(cell_m: float):
    return from_origin(X0, Y1, cell_m, cell_m)


def heights(dtm: Path, cell_m: float) -> np.ndarray:
    nx, ny = round((X1 - X0) / cell_m), round((Y1 - Y0) / cell_m)
    out = np.full((ny, nx), np.nan, dtype=np.float32)
    with rasterio.open(dtm) as src:
        reproject(rasterio.band(src, 1), out, src_nodata=src.nodata, dst_nodata=np.nan,
                  dst_transform=grid_transform(cell_m), dst_crs=CRS, resampling=Resampling.average)
    return out


def land_mask(land, cell_m: float, shape_rc) -> np.ndarray:
    return rasterize([(mapping(p), 1) for p in parts(land)], out_shape=shape_rc,
                     transform=grid_transform(cell_m), dtype="uint8").astype(bool)


def z_grid(h: np.ndarray, land: np.ndarray, base_mm: float, exag: float) -> np.ndarray:
    metres = np.where(np.isnan(h), 0.0, np.clip(h, 0.0, None))
    z = np.where(land, base_mm + COAST_MM + metres * exag, base_mm)
    return np.round(z * 100).astype(np.int32)  # hundredths of a millimetre


def write_dat(path: Path, block: np.ndarray) -> None:
    # OpenSCAD's surface() puts the first row at y = 0, so the southern row goes first
    lines = [" ".join(str(v) for v in row) for row in block[::-1]]
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def to_map_mm(x: float, y: float, cell_m: float) -> tuple[float, float]:
    """L-EST97 metres to map millimetres on the grid's frame: the first cell centre at (0, 0)."""
    return (round((x - X0 - cell_m / 2) * 1000 / SCALE, 3), round((y - Y0 - cell_m / 2) * 1000 / SCALE, 3))


def in_mm(geometry, cell_m: float):
    """A geometry from L-EST97 metres to map millimetres (see to_map_mm)."""
    k = 1000 / SCALE
    return affine_transform(geometry, [k, 0, 0, k, -(X0 + cell_m / 2) * k, -(Y0 + cell_m / 2) * k])


def in_small(geometry):
    """Map millimetres to the small map's frame, as the .scad draws its outline: half the cell
    centres, less a quarter cell."""
    f = 1 / SMALL["factor"]
    return affine_transform(geometry, [f, 0, 0, f, -CELL_MM / 2 * f, -CELL_MM / 2 * f])


def place_keys(outline_mm, tiles: list[dict]) -> list[list[float]]:
    """Butterfly keys across each seam, every KEY_SPACING_MM where the recess fits inside the outline,
    centred on each run of seam the outline crosses. Each is [x, y, angle], angle 0 across a vertical seam."""
    inner = outline_mm.buffer(-3.0)
    shapely.prepare(inner)
    # the vertical seams east of tiles 0 and 2, the horizontal ones north of tiles 2 and 3
    seams = ([("v", tiles[i]["x1_mm"], tiles[i]["y0_mm"], tiles[i]["y1_mm"]) for i in (0, 2)]
             + [("h", tiles[i]["y1_mm"], tiles[i]["x0_mm"], tiles[i]["x1_mm"]) for i in (2, 3)])
    keys = []
    for kind, at, lo, hi in seams:
        across, along = KEY_BOX_MM
        def fits(pos):
            box = (box_shape(at - across / 2, pos - along / 2, at + across / 2, pos + along / 2) if kind == "v"
                   else box_shape(pos - along / 2, at - across / 2, pos + along / 2, at + across / 2))
            return inner.contains(box)
        # a key stays clear of the recesses across the other seam, which reach across / 2 from it
        clear = along / 2 + across / 2 + 1
        good = [pos for pos in np.arange(lo + clear, hi - clear + 0.5, 1.0) if fits(pos)]
        runs, run = [], []
        for pos in good:
            if run and pos - run[-1] > 1.5:
                runs.append(run); run = []
            run.append(pos)
        if run:
            runs.append(run)
        for run in runs:
            count = max(1, int((run[-1] - run[0]) // KEY_SPACING_MM) + 1)
            middle = (run[0] + run[-1]) / 2
            for i in range(count):
                pos = middle + (i - (count - 1) / 2) * KEY_SPACING_MM
                keys.append([round(at, 3), round(pos, 3), 0] if kind == "v" else [round(pos, 3), round(at, 3), 90])
    return keys


def place_keyholes(land_mm, targets: list[float], seams_x: list[float], seams_y: list[float]) -> list[list[float]]:
    """Two keyholes at one height, as high as land allows, each as near its target x as it can be
    within 40 mm, clear of the seams; each as [x, y] of its head."""
    inner = land_mm.buffer(-3.0)
    shapely.prepare(inner)
    w, h = KEYHOLE_BOX_MM
    def ok_x(x, y):
        return (inner.contains(box_shape(x - w / 2, y, x + w / 2, y + h))
                and all(abs(x - s) > KEYHOLE_CLEAR_MM + w / 2 for s in seams_x))
    for y in np.arange(land_mm.bounds[3] - h, land_mm.bounds[1], -0.5):
        if not all(abs(y - s) > KEYHOLE_CLEAR_MM and abs(y + h - s) > KEYHOLE_CLEAR_MM for s in seams_y):
            continue
        found = []
        for target in targets:
            candidates = sorted(np.arange(target - 40, target + 40.5, 0.5), key=lambda v: abs(v - target))
            x = next((x for x in candidates if ok_x(x, y)), None)
            if x is None:
                break
            found.append(x)
        if len(found) == len(targets):
            return [[round(float(x), 3), round(float(y + KEYHOLE_HEAD_MM), 3)] for x in found]
    raise SystemExit("no room for the keyholes under land")


def scad_list(rows) -> str:
    return "[\n" + ",\n".join("[" + ",".join(str(v) for v in row) + "]" for row in rows) + "\n]"


def write_outline(path: Path, outline_points: list, tiles: list[dict], keys, keyholes, small_keyholes) -> None:
    path.write_text(
        "// Generated by data/prep.py; do not edit. Map millimetres, the first cell centre at [0, 0].\n"
        f"cell_mm = {CELL_MM};\n"
        f"base_mm = {BASE_MM};\n"
        f"small_factor = {SMALL['factor']};\n"
        f"tiles = {scad_list([[t['x0_mm'], t['y0_mm'], t['x1_mm'], t['y1_mm']] for t in tiles])};\n"
        f"keys = {scad_list(keys)};\n"
        f"keyholes = {scad_list(keyholes)};\n"
        f"small_keyholes = {scad_list(small_keyholes)};\n"
        f"outline = {scad_list(outline_points)};\n", encoding="ascii")


def split_tiles(outline_mm: list[tuple]) -> list[dict]:
    """2 x 2 tiles over the outline's box, on cell lines, sharing their seam row and column."""
    xs = [p[0] for p in outline_mm]
    ys = [p[1] for p in outline_mm]
    c0, c1 = int(np.floor(min(xs) / CELL_MM)), int(np.ceil(max(xs) / CELL_MM))
    r0, r1 = int(np.floor(min(ys) / CELL_MM)), int(np.ceil(max(ys) / CELL_MM))
    cm, rm = (c0 + c1) // 2, (r0 + r1) // 2
    tiles = []
    for index, ((ya, yb), (xa, xb)) in enumerate(
            [((rm, r1), (c0, cm)), ((rm, r1), (cm, c1)), ((r0, rm), (c0, cm)), ((r0, rm), (cm, c1))]):
        tile = {"index": index, "cols": [xa, xb], "rows_from_south": [ya, yb],
                "x0_mm": xa * CELL_MM, "x1_mm": xb * CELL_MM, "y0_mm": ya * CELL_MM, "y1_mm": yb * CELL_MM}
        if max(tile["x1_mm"] - tile["x0_mm"], tile["y1_mm"] - tile["y0_mm"]) > MAX_TILE_MM:
            raise SystemExit(f"tile {index} is over {MAX_TILE_MM} mm")
        tiles.append(tile)
    return tiles


def png(path: Path, rgb: np.ndarray) -> None:
    height, width, _ = rgb.shape
    raw = b"".join(b"\0" + rgb[r].astype(np.uint8).tobytes() for r in range(height))
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def preview(path: Path, z: np.ndarray, inside: np.ndarray) -> None:
    colours = np.array([[31, 47, 168], [63, 139, 60], [123, 75, 44]], dtype=float)
    zz = z / 100.0
    band = np.zeros(zz.shape, dtype=int)
    band[zz > BASE_MM + 0.01] = 1
    band[zz >= BASE_MM + COAST_MM + BROWN_M * EXAG_MM_PER_M] = 2
    gy, gx = np.gradient(zz, CELL_MM)
    shade = np.clip(0.75 + 0.6 * (-gx + gy) / np.sqrt(1 + gx ** 2 + gy ** 2), 0.4, 1.2)
    rgb = colours[band] * shade[..., None]
    rgb[~inside] = [233, 230, 223]
    png(path, np.clip(rgb, 0, 255))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--preview", type=Path)
    args = parser.parse_args()
    paths = fetch(args.download)
    vectors = build_vectors(paths)

    h = heights(paths["dtm"], CELL_M)
    ny, nx = h.shape
    land = land_mask(vectors["land"], CELL_M, h.shape)
    z = z_grid(h, land, BASE_MM, EXAG_MM_PER_M)

    outline_mm = [to_map_mm(x, y, CELL_M) for x, y in list(vectors["outline"].exterior.coords)[:-1]]
    tiles = split_tiles(outline_mm)
    for tile in tiles:
        (ya, yb), (xa, xb) = tile["rows_from_south"], tile["cols"]
        # rows from the south: row index in the grid is ny - 1 - r
        block = z[ny - 1 - yb: ny - ya, xa: xb + 1]
        write_dat(HERE / f"tile-{tile['index']}.dat", block)

    small_cell = CELL_M * SMALL["factor"]
    hs = heights(paths["dtm"], small_cell)
    ls = land_mask(vectors["land"], small_cell, hs.shape)
    zs = z_grid(hs, ls, SMALL["base_mm"], EXAG_MM_PER_M / SMALL["factor"])
    write_dat(HERE / "small.dat", zs)
    small_mm = ((zs.shape[1] - 1) * CELL_MM, (zs.shape[0] - 1) * CELL_MM)

    outline_g, land_g = in_mm(vectors["outline"], CELL_M), in_mm(vectors["land"], CELL_M)
    keys = place_keys(outline_g, tiles)
    cx = outline_g.centroid.x
    spread = 0.28 * (outline_g.bounds[2] - outline_g.bounds[0])
    keyholes = place_keyholes(land_g, [cx - spread, cx + spread], [tiles[0]["x1_mm"]], [tiles[0]["y0_mm"]])
    small_x, small_spread = in_small(outline_g).centroid.x, spread / SMALL["factor"]
    small_keyholes = place_keyholes(in_small(land_g), [small_x - small_spread, small_x + small_spread], [], [])
    write_outline(HERE / "outline.scad", outline_mm, tiles, keys, keyholes, small_keyholes)

    metres = np.where(np.isnan(h), 0, h)[land]
    shares = {str(t): round(float((metres >= t).mean()), 4) for t in range(30, 161, 10)}
    record = {
        "scale": f"1:{SCALE}", "crs": CRS, "cell_mm": CELL_MM, "cell_m": CELL_M,
        "grid_bounds_m": [X0, Y0, X1, Y1], "grid_cells": [nx, ny],
        "base_mm": BASE_MM, "coast_mm": COAST_MM, "exag_mm_per_m": round(EXAG_MM_PER_M, 6),
        "small": {**SMALL, "cells": [zs.shape[1], zs.shape[0]], "size_mm": list(small_mm)},
        "z_unit_mm": 0.01, "z_max_mm": round(float(z.max()) / 100, 2),
        "land_height_m": {f"p{q}": round(float(np.percentile(metres, q)), 1) for q in (25, 50, 75, 90, 95, 99, 100)},
        "land_share_at_or_above_m": shares,
        "outline": {"points": len(outline_mm), "area_cm2": round(vectors["outline"].area / (SCALE / 1000) ** 2 / 100, 1),
                    "size_mm": [round(max(p[0] for p in outline_mm) - min(p[0] for p in outline_mm), 1),
                                round(max(p[1] for p in outline_mm) - min(p[1] for p in outline_mm), 1)]},
        "tiles": tiles, "keys": keys, "keyholes": keyholes, "small_keyholes": small_keyholes,
        "sources": {key: {"file": path.name, "url": SOURCES[key][1], "bytes": path.stat().st_size,
                          "sha256": ws.sha256(path)} for key, path in paths.items()},
    }
    (HERE / "prep.json").write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.preview:
        preview(args.preview, z, land_mask(vectors["outline"], CELL_M, h.shape))
    print(json.dumps({k: record[k] for k in ("z_max_mm", "land_height_m", "outline")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
