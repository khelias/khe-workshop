# khe-workshop

The parts we design and 3D print for our own household, as source code. Each
part is a parametric OpenSCAD file with a check that proves it: the mesh is
closed, it fits the printer, and where a part has to fit something else, the fit
is tested in the model.

Töökoda, the room at [khe.ee/workshop](https://khe.ee/workshop/), lets a visitor
turn each published part, cut it open and scrub through its real print layer by
layer. A part is published once it has been printed and used, with its real print
recorded; a part not printed yet may show there as a labelled draft.

## Run it

You need [OpenSCAD](https://openscad.org/downloads.html) (a recent snapshot),
Python 3 and Node.js.

```bash
python3 scripts/check.py
```

The check renders every part and runs its probes. It exits 0 on a pass, 1 on a
failure that names the part and 2 when OpenSCAD is missing.

## Licences

The tools are under the [MIT licence](LICENSE). Each model has its own licence,
listed in [LICENSE-MODELS](LICENSE-MODELS). The U6-LR holder is non-commercial,
because its twist-lock is measured from another maker's model, and so is the star
egg, whose prints we sell.

More: [AGENTS.md](AGENTS.md) for how the repo works and
[docs/adr/](docs/adr/) for its decisions.
