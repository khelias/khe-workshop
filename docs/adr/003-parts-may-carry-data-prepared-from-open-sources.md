# ADR-003: A part may carry data prepared from open sources

- **Status:** Accepted (2026-11-21)
- **Related:** [ADR-001](001-published-parts-carry-their-proof.md), [estate ADR-043](https://github.com/khelias/khe-architecture/blob/main/decisions/043-household-parts-are-public-source-built-into-khe-sites.md)

## Context

The Estonia relief map is the first part whose shape comes from measured data, not
from dimensions written in OpenSCAD: the height of the land, the coastline, the
lakes and the state border. Reading a countrywide elevation raster, rasterising
polygons and resampling them needs libraries the Python standard library does not
have, while the check and CI run on the standard library and OpenSCAD only.

The sources have to allow a public derivative. Copernicus GLO-30 is a surface
model, so forests would read as hills at the map's height exaggeration, and a
raster made from OpenStreetMap is likely a derived database under the ODbL's
share-alike terms.

## Decision

1. **A part may commit data that a script in its own `data/` folder prepares from
   open sources.** The script may use third-party packages, pinned by version in
   the command that runs it (`uv run --no-project --python 3.12 --with
   <package>==<version> ...`). It runs by hand, never in `scripts/check.py` or CI.
2. **The check and OpenSCAD read only the committed result.** The script records
   what it read (file names, sizes, SHA-256) and the scale it used beside its
   output, and running it again on the same downloads gives the same files byte
   for byte.
3. **The relief map's sources** are the Estonian Land and Spatial Development
   Board's (Maa- ja Ruumiamet) whole-Estonia terrain model at 25 m, its county
   polygons and the Estonian Topographic Database's whole standing waters, under
   [its open data licence](https://geoportaal.maaruum.ee/opendata-licence), which
   allows derivatives and publication with a reference to the licensor, the data
   and its date; and Natural Earth's 1:10m country polygons, in the public domain,
   used only to keep the sea off neighbouring land and to cut the border lakes
   (Peipsi, the Narva reservoir), which the county polygons leave out whole, at
   the state border. The part's `credit` names them
   in that form.

## Alternatives considered

- **Standard library only.** A GeoTIFF reader and a polygon rasteriser written
  for one part would be the largest and least checked code in the repo.
- **Copernicus GLO-30 or OpenStreetMap.** Ruled out above.

## Consequences

- The prepared data is committed, so the check, CI and the room need nothing new.
- Updating a source is a re-run of the script and a commit of its output, which
  changes the part's renders.
