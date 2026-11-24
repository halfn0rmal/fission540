#!/usr/bin/env python3
"""Show what Fission540's .f3d importer will place: instances, blobs and selected bodies.

Mirrors src/io/src/F3dDesign.cpp + the body selection in AsmToOcct.cpp so the rules can
be checked against real files without building the C++ code.

Usage: import_plan.py DESIGN.f3d      (needs `pip install zstandard` for newer files)
"""
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sab_dump as sab  # noqa: E402
from occurrences import COMPONENT_CLASS, OCCURRENCE_CLASS, find_header, parse_occurrence  # noqa: E402

BODY_CONTAINER_CLASS = "372234A0-2A6C-4122-8047-E74DBA04F326"
INTERNAL = ("PrismMaterial", "Prism-", "BREP.", "ProteinAsset", "1_", "arrangementsContainer",
            "DesignConfiguration")


def parse_types(meta):
    from design_stream import Segment  # type table parser is shared
    seg = Segment.__new__(Segment)
    seg.meta = meta
    seg.types = []
    seg._parse_types()
    return seg.types


def utf16_strings(b):
    out = []
    p = 0
    while p + 4 < len(b):
        n = struct.unpack_from("<I", b, p)[0]
        if 2 <= n <= 128 and p + 4 + 2 * n <= len(b):
            raw = b[p + 4 : p + 4 + 2 * n]
            if all(raw[2 * i + 1] == 0 and 0x20 <= raw[2 * i] < 0x7F for i in range(n)):
                out.append(raw.decode("utf-16-le"))
                p += 4 + 2 * n
                continue
        p += 1
    return out


def select_bodies(recs):
    types = [sab.record_type(r) for r in recs]
    vals = lambda r: [(k, v) for k, v in r if k not in ("ident", "subident")][:-1]  # noqa: E731

    def tagged(i):
        a = vals(recs[i])[0][1]
        seen = set()
        while a >= 0 and a not in seen and a < len(recs):
            seen.add(a)
            if any(k == "str" and v == "Timestamp_attrib_def" for k, v in recs[a]):
                return True
            av = vals(recs[a])
            a = av[3][1] if len(av) > 3 and av[3][0] == "ref" else -1
        return False

    return types, tagged


def main():
    path = sys.argv[1]
    entries = dict(sab.f3d_entries(path))
    seg_dir = next(n[: -len("MetaStream.dat")] for n in entries
                   if n.endswith("/MetaStream.dat") and not n.startswith("Animation")
                   and ("FusionDesignSegmentType" in n or n.endswith("/Design1/MetaStream.dat")))
    meta, bulk = entries[seg_dir + "MetaStream.dat"], entries[seg_dir + "BulkStream.dat"]
    types = parse_types(meta)
    ids = lambda g: [i for t in types if t["guid"].upper() == g for i in t["ids"]]  # noqa: E731

    comps = {}
    for cid in ids(COMPONENT_CLASS):
        h = find_header(bulk, cid)
        name = next((s for s in utf16_strings(bulk[h : h + 0x800]) if not re.fullmatch(r"[0-9A-Fa-f-]{36}\$?", s)
                     and not s.startswith(INTERNAL)), "") if h is not None else ""
        comps[cid] = {"name": name, "blob": None}
    for bid in ids(BODY_CONTAINER_CLASS):
        h = find_header(bulk, bid)
        w = bulk[h : h + 0x800]
        owner = next((struct.unpack_from("<Q", w, p + 1)[0] for p in range(1, len(w) - 9)
                      if w[p] == 1 and struct.unpack_from("<Q", w, p + 1)[0] in comps), None)
        m = re.search(rb"B\x00R\x00E\x00P\x00\.\x00((?:[0-9a-f-]\x00){36})\.\x00s\x00m\x00b\x00(?!h\x00)", w)
        if owner is not None and m:
            comps[owner]["blob"] = m.group(1).decode("utf-16-le")

    blob_names = {re.search(r"BREP\.([0-9a-f-]{36})\.smb$", n).group(1): n for n in entries
                  if n.endswith(".smb") and not n.startswith("Animation")}
    selected_cache = {}
    placed = set()
    for oid in ids(OCCURRENCE_CLASS) + [None]:
        if oid is None:
            # Components with geometry but no decoded occurrence (e.g. the root in
            # single-component designs) are placed at the origin.
            rest = [cid for cid, c in comps.items() if c["blob"] and cid not in placed]
            if not rest:
                break
            o = {"component": rest[0], "identity": True, "matrix": None}
            comps_left = rest[1:]
            if comps_left:
                print(f"warning: {len(comps_left)} more component(s) without decoded occurrence")
        else:
            try:
                o = parse_occurrence(bulk, oid)
            except ValueError:
                o = None
            if not o or "error" in o:
                continue
        placed.add(o["component"])
        c = comps.get(o["component"], {})
        blob = c.get("blob")
        if blob not in selected_cache and blob:
            hdr, recs = sab.parse(entries[blob_names[blob]])
            types_, tagged = select_bodies(recs)
            n = hdr["counts"][0]
            lead = []
            for i in range(1, n):
                if types_[i] != "body":
                    break
                lead.append(i)
            top_tagged = [i for i in range(1, n) if types_[i] == "body" and tagged(i)]
            chosen = top_tagged if top_tagged else [f"{i}(if closed)" for i in lead]
            selected_cache[blob] = (chosen, types_.count("body"))
        m = o["matrix"]
        place = "identity" if o["identity"] else f"T=({m[3]*10:.3f}, {m[7]*10:.3f}, {m[11]*10:.3f}) mm"
        sel = selected_cache.get(blob)
        print(f"{c.get('name') or '?':16s} blob={blob[:8] if blob else '-':8s} {place:32s} "
              f"bodies={sel[0] if sel else []} of {sel[1] if sel else 0}")


if __name__ == "__main__":
    main()
