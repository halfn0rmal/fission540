# Fission540 bridge (Fusion 360 add-in)

Runs inside Fusion 360 (Windows/macOS). Currently one direction: exports Fusion designs to `.f540x` bundles that Fission540 will import. The other direction (`.f540` into Fusion) is planned, see `docs/PLAN.md`.

Bundle format: [`docs/formats/f540x.md`](../../docs/formats/f540x.md).

## Install

1. In Fusion: **Utilities → Add-Ins → Scripts and Add-Ins** (Shift+S).
2. Click **+** next to the search box, choose **Script or add-in from device**, and select the `Fission540Bridge` folder in this directory.
3. Select **Fission540Bridge** in the list and click **Run**. Tick **Run on Startup** to keep it loaded.

Commands appear in **Utilities → Add-Ins**:

- **Export to Fission540**: the active design → one `.f540x` file.
- **Batch export project to Fission540**: every design in the active project → a folder per project, keeping the project's folder structure. Writes `batch-export.log` listing each design and any failures. Each design is opened, exported and closed; large projects take a while. **Stop** in the progress dialog ends after the current design.

## What is exported

Each bundle holds `design.json` (parameters, components and bodies, occurrence tree with transforms, sketches with constraints/dimensions/profiles, timeline features with their inputs, joints), a STEP of the assembly and of each component with bodies, the design as a Fusion archive (`source.f3d`), and `export.log`.

Feature types without a dedicated description are still listed in the timeline with their name, type and parameters, marked `unsupported`. Anything that failed to export is in `export.log`.

## Development

The add-in only runs inside Fusion. `tests/test_exporter.py` runs the exporter against mock API objects to catch Python errors without Fusion (also run in CI):

```sh
python -m unittest discover -s tools/fusion-bridge/tests
```

After changing the code in Fusion: stop and run the add-in again in Scripts and Add-Ins (Fusion caches imported modules until it restarts; if a change seems ignored, restart Fusion).
