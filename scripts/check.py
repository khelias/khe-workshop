#!/usr/bin/env python3
"""Check every part: clean renders, closed meshes, the K2's bed, fit probes, proof and public terms.

Exit 0 on a pass, 1 on a failure naming the part, 2 when OpenSCAD is missing.
"""
from __future__ import annotations

import datetime
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
import replay as replay_format  # noqa: E402
import workshop as ws  # noqa: E402

SKIPPED_DIRS = {".git", "node_modules", "build", "__pycache__"}
PRIVATE_SUFFIXES = {".3mf", ".gcode", ".zip"}


def check_exports(part: dict, tmp: Path, pool: ThreadPoolExecutor, failures: list[str]) -> list[dict]:
    source = part["_dir"] / part["source"]
    allowed = part.get("allowed_nonmanifold_edges", 0)
    if allowed and not part.get("allowed_nonmanifold_reason"):
        failures.append("allowed_nonmanifold_edges needs an allowed_nonmanifold_reason")
    renders = [(export, tmp / f"{part['id']}-{export['file']}") for export in part["exports"]]
    jobs = [pool.submit(ws.render, source, out, export["defines"]) for export, out in renders]
    results = []
    for (export, out), job in zip(renders, jobs):
        done = job.result()
        if done.problems:
            failures.extend(f"{export['id']}: {line}" for line in done.problems)
            continue
        if done.empty or not out.exists():
            failures.append(f"{export['id']}: the render is empty")
            continue
        mesh = ws.read_mesh(out)
        if mesh.nonmanifold_edges > allowed:
            failures.append(f"{export['id']}: {mesh.nonmanifold_edges} open or non-manifold edges, {allowed} allowed")
        if max(mesh.size) > ws.BED_MM:
            failures.append(f"{export['id']}: {max(mesh.size)} mm does not fit the {ws.BED_MM:.0f} mm bed")
        results.append({"id": export["id"], "file": export["file"], "triangles": mesh.triangles,
                        "size_mm": list(mesh.size), "volume_cm3": mesh.volume_cm3,
                        "nonmanifold_edges": mesh.nonmanifold_edges, "sha256": ws.sha256(out)})
    return results


def probe_outcome(probe: dict, done: ws.Render) -> tuple[bool, float | None]:
    if done.problems:
        return False, None
    if probe["expect"] == "value":
        echo = re.search(rf"ECHO: {re.escape(probe['log_key'])} = ([-+\d.e]+)", done.log)
        value = float(echo.group(1)) if echo else None
        return value is not None and value >= probe["min"], value
    return done.empty == {"clear": True, "contact": False}[probe["expect"]], None


def check_probes(part: dict, tmp: Path, pool: ThreadPoolExecutor, failures: list[str]) -> list[dict]:
    probes = part.get("probes")
    if not probes:
        return []
    source = part["_dir"] / part["source"]
    jobs = [(variant, [(probe, pool.submit(ws.render, source, tmp / f"{part['id']}-{variant['id']}-{probe['id']}.stl",
                                           {**variant["defines"], **probe["defines"]}))
                       for probe in probes["checks"]])
            for variant in probes["variants"]]
    results = []
    for variant, variant_jobs in jobs:
        checks = []
        for probe, job in variant_jobs:
            passed, value = probe_outcome(probe, job.result())
            if not passed:
                failures.append(f"{variant['id']}: probe {probe['id']} failed" + (f" ({value})" if value is not None else ""))
            checks.append({"id": probe["id"], "label": probe["label"], "passed": passed, "value": value})
        results.append({"id": variant["id"], "label": variant["label"], "checks": checks})
    return results


def check_published(part: dict, result: dict, failures: list[str]) -> None:
    folder = part["_dir"] / "published"
    build_file = folder / "build.json"
    if not build_file.exists():
        failures.append("published part has no published/build.json; run scripts/build.py")
        return
    build = json.loads(build_file.read_text(encoding="utf-8"))
    version = ws.openscad_version()
    if build.get("openscad") != version:
        failures.append(f"built with OpenSCAD {build.get('openscad')}, this machine has {version}")
    if build.get("source_sha256") != ws.sha256(part["_dir"] / part["source"]):
        failures.append("the source changed since published/ was built")
    fresh = {item["file"]: item["sha256"] for item in result["exports"]}
    for export in part["exports"]:
        stl = folder / export["file"]
        if not stl.exists():
            failures.append(f"published/{export['file']} is missing")
        elif ws.sha256(stl) != fresh.get(export["file"]):
            failures.append(f"published/{export['file']} differs from a fresh render")
    proof = part.get("proof") or {}
    printed = str(proof.get("printed"))
    try:
        valid_date = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", printed)) and bool(datetime.date.fromisoformat(printed))
    except ValueError:
        valid_date = False
    if not valid_date:
        failures.append("proof.printed is not a YYYY-MM-DD date")
    use = proof.get("use") or {}
    if not (isinstance(use, dict) and use.get("et") and use.get("en")):
        failures.append("proof.use needs a sentence in et and en")
    if proof.get("photo") and not (folder / proof["photo"]).exists():
        failures.append(f"proof photo published/{proof['photo']} is missing")
    replay_file = folder / "replay.bin.gz"
    if not replay_file.exists():
        failures.append("published/replay.bin.gz is missing")
    else:
        try:
            layers = len(replay_format.read_meta(replay_file)["layers"])
        except (OSError, EOFError, ValueError, KeyError) as broken:
            failures.append(f"published/replay.bin.gz cannot be read: {broken}")
        else:
            if layers != part["replay"]["last_layer"]:
                failures.append(f"the replay has {layers} layers, it must stop at {part['replay']['last_layer']}")
    check_file = folder / "check.json"
    if not check_file.exists() or json.loads(check_file.read_text(encoding="utf-8")) != json.loads(json.dumps(result)):
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
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(os.cpu_count() or 4) as pool:
            tmp = Path(folder)
            result = {"id": part["id"], "openscad": version, "exports": check_exports(part, tmp, pool, failures),
                      "probes": check_probes(part, tmp, pool, failures)}
        results_file = ws.CHECK_RESULTS / f"{part['id']}.json"
        results_file.unlink(missing_ok=True)
        if not failures:
            results_file.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        if part.get("published"):
            check_published(part, result, failures)
        for failure in failures:
            print(f"FAIL {part['id']}: {failure}")
        failed = failed or bool(failures)
        if not failures:
            print(f"ok   {part['id']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
