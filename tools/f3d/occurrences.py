#!/usr/bin/env python3
"""List components and occurrences (with placement) in a Fusion design segment.

Research tool for the Fission540 .f3d reader; layout notes in docs/formats/f3d.md.

Usage: occurrences.py SEGMENT_DIR
"""
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from design_stream import Segment  # noqa: E402

OCCURRENCE_CLASS = "CE2913AA-CFE0-4F04-9102-24424ED3BCFA"
COMPONENT_CLASS = "E03784ED-5E19-4E14-B9F2-3B07017018CD"
TRANSFORM_MARK = b"\x09\x00\x00\x00Transform\x00"


def find_header(bulk, oid):
    """Inline or top-level object header: u32 n, n ASCII digits, u64 id."""
    pat = re.compile(rb"[\x01-\x08]\x00\x00\x00[0-9]{1,8}" + re.escape(struct.pack("<Q", oid)))
    for m in pat.finditer(bulk):
        n = bulk[m.start()]
        if m.end() - m.start() == 4 + n + 8:
            return m.start()
    return None


def ref_at(b, p):
    """Reference: 0x01, u64 id, 2 bytes. Returns (id, next position)."""
    if b[p] != 1:
        raise ValueError(f"no reference at {p:#x}")
    return struct.unpack_from("<Q", b, p + 1)[0], p + 11


def parse_occurrence(bulk, oid):
    h = find_header(bulk, oid)
    if h is None:
        return None
    p = bulk.find(TRANSFORM_MARK, h, h + 400)
    if p < 0:
        return dict(id=oid, error="no Transform marker")
    p += len(TRANSFORM_MARK)
    self_id, p = ref_at(bulk, p)
    # Trailing bytes after a reference vary (2 or 3 zero bytes); skip to the next marker.
    while bulk[p] == 0:
        p += 1
    comp_id, p = ref_at(bulk, p)
    second = bulk.find(b"\x01" + struct.pack("<Q", comp_id), p, p + 600)
    if second < 0:
        return dict(id=oid, component=comp_id, error="no second component ref")
    q = second + 11
    identity = bulk[q] == 1
    matrix = None
    if not identity:
        matrix = struct.unpack_from("<16d", bulk, q + 1)
    return dict(id=oid, self=self_id, component=comp_id, identity=identity, matrix=matrix, header=h)


def component_info(seg, cid):
    h = find_header(seg.bulk, cid)
    if h is None:
        return {}
    window = seg.bulk[h : h + 20000]
    names = [s.decode("utf-16-le") for s in re.findall(rb"(?:[\x20-\x7e]\x00){2,}", window)]
    blob = next((s for s in names if s.startswith("BREP.") and s.endswith(".smb")), None)
    # Name: first non-GUID, non-material string.
    name = next((s for s in names if not re.fullmatch(r"[0-9A-Fa-f-]{36}\$?", s)
                 and not s.startswith(("PrismMaterial", "Prism-", "BREP.", "ProteinAsset", "1_"))), None)
    return dict(name=name, blob=blob)


def main():
    seg = Segment(sys.argv[1])
    occ_type = next((t for t in seg.types if t["guid"].upper() == OCCURRENCE_CLASS), None)
    comp_type = next((t for t in seg.types if t["guid"].upper() == COMPONENT_CLASS), None)
    print("occurrence class present:", bool(occ_type), "component class present:", bool(comp_type))
    comps = {}
    for cid in (comp_type["ids"] if comp_type else []):
        comps[cid] = component_info(seg, cid)
        print(f"component {cid:#x}: {comps[cid]}")
    for oid in (occ_type["ids"] if occ_type else []):
        try:
            o = parse_occurrence(seg.bulk, oid)
        except ValueError as e:
            o = dict(id=oid, error=str(e))
        if o is None:
            print(f"occurrence {oid:#x}: not serialised")
            continue
        if "error" in o:
            print(f"occurrence {oid:#x}: {o['error']}")
            continue
        comp = comps.get(o["component"], {}).get("name")
        if o["identity"]:
            place = "identity"
        else:
            m = o["matrix"]
            place = (f"R=[{m[0]:.4g} {m[1]:.4g} {m[2]:.4g} | {m[4]:.4g} {m[5]:.4g} {m[6]:.4g} | "
                     f"{m[8]:.4g} {m[9]:.4g} {m[10]:.4g}] T=({m[3]*10:.4g}, {m[7]*10:.4g}, {m[11]*10:.4g}) mm "
                     f"last row=({m[12]:.3g} {m[13]:.3g} {m[14]:.3g} {m[15]:.3g})")
        print(f"occurrence {oid:#x} -> component {o['component']:#x} ({comp}): {place}")


if __name__ == "__main__":
    main()
