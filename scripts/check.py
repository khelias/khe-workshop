#!/usr/bin/env python3
"""Check every part: clean renders, closed meshes, the K2's bed, nothing started in the air, fit probes,
proof and public terms.

Exit 0 on a pass, 1 on a failure naming the part, 2 when OpenSCAD is missing.
"""
from __future__ import annotations

import gzip
import json
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import workshop as ws  # noqa: E402

SKIPPED_DIRS = {".git", "node_modules", "build", "__pycache__"}
PRIVATE_SUFFIXES = {".3mf", ".gcode", ".zip"}


FLAT_UM = 5  # heights this close, in micrometres, count as one flat patch
ON_BED_UM = 50  # vertices this close above the lowest one rest on the bed


def air_starts(path: Path) -> list[tuple[float, float, float]]:
    """Points where a print would start in the air: above the bed, on a face that looks down, a
    vertex, or a flat patch of vertices at one height (within FLAT_UM), with no neighbour lower than itself.
    Coordinates in mm."""
    neighbours: dict[tuple, set] = {}
    down: set[tuple] = set()
    for corners in ws.triangles(path):
        u, v = ws.sub(corners[1], corners[0]), ws.sub(corners[2], corners[0])
        normal = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        # a face within 60 degrees of flat and facing down prints on nothing below it
        if normal[2] < -0.5 * sum(n * n for n in normal) ** 0.5:
            down.update(corners)
        for corner in corners:
            neighbours.setdefault(corner, set()).update(corners)
    bed = min((corner[2] for corner in neighbours), default=0)
    starts = []
    seen: set[tuple] = set()
    for first in neighbours:
        z = first[2]
        if first in seen or z <= bed + ON_BED_UM:
            continue
        patch, todo = {first}, [first]
        while todo:
            for n in neighbours[todo.pop()]:
                if n not in patch and abs(n[2] - z) <= FLAT_UM:
                    patch.add(n)
                    todo.append(n)
        seen |= patch
        if not down.isdisjoint(patch) and not any(n[2] < z - FLAT_UM for i in patch for n in neighbours[i]):
            starts.append(tuple(value / 1000 for value in min(patch)))
    return starts


def render_path(tmp: Path, part: dict, file: str) -> Path:
    return tmp / f"{part['id']}-{file}"


def render_failures(what: str, done: ws.Render, out: Path) -> list[str]:
    if done.problems:
        return [f"{what}: {line}" for line in done.problems]
    if done.empty or not out.exists():
        return [f"{what}: the render is empty"]
    return []


def check_exports(part: dict, tmp: Path, pool: ThreadPoolExecutor, failures: list[str]) -> list[dict]:
    source = part["_dir"] / part["source"]
    allowed = part.get("allowed_nonmanifold_edges", 0)
    if allowed and not part.get("allowed_nonmanifold_reason"):
        failures.append("allowed_nonmanifold_edges needs an allowed_nonmanifold_reason")
    renders = [(export, render_path(tmp, part, export["file"])) for export in part["exports"]]
    jobs = [pool.submit(ws.render, source, out, export["defines"]) for export, out in renders]
    results = []
    for (export, out), job in zip(renders, jobs):
        failed = render_failures(export["id"], job.result(), out)
        if failed:
            failures.extend(failed)
            continue
        mesh = ws.read_mesh(out)
        if mesh.nonmanifold_edges > allowed:
            failures.append(f"{export['id']}: {mesh.nonmanifold_edges} open or non-manifold edges, {allowed} allowed")
        if max(mesh.size) > ws.BED_MM:
            failures.append(f"{export['id']}: {max(mesh.size)} mm does not fit the {ws.BED_MM:.0f} mm bed")
        # A colour region prints inside its object, so it is checked there, on the object's bed.
        starts = [] if "object" in export else air_starts(out)
        if starts:
            low = min(starts, key=lambda point: point[2])
            failures.append(f"{export['id']}: {len(starts)} place(s) start printing in the air, the lowest at "
                            f"x {low[0]:.1f}, y {low[1]:.1f}, z {low[2]:.1f} mm")
        if not export.get("check_only"):
            results.append({"id": export["id"], "file": export["file"], "triangles": mesh.triangles,
                            "size_mm": list(mesh.size), "volume_cm3": mesh.volume_cm3,
                            "nonmanifold_edges": mesh.nonmanifold_edges, "sha256": ws.sha256(out)})
    return results


def check_assembly(part: dict, tmp: Path, pool: ThreadPoolExecutor, failures: list[str]) -> list[dict]:
    """Each item rendered from its own defines is clean and closed. It is shown, not printed, so the
    bed and air-start checks do not apply."""
    problems = ws.assembly_problems(part)
    failures.extend(problems)
    if problems:
        return []
    source = part["_dir"] / part["source"]
    renders = [(item, render_path(tmp, part, ws.item_file(part, item))) for item in ws.rendered_items(part)]
    jobs = [pool.submit(ws.render, source, out, item["defines"]) for item, out in renders]
    results = []
    for (item, out), job in zip(renders, jobs):
        failed = render_failures(f"assembly {item['id']}", job.result(), out)
        if failed:
            failures.extend(failed)
            continue
        mesh = ws.read_mesh(out)
        if mesh.nonmanifold_edges:
            failures.append(f"assembly {item['id']}: {mesh.nonmanifold_edges} open or non-manifold edges")
        results.append({"id": item["id"], "file": ws.item_file(part, item), "triangles": mesh.triangles,
                        "size_mm": list(mesh.size), "sha256": ws.sha256(out)})
    return results


def probe_outcome(probe: dict, done: ws.Render, out: Path) -> tuple[bool, float | None]:
    if done.problems:
        return False, None
    if probe["expect"] == "value":
        echo = re.search(rf"ECHO: {re.escape(probe['log_key'])} = ([-+\d.e]+)", done.log)
        value = float(echo.group(1)) if echo else None
        return value is not None and value >= probe["min"], value
    if probe["expect"] == "clear" and "max_mm3" in probe and not done.empty:
        # Regions cut from one solid touch, and their faces in common leave sheets that enclose nothing.
        return out.exists() and ws.read_mesh(out).volume_mm3 <= probe["max_mm3"], None
    return done.empty == {"clear": True, "contact": False}[probe["expect"]], None


def check_probes(part: dict, tmp: Path, pool: ThreadPoolExecutor, failures: list[str]) -> list[dict]:
    probes = part.get("probes")
    if not probes:
        return []
    source = part["_dir"] / part["source"]
    jobs = [(variant, [(probe, out, pool.submit(ws.render, source, out, {**variant["defines"], **probe["defines"]}))
                       for probe in probes["checks"]
                       for out in [tmp / f"{part['id']}-{variant['id']}-{probe['id']}.stl"]])
            for variant in probes["variants"]]
    results = []
    for variant, variant_jobs in jobs:
        checks = []
        for probe, out, job in variant_jobs:
            passed, value = probe_outcome(probe, job.result(), out)
            if not passed:
                failures.append(f"{variant['id']}: probe {probe['id']} failed" + (f" ({value})" if value is not None else ""))
            checks.append({"id": probe["id"], "label": probe["label"], "passed": passed, "value": value})
        results.append({"id": variant["id"], "label": variant["label"], "checks": checks})
    return results


def close(published: object, fresh: object) -> bool:
    """Equal apart from sha256 and triangle counts, which follow the triangulation, with
    numbers allowed to differ by 0.001."""
    if isinstance(published, dict) and isinstance(fresh, dict):
        skipped = {"sha256", "triangles"}
        keys = published.keys() - skipped
        return keys == fresh.keys() - skipped and all(close(published[key], fresh[key]) for key in keys)
    if isinstance(published, list) and isinstance(fresh, list):
        return len(published) == len(fresh) and all(map(close, published, fresh))
    if type(published) in (int, float) and type(fresh) in (int, float):
        return abs(published - fresh) <= 0.001
    return published == fresh


def check_published(part: dict, result: dict, tmp: Path, failures: list[str]) -> None:
    """The published STL files match check.json (ws.published_problems). On the platform
    published/ was built on, check.json equals this check's results, hashes included, so the
    files equal a fresh render byte for byte; on another, the STL surfaces and the results
    compare at 0.001 mm."""
    folder = part["_dir"] / "published"
    failures.extend(ws.published_problems(part))
    build = ws.read_published(part, "build.json")
    if build is None:
        return
    version = ws.openscad_version()
    if build.get("openscad") != version:
        failures.append(f"built with OpenSCAD {build.get('openscad')}, this machine has {version}")
    same_platform = build.get("platform") == ws.platform_tag()
    if not same_platform:
        for name in [entry["file"] for entry in result["exports"] + result.get("assembly", [])]:
            stl = folder / name
            if stl.exists() and not ws.same_surface(stl, render_path(tmp, part, name)):
                failures.append(f"published/{name} differs from a fresh render")
    published = ws.read_published(part, "check.json")
    if published is not None:
        fresh = json.loads(json.dumps(result))
        if not (published == fresh if same_platform else close(published, fresh)):
            failures.append("published/check.json differs from this check's results; run scripts/build.py")
    size = sum(path.stat().st_size for path in folder.rglob("*") if path.is_file())
    if size > ws.PUBLISHED_BUDGET:
        failures.append(f"published/ is {size} bytes, the budget is {ws.PUBLISHED_BUDGET}")


def repo_files() -> list[Path]:
    listed = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=ws.ROOT, capture_output=True)
    if listed.returncode == 0:
        return [ws.ROOT / name for name in listed.stdout.decode("utf-8").split("\0") if name]
    return [path for path in ws.ROOT.rglob("*")
            if path.is_file() and not SKIPPED_DIRS.intersection(path.relative_to(ws.ROOT).parts)]


def terms_path() -> Path:
    override = os.environ.get("KHE_PUBLIC_TERMS")
    return Path(override) if override else ws.ROOT.parent / "khe-meta" / "house" / "parts" / "public-terms.txt"


def readable(file: Path) -> bytes:
    data = file.read_bytes()
    if file.suffix == ".gz":
        try:
            return gzip.decompress(data)
        except (OSError, EOFError):
            return data
    return data


def scan_repo(known: set[str]) -> dict[str, list[str]]:
    """Problems with what the repo holds, by owning part. A private term itself is never printed."""
    path = terms_path()
    terms = []
    if path.exists():
        terms = [line.strip().casefold() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        print("note: the private terms file is not beside this checkout, so the terms search did not run")
    found: dict[str, list[str]] = {}
    for file in repo_files():
        if not file.is_file():
            continue
        relative = file.relative_to(ws.ROOT)
        folder = relative.parts[1] if relative.parts[0] == "parts" and len(relative.parts) > 2 else "repo"
        owner = folder if folder in known else "repo"
        name = str(relative).casefold()
        if any(term in name for term in terms):
            found.setdefault(owner, []).append("a file name holds a private term")
            continue
        if file.suffix.casefold() in PRIVATE_SUFFIXES:
            found.setdefault(owner, []).append(f"{relative} is a slicer file or archive, which stays private")
        text = readable(file).decode("utf-8", "ignore").casefold()
        if any(term in text for term in terms):
            found.setdefault(owner, []).append(f"{relative} holds a private term")
    return found


def main() -> int:
    if not ws.require_openscad():
        return 2
    version = ws.openscad_version()
    ws.CHECK_RESULTS.mkdir(parents=True, exist_ok=True)
    parts = ws.load_parts()
    problems = scan_repo({part["_dir"].name for part in parts})
    failed = False
    for problem in problems.get("repo", []):
        print(f"FAIL repo: {problem}")
        failed = True
    for part in parts:
        failures: list[str] = list(problems.get(part["_dir"].name, []))
        if part["id"] != part["_dir"].name:
            failures.append(f"part.json id {part['id']} does not match its folder")
        plate_problems = ws.plate_problems(part)
        failures.extend(plate_problems + ws.export_problems(part) + ws.draft_problems(part) + ws.batch_problems(part))
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(os.cpu_count() or 4) as pool:
            tmp = Path(folder)
            result = {"id": part["id"], "openscad": version, "exports": check_exports(part, tmp, pool, failures),
                      "probes": check_probes(part, tmp, pool, failures)}
            if "assembly" in part:
                result["assembly"] = check_assembly(part, tmp, pool, failures)
            if part.get("batch") and not failures:
                for plate in part["batch"]:
                    failures.extend(ws.layout_problems(ws.plate_layout(part, plate, lambda name: render_path(tmp, part, name))))
            results_file = ws.CHECK_RESULTS / f"{part['id']}.json"
            results_file.unlink(missing_ok=True)
            if not failures:
                results_file.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            if part.get("published") and not plate_problems:
                check_published(part, result, tmp, failures)
        for failure in failures:
            print(f"FAIL {part['id']}: {failure}")
        failed = failed or bool(failures)
        if not failures:
            print(f"ok   {part['id']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
