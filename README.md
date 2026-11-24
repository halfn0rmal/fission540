# Fission540

Open-source, Linux-only parametric CAD with a Fusion 360-style workflow: sketches, a feature timeline, components and joints, drawings, rendering and FEA. No cloud features.

Status: early skeleton (Phase 0). See [docs/PLAN.md](docs/PLAN.md) for the architecture and roadmap.

## Stack

- C++20, CMake, Qt6
- OpenCascade (OCCT) geometry kernel, accessed only through `src/kernel`
- Catch2 tests

## Build (Ubuntu 24.04)

```sh
./scripts/setup-ubuntu.sh        # installs build dependencies (sudo)
cmake --preset release
cmake --build --preset release
ctest --preset release
./build/release/app/fission540
```

On Wayland the app runs through XWayland (`QT_QPA_PLATFORM=xcb` is set automatically) because the OCCT viewer uses a native X11 window.

## Opening Fusion 360 files

File > Import reads `.f3d` geometry directly (bodies, all faces/edges). Components are placed; sketches and the timeline are not decoded yet. See [docs/formats/f3d.md](docs/formats/f3d.md).

Command-line check / conversion:

```sh
./build/release/src/io/fission-f3d2step design.f3d out.step
FISSION_F3D_SAMPLES=~/f3d-samples ctest --preset release -R f3d   # import a folder of your designs
```

## Moving designs out of Fusion 360

`tools/fusion-bridge/` is a Fusion add-in that exports designs (one, or a whole project) to `.f540x` bundles: parameters, sketches, timeline, components, joints, plus STEP and the original `.f3d`. See its [README](tools/fusion-bridge/README.md).

## Layout

```
src/kernel    B-rep interface + OCCT implementation
src/core      Document, features, timeline
src/features  Concrete modelling features
src/io        File import/export (Fusion .f3d reader, STEP)
src/viewer    OCCT 3D viewport widget
src/ui        Main window, browser, timeline
app/          Executable entry point
tests/        Catch2 tests
tools/fusion-bridge  Fusion 360 add-in: export to .f540x
tools/f3d     .f3d format research scripts
```

## Licence

GPL-3.0-or-later. See [LICENSE](LICENSE).
