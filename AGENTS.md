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
- `python3 scripts/build.py` - writes `published/` for parts marked published.

The scripts use the Python standard library and OpenSCAD only.

## Layout

- `parts/<id>/part.json` - titles, story, licence, credit, exports, probes, proof
- `parts/<id>/<id>.scad` - the public source
- `parts/<id>/published/` - generated, only for a published part
- `scripts/` - the check and the builders; `workshop.py` holds what they share
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

To publish a part: run the check, set `published: true` and fill `proof`, write
the replay, run `scripts/build.py`, then run the check again.

This repo never starts a print and sends the printer nothing but read requests.
