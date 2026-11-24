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

## Layout

```
src/kernel    B-rep interface + OCCT implementation
src/core      Document, features, timeline
src/features  Concrete modelling features
src/viewer    OCCT 3D viewport widget
src/ui        Main window, browser, timeline
app/          Executable entry point
tests/        Catch2 tests
```

## Licence

GPL-3.0-or-later. See [LICENSE](LICENSE).
