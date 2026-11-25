# khe-workshop

Workspace-wide rules (push, review, docs, estate ADRs) are in [khe-workspace
`AGENTS.md`](https://github.com/khelias/khe-workspace/blob/main/AGENTS.md).

The household's 3D-printable parts as public OpenSCAD source, their checks and
the Töökoda room. Why the repo is public and how khe-sites builds the room:
[estate ADR-043](https://github.com/khelias/khe-architecture/blob/main/decisions/043-household-parts-are-public-source-built-into-khe-sites.md).
This repo's own decisions: [docs/adr/](docs/adr/).

## Commands

- `python3 scripts/check.py` - renders every export, checks the mesh, the bed, that
  nothing starts printing in the air, and the probes, verifies published parts and
  searches the repo for private terms.
  Exit 0 on a pass, 1 on a failure naming the part, 2 when OpenSCAD is missing.
  On the platform `build.json` names, the STL files and `check.json` compare byte for
  byte; on another, under the same OpenSCAD version, the STL surfaces compare within
  0.001 mm (a few small patches may be triangulated differently) and `check.json`
  without its hashes and triangle counts, numbers within 0.001.
- `python3 scripts/build.py` - writes `published/` for parts marked published.
- `python3 scripts/plate.py <id> <plate> [--json]` - where each copy of a `batch` plate
  stands on the bed, from the published files; `--json` is the layout khe-meta's
  `k2_slice.py --parts --layout` slices.
- `python3 scripts/replay.py <gcode> --part <id> [--plate <plate>]` - turns printed
  G-code into `build/replay/<id>.bin.gz`, or `<id>-<plate>.bin.gz` for one plate of a
  part with `plates` (required there, refused without), within 1.5 MB, from the
  part's or the plate's replay settings. G-code stays out of git.
- `python3 scripts/site_build.py <out> [--preview] [--base /workshop/]` - writes the
  room's pages. `--preview` includes unpublished parts that have a replay and
  names the ones it leaves out; without it the build verifies
  each published part's files and proof and fails when none is published. `--base`
  is how khe-sites builds the room: root-relative URLs in the pages and the modules'
  imports, so its stamper versions them, `?v=` on the data files, and no language
  link of its own, since the site header switches language. Marker comments
  (`khe:head`, `khe:header`, `khe:footer`, `khe:consent`) are where khe-sites adds
  the family shell.
- `python3 scripts/preview.py <dir>/part.json --out <file>.html [--lang en]` - one
  self-contained page of the room's stage for a part from outside the repo: a
  `part.json` of ready STL `items`, each with an `id` and a `colour`, an optional
  `gcode` and `facts`. The modules, three.js and the data are inlined, and the replay
  records each tool's colour (`replay.py --tool-colours`). Its stage zooms with a plain wheel,
  comes close and pans (`closeUp` in the stage config); the room's wheel scrolls the page and
  shows the stage's hint to zoom with Ctrl or Cmd. It is a private preview
  before a print (khe-meta's `k2_slice.py` writes one with every slice): it never
  enters the room or a public build, and an external part never becomes a part of
  the repo, so ADR-001 does not apply to it.
- `node --test web/test/*.test.mjs` - the decoder, the slider, the loaders, the parts
  view's paths, the camera fit, the pinch zoom, a `--base` build of the published parts and a
  preview of an external part.
- `npm run -s lint` - the family design check, against an empty baseline.
- `parts/<id>/data/prep.py` - prepares a part's data from open sources, by hand, with
  the pinned `uv run` command in its docstring; never part of the check or CI
  ([ADR-003](docs/adr/003-parts-may-carry-data-prepared-from-open-sources.md)).

The scripts in `scripts/` use the Python standard library and OpenSCAD only; a part's
`data/prep.py` may use pinned third-party packages (ADR-003).

## Layout

- `parts/<id>/part.json` - titles, story, licence, credit, exports, probes, proof
- `parts/<id>/<id>.scad` - the public source; it may `include` another part's source,
  whose mode dispatch then sits behind `if (!library)` with the including part setting
  `library` (ADR-001 point 2). The source hash in `build.json` covers every included or used
  file, fonts too, and the page links each OpenSCAD file.
- `parts/<id>/data/` - a part's prepared data and the script that makes it, committed
  (ADR-003); downloads go to `build/`
- `parts/<id>/published/` - generated, only for a published part
- `scripts/` - the check and the builders; `workshop.py` holds what they share
- `fonts/` - fonts a part loads by path (`use <...ttf>`), so every platform renders the same text:
  Familjen Grotesk SemiBold under its `OFL.txt`, from
  `github.com/Familjen-Sthlm/Familjen-Grotesk` at `de7dfe09`, SHA-256 `f24fba62882e8f0d19b53b5fd554ac1b01b14ede25a2a8a95de64fe56a156d8e`
- `web/src/` - the room: plain ES modules and CSS, served as they are
- `web/vendor/three/` - three.js as published on npm; only `OrbitControls.js` has its
  import path rewritten, because the page uses no import map
- `build/` - generated and ignored: check results, replays, previews

## Family data stays out

Everything here is public for good. The family's stamp text, slicer projects,
G-code and printed files stay in the private working layer. The check searches
every file for the private terms when that list is beside the checkout, and it
says so when the list is missing. Before any push, search the history too:

```bash
git log -p --all | grep -i -c -f ../khe-meta/house/parts/public-terms.txt
```

It must print 0. A failure message never repeats a term.

## Adding or publishing a part

A probe is a render whose result is declared in `part.json`: `clear` (nothing
collides), `contact` (something does) or `value` (an `echo` of `log_key` is at
least `min`). A `clear` probe with `max_mm3` also passes when the render encloses at
most that volume: regions cut from one solid touch, and their faces in common leave
sheets that enclose nothing. A part with non-manifold edges declares how many and why.

A part printed in several colours at once exports each colour region apart. Such an
export names `"object": "<export id>"`, the export of the whole half it prints in: the
check skips its air-start check and runs that on the object, with the object's own
bed. An export with `"check_only": true` is rendered and checked but neither
published nor offered as a download, as the objects are. `clear` probes prove the
regions do not overlap and fill the object exactly.

A replay covers `replay.first_layer` (default 1) to `last_layer`, so layers that
held family text are left out at either end; `before_label` and `after_label` name
what the room shows in their place. `stage_inlay` names an export the stage draws
inside the stage mesh in the colour printed below the replay. `replay.tolerance`
(1/100 mm, default 2) merges more for a replay over its budget, and an export's
`defines` may lower `$fn` or a mesh resolution for a part over its 10 MB budget
([ADR-001](docs/adr/001-published-parts-carry-their-proof.md)).

A part printed on several plates lists `plates` instead of `replay`, in print order:
each an `id`, a `title` in et and en, the replay settings above and an optional
display `colour` (`#rrggbb`, which wins over the G-code's, since the slicer's
filament colours are often unset). At most one plate has `stage: true`, the one that
prints `stage_export` alone; only it carries `before_label`, `after_label` and the
part's `stage_inlay`, and the stage draws the ghost and the model's top and base
with it. The Print view plays the plates one after another, each printed in its own
place in one row, and the facts get a row per plate and a total. An export with
`"test": true` is listed under the fit tests.

A part made of several pieces may declare an `assembly`: a tab `label` in et and en,
the slider's `start` (0 to 1) and `items`, each an export by id or its own `defines`
(rendered to `assembly-<item>.stl`, checked for a clean closed mesh but not as a
print), a display `colour` and an optional `path` of `[t, dx, dy, dz]` rows, t
rising from 0 to 1, linear between rows. The room then adds a fourth view, Parts,
where one slider moves every item along its path (ADR-001). A part printed in several
colours at once may name `stage_items`, the assembly items the Model and Cut views draw
in their colours in place of the one-colour `stage_export`, which still frames the
stage and fills the cut. In the Model view the camera may go below the part, and the
bed hides while it does.

A part may also list `batch` plates for the room's fifth view, Plate: each an `id`, a
`title` in et and en, the assembly `items` one copy is made of, a `pitch` in mm and,
once sliced, `sliced: {seconds, changes}`, copied by hand from the sliced file
(ADR-001 point 3). `plate_layout` in `workshop.py` is the one layout, a centred grid
at the pitch with as many copies as fit on the bed with their brims, which the check
keeps inside the bed and apart, and which the room and `plate.py` both use.

A part not printed yet may be published as a draft
([ADR-002](docs/adr/002-the-print-and-its-use-are-the-proof.md) point 3):
`"draft": true` beside `published: true`, no `proof` or replay, and a `stage_colour`
for its model. Its page has no Print view and carries the draft label; it leaves
draft when the proof and replay are added and `draft` and `stage_colour` removed.

To publish a part: run the check, set `published: true` and fill `proof`
(`printed` as `YYYY-MM-DD`, `use` in et and en, an optional `photo`;
[ADR-002](docs/adr/002-the-print-and-its-use-are-the-proof.md)), write the
replay, run `scripts/build.py`, then run the check again.

## CI and automated writers

`.github/workflows/ci.yml` runs the design check, the check and the tests on a
GitHub-hosted runner, with OpenSCAD from its checksummed Linux AppImage, extracted
once. A new OpenSCAD version changes `OPENSCAD_VERSION` and `OPENSCAD_SHA256` there
in the same commit as a rebuilt `published/`, since the check requires the version
`build.json` names.

Renovate ([estate
ADR-007](https://github.com/khelias/khe-architecture/blob/main/decisions/007-automated-writers.md))
automerges GitHub Actions minor and patch updates, digests and pins
(`renovate.json`) once a release is three days old, never `@khelias/ui`. The way back is to revert its commit on `main` and push.

This repo never starts a print and sends the printer nothing but read requests.
