# Fission540 — Linux-native Fusion 360 replacement

## Context
Goal: an open-source, Linux-only CAD application with Fusion 360's feature set and workflow, so Windows can be dropped. No cloud features. Priority workspaces: **Parametric Design**, then **Drawings, Rendering, Simulation (FEA)**. Electronics/PCB and CAM are out of scope for now (KiCad and existing CAM tools cover them; revisit later).

Decisions made:
- New application (not a FreeCAD fork), C++20 + Qt6.
- OpenCascade (OCCT 7.8+) as the geometry kernel, accessed only through an internal `kernel/` interface so a custom kernel can replace it later.
- Planned here on Windows; built and run on a Linux machine. Repo starts empty (`C:\GrantElectronics\Fission540`).

## Architecture

```
fission540/
  CMakeLists.txt, CMakePresets.json
  src/
    kernel/     Abstract B-rep interface (Shape, Face, Edge, ops) + OCCT implementation. Only module that includes OCCT modelling headers.
    core/       Document, components/occurrences, feature timeline, parameters + expression engine, undo/redo, persistent (topological) naming, recompute graph.
    sketch/     2D sketch entities, constraints, PlaneGCS solver (vendored from FreeCAD, LGPL), projection/intersection of model geometry.
    features/   Extrude, revolve, sweep, loft, rib, hole, thread, fillet, chamfer, shell, draft, scale, combine, split, pattern (rect/circ/path), mirror, thicken, offset face, press-pull, construction planes/axes/points, surface features, sheet metal.
    assembly/   Components, joints (rigid, revolute, slider, cylindrical, pin-slot, planar, ball), as-built joints, joint limits, motion links, contact/interference, rigid-body joint solver.
    io/         .f3d reader (zip + zstd, ShapeManager B-rep), native .f540 format (zip: JSON timeline + parameters + cached BREP + thumbnails), STEP/IGES (OCCT XDE, with colours/assemblies), STL/3MF/OBJ, DXF import to sketch.
    drawing/    Sheets, base/projected/section/detail/broken views (OCCT HLRBRep), dimensions, centre marks, GD&T, BOM + balloons, title blocks, PDF/DXF/SVG export.
    render/     LuxCoreRender (Apache-2.0) integration: materials/appearances library, HDRI environments, decals, offline + interactive render.
    sim/        Netgen (LGPL) tet meshing, CalculiX (ccx, run as external process) solver, setup UI (materials, loads, constraints, contacts), results post-processing (stress/displacement/safety factor, deformed shape, probes). Studies: static, modal, thermal, buckling.
    ui/         Qt6 main window: workspace switcher, ribbon toolbar, browser tree, timeline bar (drag/reorder/rollback/suppress), command dialogs, marking menu (right-click radial), ViewCube, navigation (orbit/pan/zoom presets incl. Fusion mouse mapping), selection filters, measure, section analysis.
    viewer/     OCCT AIS/V3d in a native X11 child window (QOpenGLWidget later): PBR shading, edges, transparency, highlight, analysis overlays (zebra, curvature, draft).
    scripting/  pybind11 Python API mirroring the document/feature model; add-in loader; text command console.
  tests/        Catch2 unit tests + geometry regression corpus (models + expected volume/area/face counts).
  third_party/  PlaneGCS, libdxfrw (vendored); OCCT, Qt6, Eigen, Boost, LuxCore, Netgen, pybind11 via system packages or CMake FetchContent.
```

Key design points:
1. **Persistent naming is the highest-risk core piece** (it's the main source of FreeCAD's failures). Every feature records OCCT `Generated/Modified/Deleted` history and assigns stable IDs to the faces/edges it produces (feature ID + source-entity ID + role, similar to Onshape/Fusion). Downstream references store these IDs, never indices. When an ID can't be resolved, the feature errors visibly in the timeline (red/yellow markers like Fusion) instead of silently rebinding to wrong geometry.
2. **Recompute model:** the timeline is an ordered list of features. Edits trigger recompute from the earliest changed feature, with each feature's shape cached. Rollback marker = recompute up to index N.
3. **Parameters:** user parameters + per-feature model parameters with units and expressions (`d1 * 2 + 5 mm`), dependency graph, change-parameters dialog.
4. **Document vs. GUI separation:** core/features/assembly have no Qt dependency, so tests and Python run headless.
5. **Licence:** GPL-3.0-or-later (compatible with OCCT LGPL, PlaneGCS LGPL, Netgen LGPL, LuxCore Apache-2.0; CalculiX GPL is run as a separate process).

## Phases (each ends with a usable build)

**Phase 0 — Skeleton (week 1–2)**
CMake build on Ubuntu 24.04 (OCCT 7.8 built from source; Qt6 from apt), CI (GitHub Actions, Linux), Qt main window + OCCT viewer showing a box, orbit/pan/zoom, ViewCube, STEP import/display (with assembly structure).

**Phase 1 — Sketcher**
Sketch on plane/face, line/arc/circle/rectangle/polygon/spline/slot/ellipse/conic/text, trim/extend/offset/fillet/mirror/pattern, all Fusion constraints, driving/driven dimensions, PlaneGCS solving with fully-constrained colouring, project/include geometry, construction geometry.

**Phase 2 — Core parametric solids**
Document + timeline + parameters + persistent naming. Extrude (all extents, operations: join/cut/intersect/new body/new component), revolve, sweep, loft, hole, thread (cosmetic + modelled), fillet (constant/variable/chord), chamfer, shell, draft, combine, split body/face, patterns, mirror, press-pull, construction geometry. Native file save/load. Undo/redo. Measure, inspect, section analysis.

**Phase 3 — Components & assemblies**
Components/occurrences, browser tree, joints + joint solver, motion study playback, interference check, insert/derive external design, BOM data.

**Phase 4 — Surfaces, forms & sheet metal**
Patch, extend, trim, stitch, unstitch, offset surface, thicken, ruled surface, boundary fill. Sheet metal rules, flange, bend, unfold/refold, flat pattern + DXF export. Form (T-spline-style subdivision) workspace: via an OpenSubdiv-based subdivision body converted to NURBS/B-rep on exit — scoped as a later sub-phase because conversion to B-rep is the hard part.

**Phase 5 — Drawings**
Drawing from design, standard/projected/section/detail/break views with HLR, associative dimensions, annotations, GD&T, surface finish symbols, parts list + balloons, templates (ISO/ANSI), PDF/DXF export.

**Phase 6 — Rendering**
In-viewport PBR appearances (Phase 0 viewer upgraded), appearance library + drag-and-drop, LuxCore offline/interactive render, HDRI scenes, camera/DOF, render gallery.

**Phase 7 — Simulation**
Study setup UI, material library (mechanical/thermal properties), Netgen meshing with local refinement, CalculiX input deck generation, run/progress, result visualisation (contour plots, deformation scale, animations, probes), report export. Static stress first, then modal, thermal, buckling.

**Phase 8 — Scripting & polish**
Python API + add-ins + console, keyboard shortcut customisation, preferences, performance (large assemblies: instancing, LOD, background recompute).

Roughly: phases 0–3 are the minimum to replace Fusion for everyday part/assembly design. Each phase is multiple months of iteration, mainly on robustness.

## Fusion 360 compatibility (both directions)
Goal: designs move between Fission540 and Fusion 360 in both directions, parametric where possible. The native format stays `.f540`; Fusion's format is undocumented, changes with Fusion updates, and cannot be tested on Linux, so it is not used as the native save format.

**Fusion → Fission540**

1. **Direct `.f3d` reading (in progress, `src/io`, format notes in `docs/formats/f3d.md`):** container, B-rep geometry (ShapeManager binary, ACIS SAB-compatible) and component placement are decoded and imported; a committed sample (`tests/data/f3d/`) is imported in CI. Next: parametric history (sketches, features, parameters), which needs differential analysis of test designs made in Fusion.
2. **STEP import (Phase 0/2):** STEP AP214/AP242 exported from Fusion, read via OCCT XDE, keeping the assembly tree, component names, colours and placements. Geometry only. Imported bodies become base features that can be built on.

**Fusion bridge add-in (`tools/fusion-bridge/`, Python, Fusion API)** — one add-in, both directions, runs inside Fusion on Windows/macOS:

Status: both directions written (`tools/fusion-bridge/Fission540Bridge`) — export, batch project export and import — with schema 0 in `docs/formats/f540x.md` and mock-API tests for both in CI. **Not yet run inside Fusion**: that needs a Windows or macOS machine with Fusion, and is the next step for this add-in.

- **Export:** writes each design to a `.f540x` bundle: JSON for user/model parameters, sketches (entities, constraints, dimensions), timeline features with their inputs, components/occurrences/transforms, joints, plus a STEP of every component as fallback geometry. Fission540 rebuilds each timeline entry as a native parametric feature where that feature type exists; unsupported features come in as frozen B-rep from the STEP fallback and are flagged in the timeline. Batch mode walks a Fusion project/hub folder and exports every design in one run.
- **Import:** reads a `.f540x` and rebuilds it in Fusion through the API: parameters, sketches, timeline features, components, joints, in timeline order. Features Fusion's API cannot express, and features whose geometry does not come back to the volume the bundle recorded, are inserted as base-feature bodies from the STEP fallback and listed in a report written beside the bundle. References to faces and edges are matched by geometric signature and fail visibly rather than rebinding (see `docs/formats/f540x.md`, "Reading a bundle"). This is the supported way to open a Fission540 design in Fusion with its history. `.f540` itself will be read once that format exists; the native format has no writer yet, so the add-in reads the bundle schema only.
- The `.f540x` JSON schema is shared by both directions and versioned in `docs/formats/f540x.md`, so the add-in and Fission540 agree on one mapping per feature type.
- **Time-sensitive:** export must exist before Windows is removed; import needs a Windows or macOS machine with Fusion to test. Round-trip tests (Fusion → `.f540x` → Fission540 → `.f540` → Fusion) use the same test designs as the `.f3d` analysis.

**Fission540 → `.f3d` direct writing (experimental):**

1. **Geometry-only `.f3d` export (early experiment, needs a Fusion test session):** write a minimal `.f3d` with components, occurrences, placements and bodies (SAB blobs with the attributes the design segment references) and check what Fusion opens. Outcome decides whether direct writing is viable; result goes in `docs/formats/f3d.md`.
2. **Parametric `.f3d` writing (long term, conditional):** only after the reader decodes timeline/sketches/features and step 1 shows Fusion accepts files we write. Needs re-testing against each Fusion release.

## Status
- Phase 0 skeleton in place: kernel (box + booleans + properties), core (Document/Feature/Timeline with rollback marker, suppression, error state), BoxFeature, Qt main window with browser/timeline docks, OCCT viewport (native X11 window, Fusion-style middle-mouse navigation, ViewCube), Catch2 tests, Linux CI.
- Uses Ubuntu 24.04's OCCT 7.6 for now; move to OCCT 7.8+ built from source when needed.

## Critical early files
- `CMakeLists.txt`, `CMakePresets.json`, `scripts/setup-ubuntu.sh` (deps + OCCT build)
- `src/kernel/Shape.h`, `src/kernel/occt/OcctShape.cpp`
- `src/core/Document.h`, `src/core/Timeline.h`, `src/core/Feature.h`, `src/core/NamingService.h`, `src/core/Parameters.h`
- `src/sketch/Sketch.h`, `src/sketch/SolverAdapter.cpp` (wraps PlaneGCS)
- `src/ui/MainWindow.cpp`, `src/viewer/OcctViewport.cpp`, `src/ui/TimelineWidget.cpp`

## Verification
- **Unit tests (Catch2, headless):** each feature against known geometry: volume, surface area, face/edge counts, bounding box. Expression engine and units. Sketch solver convergence and DOF counts.
- **Persistent naming regression tests:** build model → edit upstream sketch dimension → recompute → assert downstream fillets/chamfers still reference the intended edges (checked by geometric signature).
- **Round-trip tests:** save/load .f540 gives an identical timeline and shape. STEP export→import preserves volume within tolerance.
- **Regression corpus:** a folder of reference models (STEP + .f540) recomputed in CI; any change in volume/topology fails the build.
- **Drawings:** HLR output compared against golden SVGs.
- **Sim:** cantilever beam and plate-with-hole benchmarks against analytical stress/deflection (within ~5%).
- **Manual:** run the app on the Linux box after each phase and rebuild a set of your real Fusion parts end-to-end (sketch → features → assembly → drawing → render → sim).
