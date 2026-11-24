#!/usr/bin/env python3
"""Decode the object directory of a Fusion design segment (MetaStream.dat + BulkStream.dat).

Research tool for the Fission540 .f3d reader. Clean-room: derived only from data files.

MetaStream holds a type table (module name + type GUIDs + the u64 ids of every object of
that type) and an index of (u64 object id, u64 offset into BulkStream). See docs/formats/f3d.md.

Usage:
    design_stream.py SEGMENT_DIR types                # list types with object counts
    design_stream.py SEGMENT_DIR objects TYPE_GUID    # dump objects of a type
    design_stream.py SEGMENT_DIR find TEXT            # which object/type contains TEXT (utf-16)
    design_stream.py SEGMENT_DIR obj ID               # dump one object (hex id or decimal)
"""
import re
import struct
import sys
from pathlib import Path

GUID_RE = re.compile(rb"\$\x00\x00\x00([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})")


class Segment:
    def __init__(self, seg_dir):
        seg_dir = Path(seg_dir)
        self.meta = (seg_dir / "MetaStream.dat").read_bytes()
        self.bulk = (seg_dir / "BulkStream.dat").read_bytes()
        self.types = []  # dicts: module, guid, guid2, ids, offset
        self.index = {}  # object id -> bulk offset
        self._parse_types()
        self._parse_index()
        self.type_of = {}
        for t in self.types:
            for i in t["ids"]:
                self.type_of[i] = t
        offs = sorted(set(self.index.values()))
        self.next_off = {o: (offs[k + 1] if k + 1 < len(offs) else len(self.bulk)) for k, o in enumerate(offs)}

    def _parse_types(self):
        m = self.meta
        # Entry: u32 36 GUID, u32 36 GUID2, u32 ?, u32 n module, u32 count, count * u64 ids
        for g in GUID_RE.finditer(m):
            p = g.end()
            g2 = GUID_RE.match(m, p)
            if not g2:
                continue
            p = g2.end()
            try:
                flag = struct.unpack_from("<I", m, p)[0]
                nlen = struct.unpack_from("<I", m, p + 4)[0]
                if not (1 <= nlen <= 64):
                    continue
                module = m[p + 8 : p + 8 + nlen].decode("ascii")
                if not module.isidentifier():
                    continue
                q = p + 8 + nlen
                count = struct.unpack_from("<I", m, q)[0]
                if count > 100000:
                    continue
                ids = list(struct.unpack_from(f"<{count}Q", m, q + 4))
            except (struct.error, UnicodeDecodeError):
                continue
            self.types.append(dict(guid=g.group(1).decode(), guid2=g2.group(1).decode(),
                                   flag=flag, module=module, ids=ids, offset=g.start()))

    def _parse_index(self):
        # Trailing table of (u64 bulk offset, u64 object id) pairs, both strictly increasing.
        # Its alignment relative to the end of file varies, so take the longest valid run.
        m = self.meta
        best = (0, 0, 0)
        for align in range(16):
            pos = len(m) - 16 - align
            run = 0
            prev = None
            while pos >= 0:
                off, oid = struct.unpack_from("<QQ", m, pos)
                if off > len(self.bulk) or (prev and not (off < prev[0] and oid < prev[1])):
                    break
                prev = (off, oid)
                run += 1
                pos -= 16
            if run > best[1]:
                best = (align, run, pos + 16)
        _, run, start = best
        # The id stored next to an offset belongs to the previous object, so take the id
        # from each object's own header instead: u32 n, n ASCII digits (class tag), u64 id.
        self.tags = {}
        for k in range(run):
            off, _ = struct.unpack_from("<QQ", m, start + 16 * k)
            n = struct.unpack_from("<I", self.bulk, off)[0]
            if n > 16:
                continue
            tag = self.bulk[off + 4 : off + 4 + n].decode("ascii", "replace")
            oid = struct.unpack_from("<Q", self.bulk, off + 4 + n)[0]
            self.index[oid] = off
            self.tags[oid] = tag
        self.index_start = start

    def object_bytes(self, oid):
        off = self.index[oid]
        return self.bulk[off : self.next_off[off]]


def utf16_strings(b):
    return [s.decode("utf-16-le") for s in re.findall(rb"(?:[\x20-\x7e]\x00){3,}", b)]


def main():
    seg = Segment(sys.argv[1])
    cmd = sys.argv[2] if len(sys.argv) > 2 else "types"
    if cmd == "types":
        print(f"types={len(seg.types)} indexed objects={len(seg.index)}")
        for t in seg.types:
            sample = t["ids"][0] if t["ids"] else None
            strs = utf16_strings(seg.object_bytes(sample))[:4] if sample in seg.index else []
            print(f"{t['module']:16s} {t['guid']} n={len(t['ids']):4d} sample={strs}")
    elif cmd == "find":
        needle = sys.argv[3].encode("utf-16-le")
        for oid, off in sorted(seg.index.items(), key=lambda x: x[1]):
            if needle in seg.object_bytes(oid):
                t = seg.type_of.get(oid, {})
                print(f"id={oid:#x} off={off:#x} size={seg.next_off[off]-off} type={t.get('module')} {t.get('guid')}")
    elif cmd == "objects":
        t = next(t for t in seg.types if t["guid"].lower() == sys.argv[3].lower())
        for oid in t["ids"]:
            b = seg.object_bytes(oid) if oid in seg.index else b""
            print(f"id={oid:#x} size={len(b)} {utf16_strings(b)[:6]}")
    elif cmd == "obj":
        oid = int(sys.argv[3], 0)
        b = seg.object_bytes(oid)
        t = seg.type_of.get(oid, {})
        print(f"id={oid:#x} off={seg.index[oid]:#x} size={len(b)} type={t.get('module')} {t.get('guid')}")
        for i in range(0, len(b), 16):
            chunk = b[i : i + 16]
            print(f"  {i:04x}: {chunk.hex(' ')}")


if __name__ == "__main__":
    main()
