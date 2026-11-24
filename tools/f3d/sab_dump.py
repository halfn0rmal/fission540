#!/usr/bin/env python3
"""Tokenise Autodesk ShapeManager binary B-rep (.smb / .smbh, "ASM BinaryFile4").

Research tool for the Fission540 .f3d reader. Clean-room: derived only from
inspecting data files, never from Autodesk program code.

Usage:
    sab_dump.py FILE [--records N] [--stats]
    sab_dump.py --f3d DESIGN.f3d --stats     # all BREP blobs inside a .f3d
"""
import argparse
import collections
import io
import struct
import sys
import zipfile

MAGIC = b"ASM BinaryFile4"

# Token tags (shared with ACIS SAB).
FIXED = {
    0x02: ("char", 1),
    0x03: ("short", 2),
    0x04: ("long", 4),
    0x05: ("float", 4),
    0x06: ("double", 8),
    0x0C: ("ref", 4),
    0x13: ("pos", 24),
    0x14: ("vec", 24),
    0x15: ("enum", 4),
    0x16: ("vec2", 16),
}
STRINGS = {0x07: 1, 0x08: 2, 0x09: 4, 0x12: 4, 0x0D: 1, 0x0E: 1}
MARKERS = {0x0A: "true", 0x0B: "false", 0x0F: "{", 0x10: "}", 0x11: "#"}


class SabError(Exception):
    pass


def decode_value(tag, raw):
    if tag == 0x02:
        return raw[0]
    if tag == 0x03:
        return struct.unpack("<h", raw)[0]
    if tag in (0x04, 0x0C, 0x15):
        return struct.unpack("<i", raw)[0]
    if tag == 0x05:
        return struct.unpack("<f", raw)[0]
    if tag == 0x06:
        return struct.unpack("<d", raw)[0]
    if tag in (0x13, 0x14):
        return struct.unpack("<3d", raw)
    if tag == 0x16:
        return struct.unpack("<2d", raw)
    raise SabError(f"no decoder for tag {tag:#x}")


def tokens(buf, pos):
    n = len(buf)
    while pos < n:
        tag = buf[pos]
        start = pos
        pos += 1
        if tag in FIXED:
            name, size = FIXED[tag]
            yield start, name, decode_value(tag, buf[pos : pos + size])
            pos += size
        elif tag in STRINGS:
            width = STRINGS[tag]
            length = int.from_bytes(buf[pos : pos + width], "little")
            pos += width
            text = buf[pos : pos + length].decode("latin-1")
            pos += length
            kind = {0x0D: "ident", 0x0E: "subident"}.get(tag, "str")
            yield start, kind, text
        elif tag in MARKERS:
            yield start, "mark", MARKERS[tag]
        else:
            raise SabError(f"unknown tag {tag:#04x} at offset {start:#x}")


def parse(buf):
    """Return (header, records). Each record is a list of (kind, value) tokens."""
    if not buf.startswith(MAGIC):
        raise SabError("not an ASM BinaryFile4 blob")
    pos = len(MAGIC)
    version = struct.unpack_from("<q", buf, pos)[0]
    pos += 8
    counts = struct.unpack_from("<2i", buf, pos)
    pos += 8
    header = {"version": version, "counts": counts}
    records = []
    current = []
    preamble = []
    in_records = False
    for _, kind, value in tokens(buf, pos):
        if not in_records:
            if kind == "ident":
                in_records = True
            else:
                preamble.append(value)
                continue
        current.append((kind, value))
        if kind == "mark" and value == "#":
            records.append(current)
            current = []
    header["preamble"] = preamble
    if current:
        header["trailing"] = current
    return header, records


def record_type(record):
    """Full ACIS class name, e.g. 'cone-surface' from subident 'cone' + ident 'surface'."""
    parts = []
    for kind, value in record:
        if kind in ("subident", "ident"):
            parts.append(value)
            if kind == "ident":
                break
    return "-".join(parts)


def format_token(kind, value):
    if kind == "ref":
        return f"${value}"
    if kind == "double":
        return f"{value:.9g}"
    if kind in ("pos", "vec", "vec2"):
        return "(" + " ".join(f"{v:.9g}" for v in value) + ")"
    if kind == "mark":
        return value
    if kind in ("str", "ident", "subident"):
        return repr(value)
    return str(value)


ZIP_METHOD_ZSTD = 93  # newer Fusion versions compress entries with Zstandard


def read_entry(path, z, info):
    """Read one entry, handling Zstandard (method 93), which zipfile does not support."""
    if info.compress_type != ZIP_METHOD_ZSTD:
        return z.read(info)
    import zstandard  # pip install zstandard

    with open(path, "rb") as f:
        f.seek(info.header_offset)
        local = f.read(30)
        if local[:4] != b"PK\x03\x04":
            raise SabError(f"bad local header for {info.filename}")
        name_len, extra_len = struct.unpack_from("<HH", local, 26)
        f.seek(info.header_offset + 30 + name_len + extra_len)
        packed = f.read(info.compress_size)
    return zstandard.ZstdDecompressor().decompress(packed, max_output_size=info.file_size)


def f3d_entries(path, suffixes=None):
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            if suffixes and not info.filename.endswith(suffixes):
                continue
            yield info.filename, read_entry(path, z, info)


def blobs_from_f3d(path):
    yield from f3d_entries(path, (".smb", ".smbh"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?")
    ap.add_argument("--f3d")
    ap.add_argument("--records", type=int, default=0)
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    if args.f3d:
        sources = list(blobs_from_f3d(args.f3d))
    elif args.file:
        sources = [(args.file, open(args.file, "rb").read())]
    else:
        ap.error("give FILE or --f3d")

    totals = collections.Counter()
    failures = 0
    for name, buf in sources:
        try:
            header, records = parse(buf)
        except SabError as e:
            failures += 1
            print(f"{name}: FAILED {e}")
            continue
        types = collections.Counter(record_type(r) for r in records)
        totals.update(types)
        print(f"{name}: version={header['version']} counts={header['counts']} "
              f"records={len(records)} preamble={header['preamble']}")
        for i, rec in enumerate(records[: args.records]):
            print(f"  -{i} " + " ".join(format_token(k, v) for k, v in rec))
    if args.stats:
        print(f"\nblobs={len(sources)} failed={failures}")
        for t, n in totals.most_common():
            print(f"{n:7d}  {t}")


if __name__ == "__main__":
    sys.exit(main())
