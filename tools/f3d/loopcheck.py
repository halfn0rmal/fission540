#!/usr/bin/env python3
# Usage: python loopcheck.py sab_dump.py SAMPLES_DIR [types]  (research check, see docs/formats/f3d.md)
import sys, glob, math, collections, importlib.util
spec = importlib.util.spec_from_file_location("sab", sys.argv[1]); sab = importlib.util.module_from_spec(spec); spec.loader.exec_module(sab)
def vals(r): return [(k,v) for k,v in r if k not in ('ident','subident')][:-1]
res = collections.Counter(); tr = collections.Counter()
for f in sorted(glob.glob(sys.argv[2] + "/*.f3d")):
    for name, buf in sab.blobs_from_f3d(f):
        if name.endswith('.smbh'): continue
        h, recs = sab.parse(buf)
        T = [sab.record_type(r) for r in recs]
        def cends(ci):
            v = vals(recs[ci]); e = vals(recs[v[6][1]]); rev = v[7][1] == 'true'
            s, t = e[3][1], e[5][1]
            return (t, s) if rev else (s, t)
        for i, t in enumerate(T):
            if t == 'transform':
                v = vals(recs[i]); ident = v[2][1] == (1,0,0) and v[3][1] == (0,1,0) and v[4][1] == (0,0,1)
                tr['identity-rot' if ident else 'rotated'] += 1
                tr['scale=%g' % v[6][1]] += 1
            if t != 'loop': continue
            first = vals(recs[i])[4][1]; c = first; n = 0; ok = True
            while True:
                nxt = vals(recs[c])[3][1]
                if cends(c)[1] != cends(nxt)[0]: ok = False
                c = nxt; n += 1
                if c == first or n > 10000: break
            res['closed-chain-ok' if ok and c == first else 'BROKEN'] += 1
print(dict(res)); print(dict(tr))
