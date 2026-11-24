#!/usr/bin/env python3
# Usage: python layout.py sab_dump.py SAMPLES_DIR [types]  (research check, see docs/formats/f3d.md)
import sys, glob, collections, importlib.util
spec = importlib.util.spec_from_file_location("sab", sys.argv[1]); sab = importlib.util.module_from_spec(spec); spec.loader.exec_module(sab)
types = sys.argv[3].split(',')
slots = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
lens = collections.defaultdict(collections.Counter)
for f in sorted(glob.glob(sys.argv[2] + "/*.f3d")):
    for name, buf in sab.blobs_from_f3d(f):
        h, recs = sab.parse(buf)
        rtypes = [sab.record_type(r) for r in recs]
        for r, t in zip(recs, rtypes):
            if t not in types: continue
            body = [(k, v) for k, v in r if k not in ('ident', 'subident')][:-1]
            lens[t][len(body)] += 1
            for i, (k, v) in enumerate(body):
                if k == 'ref':
                    slots[t][i]['null' if v < 0 else (rtypes[v] if v < len(rtypes) else 'OOR')] += 1
                else:
                    slots[t][i][k + ('=' + str(v) if k in ('mark', 'long', 'enum') and isinstance(v,(int,str)) else '')] += 1
for t in types:
    print(f"== {t}  token-counts={dict(lens[t])}")
    for i in sorted(slots[t]):
        print(f"   [{i}]", dict(slots[t][i].most_common(6)))
