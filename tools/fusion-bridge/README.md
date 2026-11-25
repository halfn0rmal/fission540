# Fission540 bridge (Fusion 360 add-in)

Runs inside Fusion 360 (Windows/macOS) and moves designs in both directions:

- **Fusion → Fission540:** exports designs to `.f540x` bundles, one or a whole project.
- **Fission540 → Fusion:** rebuilds a `.f540x` bundle as a parametric Fusion design.

Bundle format: [`docs/formats/f540x.md`](../../docs/formats/f540x.md).

Status: written against the Fusion API documentation and tested against mocks of it
(`tests/`, also run in CI). **It has not been run inside Fusion yet** — that needs a
Windows or macOS machine with Fusion installed. Expect to fix call signatures on the
first real run; the add-in reports what failed rather than stopping, so one bad call
does not cost a whole design.

## Install

1. In Fusion: **Utilities → Add-Ins → Scripts and Add-Ins** (Shift+S).
2. Click **+** next to the search box, choose **Script or add-in from device**, and select the `Fission540Bridge` folder in this directory.
3. Select **Fission540Bridge** in the list and click **Run**. Tick **Run on Startup** to keep it loaded.

Commands appear in **Utilities → Add-Ins**:

- **Export to Fission540**: the active design → one `.f540x` file.
- **Batch export project to Fission540**: every design in the active project → a folder per project, keeping the project's folder structure. Writes `batch-export.log` listing each design and any failures. Each design is opened, exported and closed; large projects take a while. **Stop** in the progress dialog ends after the current design.
- **Import from Fission540**: one or more `.f540x` bundles → a new Fusion document each. Writes `<bundle>-import.log` beside each bundle.

## What is exported

Each bundle holds `design.json` (parameters, components and bodies, occurrence tree with transforms, sketches with constraints/dimensions/profiles, timeline features with their inputs, joints), a STEP of the assembly and of each component with bodies, the design as a Fusion archive (`source.f3d`), and `export.log`.

Feature types without a dedicated description are still listed in the timeline with their name, type and parameters, marked `unsupported`. Anything that failed to export is in `export.log`.

## What is imported

The bundle is rebuilt in a new document, in timeline order: user parameters, components
and occurrences, then each sketch and feature, then joints. Rebuilt parametrically:

| | |
|---|---|
| sketches | points, lines, circles, arcs, ellipses, fitted splines; anything else as a fixed spline from its NURBS form |
| sketch relations | the constraints and dimensions listed in `importer.CONSTRAINTS` / `DIMENSIONS` |
| features | extrude, revolve, sweep, loft, hole, fillet, chamfer, shell, draft, thicken, offset faces, combine, split body, mirror, move, scale, rectangular and circular pattern, construction planes/axes/points |
| assembly | components, occurrence tree with transforms, grounding, joints with their motion and limits |

Everything else is reported, and where the rebuilt geometry does not match the bundle
(body count, or volume by more than 0.1%) the component's STEP comes in as a base
feature named "Fission540 fallback geometry", so the shape is present and visibly frozen.

Three things to know about the result:

- **Parameters keep their names.** A rebuilt feature's parameters are renamed to the
  names the bundle used (`d7`, `width`), because expressions elsewhere in the bundle
  refer to them. An expression whose names do not all exist in the new design is
  imported as a plain number instead, and that is reported.
- **References are matched by geometry, not by identity.** Fusion's entity tokens mean
  nothing outside the document they came from, so a fillet's edges are found by
  comparing end points, length and curve type against the rebuilt model. A reference
  that does not match within tolerance fails the feature and is reported with how far
  off the closest candidate was — it is never rebound to the nearest edge.
- **Sketch axes are remapped.** Fusion picks a sketch's own axes when the sketch is
  created and they need not match the exported ones, so points are carried through
  world space. If the result would not be flat in the new sketch plane, the exported
  coordinates are used unchanged and the sketch is flagged.

Projected ("reference") sketch geometry is rebuilt as ordinary sketch geometry: the
shape is right but it will not follow the model.

## Development

The add-in only runs inside Fusion. `tests/` runs both directions against mocks of the
Fusion API (`tests/fusion_mock.py`) to catch Python errors, wrong call shapes and wrong
reference matching without Fusion — including a round trip, where a design is exported
and then imported back:

```sh
python -m unittest discover -s tools/fusion-bridge/tests
```

What the mocks cannot check is Fusion behaving differently from its documentation. When
running in Fusion for the first time, work through the import log: each line names the
entity and the reason, and a wrong API signature shows up as a traceback in it.

After changing the code in Fusion: stop and run the add-in again in Scripts and Add-Ins (Fusion caches imported modules until it restarts; if a change seems ignored, restart Fusion).

## Layout

```
Fission540Bridge/
  Fission540Bridge.py        add-in entry point and the three commands
  f540x/api.py               thin helpers over the Fusion API, used by both directions
  f540x/exporter.py          design -> design.json + STEP + source.f3d
  f540x/importer.py          design.json -> a rebuilt Fusion design: the order of events
  f540x/features.py          one builder per feature type, mixed into the importer
  f540x/sketches.py          rebuilding one sketch's geometry, constraints and dimensions
  f540x/resolve.py           matching exported references against rebuilt geometry
  f540x/report.py            what an import could not do, and why
tests/
  fusion_mock.py             mock of the slice of the Fusion API the bridge uses
  test_exporter.py           export against a mock design
  test_importer.py           import into a mock Fusion session, and a round trip
  test_addin.py              the add-in loads, registers its commands, and imports a bundle
```
