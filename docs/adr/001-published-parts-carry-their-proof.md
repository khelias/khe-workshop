# ADR-001: Published parts carry their proof, in OpenSCAD, with generated data committed

- **Status:** Accepted (2026-11-19); point 1 superseded by [ADR-002](002-the-print-and-its-use-are-the-proof.md); point 3's budget raised from 5 to 10 MB on 2026-11-19, for the yarn bowl, before anything depended on the number
- **Related:** [estate ADR-043](https://github.com/khelias/khe-architecture/blob/main/decisions/043-household-parts-are-public-source-built-into-khe-sites.md)

## Context

This repo holds parts we design and print ourselves, and a room that shows them.
A model on a page claims that the part works, so the page needs something behind
that claim. The parts also need one source language, a way to get print data to
the page, and licences that respect where each shape came from.

## Decision

1. **A part is published only with proof.** `published: true` requires a photo of
   the real print and a recorded use. Without them a part stays in the repo as
   source and does not appear in the room.
2. **OpenSCAD is the source language.** Both first parts are written in it, its
   renders can be compared byte for byte, and it can later run the same source in
   a visitor's browser.
3. **Generated page data is committed per published part, within 10 MB.** G-code
   cannot be made in CI, because the printer's slicer profile stays out of public
   repos. The STL files, the replay and the check results are written locally by
   `scripts/build.py`, and the check proves they match the source. The budget is
   there because every rebuild adds a full copy to the history and the page loads
   the part's STL when it opens.
4. **Licences are per part.** The tools are MIT and our own models CC BY 4.0. The
   U6-LR holder is CC BY-NC 4.0 with credit, because its twist-lock was measured
   from Printables model 789473 by Peter H, which is CC BY-NC.

## Alternatives considered

- **build123d as the source language.** It has good agent tooling, but both parts
  already exist in OpenSCAD and were printed from that source.
- **Generating page data in CI.** That would need the slicer profile in a public
  place, or a runner holding it.
- **One licence for everything.** A single permissive licence would misstate the
  holder's terms.

## Consequences

- A part cannot appear in the room until it has really been printed and used.
- A published part's files must be rebuilt whenever its source changes, and under
  the OpenSCAD version recorded in its `build.json`.
- The repo grows by at most 10 MB per published part, each time it is rebuilt.
