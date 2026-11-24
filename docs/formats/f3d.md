# Fusion 360 `.f3d` format notes

Clean-room notes, derived only from inspecting `.f3d` data files. Never from Autodesk program code.
Confidence markers: **[verified]** = checked numerically across sample files, **[observed]** = seen in samples but not cross-checked, **[unknown]** = not yet decoded.

Samples used: 5 user designs (single part to multi-component assembly) + 1 Autodesk library screw, Fusion builds from 2024–2025 (ASM 229.x / 231.x).

## Container [verified]

Plain ZIP. Entry compression is either Stored, Deflate, or **method 93 = Zstandard** (newer Fusion builds). Python's `zipfile` and older libzip can't read method 93.

```
Manifest.dat                     UTF-16 strings: doc type "FusionDocType", ".f3d", GUIDs, app list (CAM, Sim...), asset folder name
Properties.dat                   u32 length + JSON ("{}")
ComponentReferenceData.json      JSON (external component refs; "[]" when none)
<Asset>/Manifest.dat             asset type "Neutron3DAssetType", GUIDs
<Asset>/Breps.BlobParts/BREP.<guid>.smb    current B-rep geometry (ShapeManager binary)
<Asset>/Breps.BlobParts/BREP.<guid>.smbh   B-rep with history (delta_state records; rollback/undo states)
<Asset>/<Segment>/MetaStream.dat           type table for the design object graph
<Asset>/<Segment>/BulkStream.dat           design object graph (timeline, sketches, parameters, components)
<Asset>/ProteinAssets.BlobParts/*.protein  materials/appearances (not yet examined)
<Asset>/DesignConfigurationTable.BlobParts/*.dsgcfg
<Asset>/Previews/small.png       thumbnail
Animation[Active]/...            animation workspace, same layout
```

`<Asset>` is `FusionAssetName` or `FusionAssetName[Active]`. `<Segment>` is `Design1` (older) or `FusionDesignSegmentType1` / `FusionACTSegmentType1` (newer).

## B-rep blobs: `ASM BinaryFile4` [verified]

Autodesk ShapeManager binary. Token-compatible with ACIS SAB.

Header: `"ASM BinaryFile4"` (15 bytes), i64 version (22900 = ASM 229), i32, i32, then tokens:
product string, ASM version string, date string, **units (double, mm per model unit: 10.0 = cm)**, resabs (1e-6), resnor (1e-10).

Tokens (1-byte tag, little-endian payload):

| tag | meaning | payload |
|---|---|---|
| 0x02 | char | 1 |
| 0x03 | short | 2 |
| 0x04 | long | i32 |
| 0x05 | float | f32 |
| 0x06 | double | f64 |
| 0x07 / 0x08 / 0x09, 0x12 | string | u8 / u16 / u32 length + bytes |
| 0x0A / 0x0B | true / false | – |
| 0x0C | entity reference | i32 record index, -1 = null |
| 0x0D | identifier (record class) | u8 length + bytes |
| 0x0E | sub-identifier (class prefix, e.g. `cone` in `cone-surface`) | u8 length + bytes |
| 0x0F / 0x10 | subtype block open / close | – |
| 0x11 | record terminator | – |
| 0x13 / 0x14 | position / vector | 3 × f64 |
| 0x15 | enum | i32 |
| 0x16 | 2D vector | 2 × f64 |

Records are numbered from 0 in file order (record 0 = `asmheader`). References index this list. Parsing stops at `Begin-of-ASM-History-Data`.

### Entity layouts [verified across 29 blobs]

Field index counts tokens after the class identifiers. Every entity starts `[0] attrib ref, [1] history id (long), [2] ref (always null)`.

| entity | fields from [3] |
|---|---|
| body | lump, wire, transform |
| lump | next lump, shell, owner body |
| shell | next shell, subshell, face, wire, owner lump |
| face | next face, loop, shell, subshell, surface, sense (true = reversed), double-sided, [containment if double-sided] |
| loop | next loop, coedge, face |
| coedge | next, previous, partner, edge, sense (true = reversed), loop, long 0, pcurve |
| edge | start vertex, start param, end vertex, end param, coedge, curve, sense, convexity string |
| vertex | edge, long, point |
| point | position |
| transform | 3 rotation vectors, translation vector, scale, rotation / reflection / shear flags |

### Parameter rules [verified]
- Forward edge: `curve(start_param)` = start vertex, `curve(end_param)` = end vertex (2779/2779 edges).
- Reversed edge: use negated parameters on the curve.
- Coedge with sense = reversed traverses its edge end→start. Loops close under this rule (1169/1169).

### Geometry [observed]
Intervals are `true <double>` (bounded) or `false` (unbounded), so field positions after an interval vary.

| class | fields from [3] |
|---|---|
| straight-curve | root, direction (param scale = length), interval |
| ellipse-curve | centre, normal, major-axis vector (length = major radius), ratio, interval. `P(t) = c + M cos t + ratio·(n̂×M) sin t` [verified] |
| intcurve-curve | reversed flag, `{ subtype version ... 'nubs'/'nurbs' approximation ... defining surfaces ... }` |
| plane-surface | root, normal, u direction, reverse-v flag, … |
| cone-surface | centre, axis, major-axis vector, ratio, u interval, sin(half angle), cos(half angle), radius scale, … (sin = 0 → cylinder) |
| torus-surface | centre, axis, major radius, minor radius, u direction, … |

`nubs` (non-rational B-spline) in intcurve: `degree, closure, knot_count, (knot, multiplicity) × knot_count, control points (3 doubles each), fit tolerance`. End multiplicities are stored as `degree` (OCCT expects `degree + 1`).

Not seen in samples yet (need test files): `sphere`, `spline` surfaces (lofts, variable fillets, freeform), `nurbs` (rational), non-identity body transforms.

## Design data (MetaStream / BulkStream) [unknown]

Object graph serialisation. MetaStream lists types as (module name, class GUID) pairs, with modules `Fusion`, `CommonData`, `Geometry`, `MSketch`, `Dimension`, `EntityTracking`, `Scene`. No class names, only GUIDs.
BulkStream contains records referencing those types. Some field and enum names are visible: `SketchesRoot`, `ComponentsRoot`, `ComponentInstancesRoot`, `DcSketchMetaType`, `crv_primary_id`, `pt_tag`, `EdgeStartVertexProgenitor`, unit system tables (`MmMKS`, `CmMKS`).

Decoding plan: differential analysis. Create minimal designs in Fusion that differ by one change (empty, one sketch line, one dimension value, one extrude, extrude distance changed, one component, one joint…) and diff the streams to map GUIDs to feature types and fields.

Needed for: timeline/history, sketches, parameters, **component placement** (B-rep blob transforms are identity, so occurrence transforms live here).
