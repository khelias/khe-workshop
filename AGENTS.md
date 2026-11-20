# khe-workshop

Workspace-wide rules (push, review, docs, estate ADRs) are in [khe-workspace
`AGENTS.md`](https://github.com/khelias/khe-workspace/blob/main/AGENTS.md).

The household's 3D-printable parts as public OpenSCAD source, their checks and
the Töökoda room. Why the repo is public and how khe-sites builds the room:
[estate ADR-043](https://github.com/khelias/khe-architecture/blob/main/decisions/043-household-parts-are-public-source-built-into-khe-sites.md).
This repo's own decisions: [docs/adr/](docs/adr/).

## Commands

- `python3 scripts/check.py` - renders every export, checks the mesh, the bed and
  the probes, verifies published parts and searches the repo for private terms.
  Exit 0 on a pass, 1 on a failure naming the part, 2 when OpenSCAD is missing.
  On the platform `build.json` names, the STL files and `check.json` compare byte for
  byte; on another, under the same OpenSCAD version, the STL surfaces compare within
  0.001 mm (a few small patches may be triangulated differently) and `check.json`
  without its hashes and triangle counts, numbers within 0.001.
- `python3 scripts/build.py` - writes `published/` for parts marked published.
- `python3 scripts/replay.py <gcode> --part <id>` - turns printed G-code into
  `build/replay/<id>.bin.gz`, within 1.5 MB, from the part's `replay` settings.
  G-code stays out of git.
- `python3 scripts/site_build.py <out> [--preview] [--base /workshop/]` - writes the
  room's pages. `--preview` includes unpublished parts; without it the build verifies
  each published part's files and proof and fails when none is published. `--base`
  is how khe-sites builds the room: root-relative URLs in the pages and the modules'
  imports, so its stamper versions them, `?v=` on the data files, and no language
  link of its own, since the site header switches language. Marker comments
  (`khe:head`, `khe:header`, `khe:footer`, `khe:consent`) are where khe-sites adds
  the family shell.
- `node --test web/test/*.test.mjs` - the decoder, the slider and the loaders, and a
  `--base` build of the published parts.
- `npm run -s lint` - the family design check, against an empty baseline.

The scripts use the Python standard library and OpenSCAD only.

## Layout

- `parts/<id>/part.json` - titles, story, licence, credit, exports, probes, proof
- `parts/<id>/<id>.scad` - the public source
- `parts/<id>/published/` - generated, only for a published part
- `scripts/` - the check and the builders; `workshop.py` holds what they share
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
least `min`). A part with non-manifold edges declares how many and why.

A replay covers `replay.first_layer` (default 1) to `last_layer`, so layers that
held family text are left out at either end; `before_label` and `after_label` name
what the room shows in their place. `stage_inlay` names an export the stage draws
inside the stage mesh in the colour printed below the replay. `replay.tolerance`
(1/100 mm, default 2) merges more for a replay over its budget, and an export's
`defines` may lower `$fn` or a mesh resolution for a part over its 10 MB budget
([ADR-001](docs/adr/001-published-parts-carry-their-proof.md)).

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
automerges GitHub Actions minor and patch updates, digests and pins (`renovate.json`),
never `@khelias/ui`. The way back is to revert its commit on `main` and push.

This repo never starts a print and sends the printer nothing but read requests.
