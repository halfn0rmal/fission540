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

## Design data (MetaStream / BulkStream)

Tools: `tools/f3d/design_stream.py` (type table, index, object dumps), `tools/f3d/occurrences.py`,
`tools/f3d/import_plan.py` (prints exactly what the importer will place).

### MetaStream [verified]
- **Type table**: entries `u32 36, class GUID (ASCII), u32 36, parent class GUID, u32 index, u32 n, module name, u32 count, count × u64 object id`.
  This is a class hierarchy: only concrete classes list objects. Modules seen: `Fusion`, `CommonData`, `Geometry`, `Component`, `Body`, `MSketch`, `Dimension`, `EntityTracking`, `Scene`.
  Class GUIDs are identical across all samples (2024–2025 builds).
- **Index** at the end: `(u64 BulkStream offset, u64 id)` pairs, both increasing, alignment relative to end-of-file varies. The id stored next to an offset belongs to the *previous* object; read the id from the object header instead. Only top-level objects are indexed; most objects are serialised inline inside others.

### BulkStream objects [verified]
- Header: `u32 n, n ASCII digits (per-class serialisation version, e.g. "341"), u64 object id`. Headers can be found for inline objects too.
- Reference: `0x01, u64 object id`, followed by 2 or 3 bytes (varies).
- Strings: `u32 char count + UTF-16LE`. Names, expressions (`198 mm`), feature names (`Extrude`, `Fillet`, `Sketch`, `Body->Comp`) are readable.

### Classes decoded

| class GUID | module | meaning | layout notes |
|---|---|---|---|
| `E03784ED-5E19-4E14-B9F2-3B07017018CD` | Fusion | component definition | name is the first non-internal UTF-16 string after the header [observed] |
| `372234A0-2A6C-4122-8047-E74DBA04F326` | Body | component body container | reference to the component + UTF-16 `BREP.<guid>.smb` (and `.smbh`) [verified]; then `u32 N` + N pointers (runtime garbage) + `u32 N` + N u64 entity tags, one per top-level SAB entity (N = blob header count − 1) [verified] |
| `CE2913AA-CFE0-4F04-9102-24424ED3BCFA` | Component | occurrence | see below [verified for identity + translation] |
| `2D6E13A1-BBEF-4FB3-9277-00D99F634136` | Fusion | timeline feature (CreateComponent, CopyPaste…); CopyPaste carries the paste matrix [observed] |
| `D3937028-C20C-4E65-B010-94AD418A5C20` | Body | per-body appearance/material (PrismMaterial ids) [observed] |

**Occurrence** layout after the header: change-flag names (`Appearance`, `Geometry`, `PhysicalMaterial`, `Properties`, `StructureChange`, `Transform`), self reference, component reference, UTF-16 id string (`1_2495`), u8, u32, two GUID strings, u8, component reference again, then **u8 placement flag: 1 = identity (no matrix stored), 0 = 16 doubles, row-major 4×4, translation in m[3], m[7], m[11] in cm**, then a reference to the parent (root) object.
Verified: a copy-pasted occurrence at (0, 6.2, 0) cm, matching its CopyPaste feature. Not yet verified: rotations (convention assumed `p' = M·p`), nested sub-assemblies (all samples are one level deep). The root occurrence in single-component designs uses a different layout without the `Transform` marker; the importer places the root at the origin.

### Which bodies in a blob are current [heuristic]
Each `.smb` holds the component's current bodies **plus** feature-cache bodies (tool bodies, sketch profiles, earlier states). The SAB header count gives the top-level saved entities (records `[0, count)`); nested caches come after.
- Blobs that use `ATTRIB_CUSTOM` `Timestamp_attrib_def` attributes (newer files): the importer takes the tagged top-level bodies.
- Untagged blobs (older files): the leading run of top-level body records, closed solids only (drops sketch profile sheets).

Known gap: after "Create Components from Bodies", the root blob still holds the original tagged bodies (Sensor1: root bodies 56 and 62), which get imported as extra bodies. The exact current-body list is in the design data (`EntityTracking` / `Body` classes) and still needs decoding; ground truth (body names per component as shown in Fusion's browser) would settle it.

### Still unknown
Timeline features and their parameters, sketches (entities, constraints, dimensions), user parameters, joints. Plan: differential analysis of minimal test designs.
