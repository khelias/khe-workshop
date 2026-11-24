#!/usr/bin/env python3
"""Write the room's static pages: an index and one page per part, in Estonian and English.

Without --preview only published parts are built, each verified first, and the build fails when
there are none. With --base the pages and modules use root-relative URLs under that path, and
data URLs carry a content version, for a site that caches by URL.
"""
from __future__ import annotations

import argparse
import datetime
import functools
import html
import json
import math
import posixpath
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import replay as replay_format  # noqa: E402
import workshop as ws  # noqa: E402

LANGS = ("et", "en")
PREFIX = {"et": "", "en": "en/"}
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December")
SOURCE_URL = "https://github.com/khelias/khe-workshop/blob/main/parts"
# Rewritten so khe-sites' stamper, which versions only root-relative URLs, reaches every module.
SPECIFIER = re.compile(r"""(\b(?:from|import)\s*\(?\s*)(['"])(\.\.?/[^'"\s]+)\2""")
LICENCES = {
    "CC-BY-4.0": ("CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/"),
    "CC-BY-NC-4.0": ("CC BY-NC 4.0", "https://creativecommons.org/licenses/by-nc/4.0/"),
}
TEXT = {
    "et": {
        "room": "Töökoda",
        "lead": "Detailid, mille oleme oma kodu jaoks ise kavandanud ja printinud. Igaüht saab keerata, pooleks lõigata ja vaadata, kuidas see kiht kihi haaval valmis.",
        "other": "English", "back": "Kõik detailid", "views": "Vaade",
        "model": "Mudel", "cut": "Lõige", "print": "Printimine",
        "why": "Detailist", "proof": "Kontroll", "facts": "Prinditöö",
        "files": "Failid", "licence": "Litsents", "source": "Lähtekood (OpenSCAD)",
        "size": "Mõõdud", "layers": "Kihte", "layers_one": "kiht", "layers_many": "kihti", "time": "Printimise aeg", "filament": "Filamenti",
        "material": "Materjal", "layer_height": "Kihi kõrgus", "infill": "Täide", "walls": "Seinu", "supports": "Toed",
        "yes": "On", "no": "Pole",
        "result": "Tulemus",
        "passed_one": "1 kontroll läbitud", "passed": "{n} kontrolli läbitud", "failed": "Kontroll ebaõnnestus",
        "closed": "{name}: terviklik mudel, mahub printeri {bed} mm prindialusele.",
        "closed_many": "{n} terviklikku mudelit, kõik mahuvad printeri {bed} mm prindialusele.",
        "open": "{name}: mahub printeri {bed} mm prindialusele. {reason}",
        "nowebgl": "3D-vaade vajab JavaScripti ja WebGL-i, mida see brauser ei toeta.",
        "photo": "Foto prinditud detailist", "download": "Laadi alla", "printed": "Prinditud {date}.",
        "terms": {"CC-BY-4.0": "Võid seda kasutada, muuta ja jagada, kui nimetad autori.",
                  "CC-BY-NC-4.0": "Võid seda kasutada, muuta ja jagada, kui nimetad autorid, aga mitte ärilisel eesmärgil."},
        "plate": "Plaat", "total": "Kokku", "plates_row": "{n} plaati, {time}", "tests": "Sobivusproovid",
        "stage": {"play": "Esita", "pause": "Paus", "loading": "Laadin prinditööd", "loading_parts": "Laadin osi", "error": "Vaadet ei õnnestunud laadida.",
                  "turned": "Pööratud {deg}°", "cut": "Lõige {mm} mm keskjoonest",
                  "print": "{time}, kiht {layer}/{layers}",
                  "print_plates": "{time} / {total}, plaat {plate}/{plates}, kiht {layer}/{layers}",
                  "plate_mark": "Järgmine plaat", "colour_change": "Värvivahetus",
                  "apart": "Lahti võetud {pct}%",
                  "slider": {"model": "Pööra detaili", "cut": "Liiguta lõiget", "print": "Keri prinditööd", "parts": "Võta osadeks"}},
    },
    "en": {
        "room": "Workshop",
        "lead": "Parts we designed and printed for our own home. Turn each one, cut it open and watch how it was built, layer by layer.",
        "other": "Eesti", "back": "All parts", "views": "View",
        "model": "Model", "cut": "Cut", "print": "Print",
        "why": "About the part", "proof": "Checks", "facts": "The print",
        "files": "Files", "licence": "Licence", "source": "Source (OpenSCAD)",
        "size": "Size", "layers": "Layers", "layers_one": "layer", "layers_many": "layers", "time": "Print time", "filament": "Filament",
        "material": "Material", "layer_height": "Layer height", "infill": "Infill", "walls": "Walls", "supports": "Supports",
        "yes": "Yes", "no": "No",
        "result": "Result",
        "passed_one": "1 check passed", "passed": "{n} checks passed", "failed": "A check failed",
        "closed": "{name}: a closed solid that fits the printer's {bed} mm bed.",
        "closed_many": "{n} files are closed solids that fit the printer's {bed} mm bed.",
        "open": "{name}: fits the printer's {bed} mm bed. {reason}",
        "nowebgl": "The 3D view needs JavaScript and WebGL, which this browser does not offer.",
        "photo": "A photo of the printed part", "download": "Download", "printed": "Printed {date}.",
        "terms": {"CC-BY-4.0": "You may use, change and share it if you credit the author.",
                  "CC-BY-NC-4.0": "You may use, change and share it if you credit the authors, but not commercially."},
        "plate": "Plate", "total": "Total", "plates_row": "{n} plates, {time}", "tests": "Fit tests",
        "stage": {"play": "Play", "pause": "Pause", "loading": "Loading the print", "loading_parts": "Loading the parts", "error": "The view could not be loaded.",
                  "turned": "Turned {deg}°", "cut": "Cut {mm} mm from the centre",
                  "print": "{time}, layer {layer} of {layers}",
                  "print_plates": "{time} of {total}, plate {plate}/{plates}, layer {layer}/{layers}",
                  "plate_mark": "Next plate", "colour_change": "Colour change",
                  "apart": "{pct}% apart",
                  "slider": {"model": "Turn the part", "cut": "Move the cut", "print": "Scrub through the print", "parts": "Take the part apart"}},
    },
}


def stage_text(lang: str, plates: int) -> dict:
    """The stage's strings, with the readout for one plate or for several as `print`."""
    text = dict(TEXT[lang]["stage"])
    plates_text = text.pop("print_plates")
    if plates > 1:
        text["print"] = plates_text
    return text


def totals(metas: list[tuple[dict, dict]]) -> tuple[float, float | None]:
    """The plates' print time and filament together, summed before rounding."""
    grams = [meta.get("filament_g") for _, meta in metas]
    return math.fsum(meta["print_seconds"] for _, meta in metas), math.fsum(grams) if all(grams) else None


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def number(value: float, lang: str, digits: int = 1) -> str:
    text = f"{value:.{digits}f}"
    return text.replace(".", ",") if lang == "et" else text


def duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min"


@functools.cache
def replay_meta(path: Path) -> dict:
    return replay_format.read_meta(path)


@functools.cache
def outline(path: Path) -> str:
    """An SVG path of the real layer with the most outer wall, for the index row."""
    meta, kinds, xs, ys = replay_format.read_replay(path)
    wall = replay_format.WALL_KIND
    ends = [row[1] for row in meta["layers"][1:]] + [meta["records"]]
    first, last = max(zip((row[1] for row in meta["layers"]), ends), key=lambda span: kinds.count(wall, *span))
    parts: list[str] = []
    drawing = False
    for index in range(first, last):
        if kinds[index] == wall:
            if not drawing:
                start = max(index - 1, 0)
                parts.append(f"M{xs[start]:.1f} {-ys[start]:.1f}")
            parts.append(f"L{xs[index]:.1f} {-ys[index]:.1f}")
        drawing = kinds[index] == wall
    low_x, low_y, high_x, high_y = meta["walls"]
    box = f"{low_x:.1f} {-high_y:.1f} {high_x - low_x:.1f} {high_y - low_y:.1f}"
    return (f'<svg class="row__outline" viewBox="{box}" aria-hidden="true" focusable="false">'
            f'<path d="{"".join(parts)}"/></svg>')


def date_text(value: str, lang: str) -> str:
    day = datetime.date.fromisoformat(value)
    return f"{day.day}.{day.month}.{day.year}" if lang == "et" else f"{day.day} {MONTHS[day.month - 1]} {day.year}"


def use_record(part: dict, lang: str) -> str:
    """The published part's print date and use, the proof under its story."""
    proof = part.get("proof") if part.get("published") else None
    if not proof:
        return ""
    printed = TEXT[lang]["printed"].format(date=date_text(proof["printed"], lang))
    return f'<p>{esc(printed)} {esc(proof["use"][lang])}</p>'


@functools.cache
def version(path: Path) -> str:
    return ws.sha256(path)[:10]


def photo_name(part: dict) -> str | None:
    """A photo appears only for a published part."""
    return (part.get("proof") or {}).get("photo") if part.get("published") else None


class Site:
    def __init__(self, out: Path, preview: bool, base: str | None = None) -> None:
        self.out = out
        self.base = base
        self.parts = []
        for part in ws.load_parts():
            if not (preview or part.get("published")):
                continue
            has_replay = "replay" in part or "plates" in part
            if not part.get("published") and not (has_replay and all(ws.replay_path(part, plate).exists() for plate in ws.plates(part))):
                print(f"note: {part['id']} is left out, it has no replay data yet")
                continue
            self.parts.append(part)
        if not preview:
            for part in self.parts:
                problems = ws.published_problems(part)
                if problems:
                    raise SystemExit(f"FAIL {part['id']}: {'; '.join(problems)}")

    def link(self, depth: int, path: str = "") -> str:
        """The URL of a path below the room's root, from a page `depth` folders down."""
        url = (self.base or "../" * depth) + path
        return url or "./"

    def data_link(self, part: dict, depth: int, name: str) -> str:
        url = self.link(depth, f"data/{part['id']}/{name}")
        return f"{url}?v={version(self.out / 'data' / part['id'] / name)}" if self.base else url

    def root_imports(self, file: Path) -> None:
        """Rewrite a copied module's relative specifiers to root-relative ones under the base."""
        here = self.base + file.parent.relative_to(self.out).as_posix() + "/"

        def rooted(match: re.Match) -> str:
            target = posixpath.normpath(posixpath.join(here, match[3]))
            inside = target.startswith(self.base) and (self.out / target[len(self.base):]).is_file()
            if not inside:
                raise SystemExit(f"FAIL: {file.relative_to(self.out)} imports {match[3]}, which the build did not write")
            return f"{match[1]}{match[2]}{target}{match[2]}"

        file.write_text(SPECIFIER.sub(rooted, file.read_text(encoding="utf-8")), encoding="utf-8")

    def results(self, part: dict) -> dict:
        path = part["_dir"] / "published" / "check.json" if part.get("published") else ws.CHECK_RESULTS / f"{part['id']}.json"
        if not path.exists():
            raise SystemExit(f"FAIL {part['id']}: no check results, run scripts/check.py first")
        return json.loads(path.read_text(encoding="utf-8"))

    def replay_file(self, part: dict, plate: dict) -> Path:
        path = ws.published_replay(part, plate) if part.get("published") else ws.replay_path(part, plate)
        if not path.exists():
            raise SystemExit(f"FAIL {part['id']}: no replay data for {path.name}, run scripts/replay.py first")
        return path

    def plate_metas(self, part: dict) -> list[tuple[dict, dict]]:
        """Each plate with its replay's metadata, in print order."""
        return [(plate, replay_meta(self.replay_file(part, plate))) for plate in ws.plates(part)]

    def copy_data(self, part: dict) -> None:
        folder = self.out / "data" / part["id"]
        folder.mkdir(parents=True, exist_ok=True)
        for plate in ws.plates(part):
            shutil.copyfile(self.replay_file(part, plate), folder / ws.published_replay(part, plate).name)
        photo = photo_name(part)
        if photo:
            shutil.copyfile(part["_dir"] / "published" / photo, folder / photo)
        for export in part["exports"]:
            target = folder / export["file"]
            if part.get("published"):
                shutil.copyfile(part["_dir"] / "published" / export["file"], target)
            else:
                ws.render_or_exit(part, target, export["defines"], export["id"])
        for item in ws.rendered_items(part):
            name = ws.item_file(part, item)
            if part.get("published"):
                shutil.copyfile(part["_dir"] / "published" / name, folder / name)
            else:
                ws.render_or_exit(part, folder / name, item["defines"], f"assembly {item['id']}")

    def page(self, lang: str, depth: int, title: str, description: str, paths: dict[str, str], body: str) -> str:
        """`paths` holds the page's path below the room's root in each language."""
        t = TEXT[lang]
        other = "en" if lang == "et" else "et"
        alternates = "\n".join(f'<link rel="alternate" hreflang="{code}" href="{esc(self.link(depth, paths[code]))}">' for code in LANGS)
        switch = "" if self.base else (f'<p class="room__lang"><a href="{esc(self.link(depth, paths[other]))}" '
                                       f'lang="{other}">{t["other"]}</a></p>\n')
        return f"""<!doctype html>
<html lang="{lang}" data-room="workshop">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
{alternates}
<!-- khe:head -->
<link rel="stylesheet" href="{self.link(depth, 'assets/src/room.css')}">
<script type="module" src="{self.link(depth, 'assets/src/main.js')}"></script>
</head>
<body>
<!-- khe:header -->
<main class="room">
{switch}{body}
</main>
<!-- khe:footer -->
<!-- khe:consent -->
</body>
</html>
"""

    def index(self, lang: str) -> str:
        t = TEXT[lang]
        prefix = PREFIX[lang]
        depth = prefix.count("/")
        rows = []
        for part in self.parts:
            metas = self.plate_metas(part)
            href = self.link(depth, f"{prefix}{part['id']}/")
            if len(metas) > 1:
                facts = t["plates_row"].format(n=len(metas), time=duration(totals(metas)[0]))
            else:
                meta = metas[0][1]
                layer_unit = t["layers_one"] if meta["total_layers"] == 1 else t["layers_many"]
                facts = f"{meta['total_layers']} {layer_unit}, {duration(meta['print_seconds'])}"
            shown_plate = ws.stage_plate(part) or metas[0][0]
            rows.append(f"""<li class="row">
<a class="row__link" href="{href}">
{outline(self.replay_file(part, shown_plate))}
<span class="row__text">
<span class="row__title">{esc(part['title'][lang])}</span>
<span class="row__summary">{esc(part['summary'][lang])}</span>
</span>
<span class="fact row__fact">{esc(facts)}</span>
</a>
</li>""")
        shown = self.parts[0]
        shown_href = self.link(depth, f"{prefix}{shown['id']}/")
        body = f"""<section class="band hero">
<header class="hero__text">
<h1>{t['room']}</h1>
<p class="lead">{t['lead']}</p>
</header>
<div class="hero__stage">
<p class="label"><a href="{shown_href}">{esc(shown['title'][lang])}</a></p>
{self.stage(shown, lang, depth, self.plate_metas(shown), initial="print")}
</div>
</section>
<ul class="rows">
{chr(10).join(rows)}
</ul>"""
        return self.page(lang, depth, t["room"], t["lead"], PREFIX, body)

    def photo(self, part: dict, lang: str, depth: int) -> str:
        photo = photo_name(part)
        if not photo:
            return ""
        return f'<img src="{esc(self.data_link(part, depth, photo))}" alt="{TEXT[lang]["photo"]}" loading="lazy">'

    def stage_plate_config(self, part: dict, plate: dict, meta: dict, lang: str, depth: int) -> dict:
        """What the stage draws with the stage plate only: the top printed after its replay, the
        layers printed below it and the inlay."""
        first = meta.get("first_layer", 1)
        last = first + len(meta["layers"]) - 1
        extra = {}
        after = [change for change in meta["colour_changes"] if change["layer"] > last]
        if after:
            # What was printed after the replay's last layer, in its own colour.
            extra["top"] = {"above": meta["layers"][-1][0] + 0.05, "colour": after[0]["colour"],
                            "label": plate["after_label"][lang]}
        printed_below = meta.get("below")
        if printed_below:
            # What was printed under the replay's first layer, shown by the model instead.
            if "before_label" not in plate:
                raise SystemExit(f"FAIL {part['id']}: a replay that starts above layer 1 needs before_label")
            extra["below"] = {"z": printed_below["z"], "label": plate["before_label"][lang]}
        if part.get("stage_inlay"):
            if not printed_below:
                raise SystemExit(f"FAIL {part['id']}: stage_inlay takes its colour from a replay that starts above layer 1")
            inlay = next(item["file"] for item in part["exports"] if item["id"] == part["stage_inlay"])
            extra["inlay"] = {"stl": self.data_link(part, depth, inlay), "colour": printed_below["colour"]}
        return extra

    def stage(self, part: dict, lang: str, depth: int, metas: list[tuple[dict, dict]], initial: str = "model") -> str:
        t = TEXT[lang]
        files = {item["id"]: item["file"] for item in part["exports"]}
        plates = []
        for plate, meta in metas:
            entry = {"replay": self.data_link(part, depth, ws.published_replay(part, plate).name),
                     "colour": plate.get("colour") or meta["colour"], "rotate": plate["rotate_deg"],
                     "first": meta.get("first_layer", 1),
                     "title": (plate.get("title") or part["title"])[lang], "stage": bool(plate.get("stage"))}
            if entry["stage"]:
                entry.update(self.stage_plate_config(part, plate, meta, lang, depth))
            plates.append(entry)
        config = {
            "lang": lang, "stl": self.data_link(part, depth, files[part["stage_export"]]),
            "plates": plates, "bed": ws.BED_MM, "text": stage_text(lang, len(plates)),
        }
        if initial != "model":
            config["initial"] = initial
        views = [(view, t[view]) for view in ("model", "cut", "print")]
        assembly = part.get("assembly")
        if assembly:
            config["assembly"] = {"start": assembly["start"], "items": [
                {"stl": self.data_link(part, depth, ws.item_file(part, item)), "colour": item["colour"], "path": item.get("path")}
                for item in assembly["items"]]}
            views.append(("parts", assembly["label"][lang]))
        tabs = "".join(f'<button type="button" class="stage__tab" data-view="{view}" aria-pressed="{str(view == initial).lower()}">{esc(label)}</button>'
                       for view, label in views)
        data = json.dumps(config, ensure_ascii=False).replace("<", "\\u003c")
        return f"""<section class="stage" data-stage aria-label="{esc(part['title'][lang])}">
<script type="application/json" data-stage-config>{data}</script>
<div class="stage__view">
<canvas class="stage__canvas"></canvas>
<div class="stage__fallback">{self.photo(part, lang, depth)}<p>{t['nowebgl']}</p></div>
<noscript><p class="stage__noscript">{t['nowebgl']}</p></noscript>
<p class="stage__status" data-stage-status role="status" hidden></p>
</div>
<div class="stage__controls">
<div class="stage__tabs" role="group" aria-label="{t['views']}">{tabs}</div>
<div class="stage__timeline">
<input class="stage__slider" data-stage-slider type="range" min="0" max="1000" step="1" value="0">
</div>
<div class="stage__foot">
<output class="stage__readout" data-stage-readout></output>
<button type="button" class="stage__play" data-stage-play hidden>{t['stage']['play']}</button>
</div>
</div>
</section>"""

    def proof(self, part: dict, lang: str) -> str:
        t = TEXT[lang]
        results = self.results(part)
        lines = []
        titles = {item["id"]: item["title"][lang] for item in part["exports"]}
        reason = part.get("allowed_nonmanifold_reason") or {}
        bed = f"{ws.BED_MM:.0f}"
        closed = [export for export in results["exports"] if not export["nonmanifold_edges"]]
        if len(closed) > 1:
            lines.append(f"<li>{esc(t['closed_many'].format(n=len(closed), bed=bed))}</li>")
        elif closed:
            lines.append(f"<li>{esc(t['closed'].format(name=titles[closed[0]['id']], bed=bed))}</li>")
        for export in results["exports"]:
            if export["nonmanifold_edges"]:
                lines.append(f"<li>{esc(t['open'].format(name=titles[export['id']], reason=reason.get(lang, ''), bed=bed))}</li>")
        table = ""
        if results["probes"]:
            probes = part["probes"]
            rows = []
            for variant in results["probes"]:
                checks = variant["checks"]
                value = next((item["value"] for item in checks if item.get("value") is not None), None)
                passed = all(item["passed"] for item in checks)
                outcome = (t["passed_one"] if len(checks) == 1 else t["passed"].format(n=len(checks))) if passed else t["failed"]
                clearance = f"{number(value, lang, 2)} mm" if value is not None else ""
                rows.append(f'<tr><th scope="row">{esc(variant["label"][lang])}</th><td class="fact">{clearance}</td><td>{esc(outcome)}</td></tr>')
            labels = "".join(f"<li>{esc(item['label'][lang])}</li>" for item in results["probes"][0]["checks"])
            table = f"""<div class="table">
<table>
<thead><tr><th scope="col">{esc(probes['variant_heading'][lang])}</th><th scope="col">{esc(probes['value_heading'][lang])}</th><th scope="col">{t['result']}</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</div>
<p class="label">{esc(probes['each'][lang])}</p>
<ul class="checks">{labels}</ul>"""
        return f"""<section class="block">
<h2>{t['proof']}</h2>
{table}
<ul class="checks">{''.join(lines)}</ul>
</section>"""

    def plate_table(self, part: dict, metas: list[tuple[dict, dict]], lang: str) -> str:
        """A row per plate and the total, summed before rounding."""
        t = TEXT[lang]
        rows = []
        for plate, meta in metas:
            colour = plate.get("colour") or meta["colour"]
            grams = meta.get("filament_g")
            rows.append(f'<tr><th scope="row"><span class="swatch" style="--swatch: {esc(colour)}" aria-hidden="true"></span>{esc(plate["title"][lang])}</th>'
                        f'<td class="fact">{meta["total_layers"]}</td><td class="fact">{duration(meta["print_seconds"])}</td>'
                        f'<td class="fact">{f"{number(grams, lang, 0)} g" if grams else ""}</td></tr>')
        seconds, grams = totals(metas)
        total_grams = f"{number(grams, lang, 0)} g" if grams else ""
        rows.append(f'<tr><th scope="row">{t["total"]}</th><td></td><td class="fact">{duration(seconds)}</td><td class="fact">{total_grams}</td></tr>')
        return f"""<div class="table">
<table>
<thead><tr><th scope="col">{t['plate']}</th><th scope="col">{t['layers']}</th><th scope="col">{t['time']}</th><th scope="col">{t['filament']}</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</div>
"""

    def part_page(self, part: dict, lang: str) -> str:
        t = TEXT[lang]
        prefix = PREFIX[lang]
        depth = 1 + prefix.count("/")
        metas = self.plate_metas(part)
        results = self.results(part)
        stage_result = next(item for item in results["exports"] if item["id"] == part["stage_export"])
        size = " x ".join(number(value, lang) for value in stage_result["size_mm"])
        facts = [(t["size"], f"{size} mm")]
        plate_table = ""
        if len(metas) > 1:
            plate_table = self.plate_table(part, metas, lang)
        else:
            meta = metas[0][1]
            facts += [(t["layers"], str(meta["total_layers"])), (t["time"], duration(meta["print_seconds"]))]
            if meta.get("filament_g"):
                facts.append((t["filament"], f"{number(meta['filament_g'], lang, 0)} g"))

        def shared(key: str, show=lambda value: value) -> str:
            """A setting once when every plate shares it, else each distinct value."""
            return ", ".join(dict.fromkeys(filter(None, (show(meta["settings"][key]) for _, meta in metas))))
        facts += [(t["material"], shared("material")),
                  (t["layer_height"], shared("layer_height", lambda height: f"{number(float(height), lang)} mm" if height else None)),
                  (t["infill"], shared("infill")), (t["walls"], shared("walls")),
                  (t["supports"], shared("supports", lambda supports: t["yes"] if supports else t["no"]))]
        fact_rows = "".join(f'<div><dt>{esc(name)}</dt><dd class="fact">{esc(value)}</dd></div>' for name, value in facts if value)
        photo = self.photo(part, lang, depth)
        photo_html = f'<figure class="photo">{photo}</figure>' if photo else ""
        note_html = "".join(f'<p class="note">{esc(plate["note"][lang])}</p>' for plate, _ in metas if plate.get("note"))

        def file_items(exports) -> str:
            return "".join(f'<li><a href="{esc(self.data_link(part, depth, item["file"]))}" download>{esc(item["title"][lang])}</a> <span class="fact">STL</span></li>'
                           for item in exports)
        tests = [item for item in part["exports"] if item.get("test")]
        files = file_items(item for item in part["exports"] if not item.get("test"))
        files += f'<li><a href="{SOURCE_URL}/{part["id"]}/{esc(part["source"])}">{t["source"]}</a></li>'
        files_html = f'<ul class="files">{files}</ul>'
        if tests:
            files_html += f'\n<h3>{t["tests"]}</h3>\n<ul class="files">{file_items(tests)}</ul>'
        name, url = LICENCES[part["licence"]]
        credit = part.get("credit")
        credit_html = ""
        if credit:
            links = ", ".join(f'<a href="{esc(link["url"])}">{esc(link["label"])}</a>' for link in credit["links"])
            credit_html = f"<p>{esc(credit[lang])} {links}</p>"
        body = f"""<section class="band">
<header class="room__head">
<p class="label"><a href="{self.link(depth, prefix)}">{t['back']}</a></p>
<h1>{esc(part['title'][lang])}</h1>
<p class="lead">{esc(part['summary'][lang])}</p>
<p class="room__action"><a class="button" href="#files">{t['download']}</a></p>
</header>
{self.stage(part, lang, depth, metas)}
</section>
{note_html}
<div class="blocks">
<section class="block">
<h2>{t['why']}</h2>
<p>{esc(part['story'][lang])}</p>
{use_record(part, lang)}
{photo_html}
</section>
{self.proof(part, lang)}
<section class="block">
<h2>{t['facts']}</h2>
{plate_table}<dl class="facts">{fact_rows}</dl>
</section>
<section class="block" id="files">
<h2>{t['files']}</h2>
{files_html}
<p>{t['licence']}: <a href="{url}">{name}</a>. {t['terms'][part['licence']]}</p>
{credit_html}
</section>
</div>"""
        paths = {code: f"{PREFIX[code]}{part['id']}/" for code in LANGS}
        return self.page(lang, depth, f"{part['title'][lang]} | {t['room']}", part["summary"][lang], paths, body)

    def build(self) -> None:
        assets = self.out / "assets"
        shutil.rmtree(assets, ignore_errors=True)
        shutil.copytree(ws.ROOT / "web" / "src", assets / "src")
        shutil.copytree(ws.ROOT / "web" / "vendor", assets / "vendor")
        if self.base:
            for module in sorted(assets.rglob("*.js")):
                self.root_imports(module)
        for part in self.parts:
            self.copy_data(part)
        for lang in LANGS:
            base = self.out if lang == "et" else self.out / "en"
            base.mkdir(parents=True, exist_ok=True)
            (base / "index.html").write_text(self.index(lang), encoding="utf-8")
            for part in self.parts:
                folder = base / part["id"]
                folder.mkdir(exist_ok=True)
                (folder / "index.html").write_text(self.part_page(part, lang), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--preview", action="store_true", help="include parts that are not published")
    parser.add_argument("--base", help="the root-relative path the room is served at, such as /workshop/")
    args = parser.parse_args()
    if args.base is not None and not re.fullmatch(r"/(?:[\w-]+/)*", args.base):
        parser.error("--base is a root-relative path that starts and ends with /")
    if args.preview and not ws.require_openscad():
        return 2
    site = Site(args.out, args.preview, args.base)
    if not site.parts:
        print("FAIL: no part is published, so there is nothing to build", file=sys.stderr)
        return 1
    site.build()
    print(f"built {len(site.parts)} part(s) into {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
