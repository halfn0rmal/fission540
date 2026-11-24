#!/usr/bin/env python3
# Usage: python geomcheck.py sab_dump.py SAMPLES_DIR [types]  (research check, see docs/formats/f3d.md)
import sys, glob, math, collections, importlib.util
spec = importlib.util.spec_from_file_location("sab", sys.argv[1]); sab = importlib.util.module_from_spec(spec); spec.loader.exec_module(sab)
def sub(a,b): return [a[i]-b[i] for i in range(3)]
def add(a,b): return [a[i]+b[i] for i in range(3)]
def mul(a,s): return [x*s for x in a]
def cross(a,b): return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
def norm(a): return math.sqrt(sum(x*x for x in a))
def vals(r): return [(k,v) for k,v in r if k not in ('ident','subident')][:-1]
def evalc(rec, t):
    typ = sab.record_type(rec); v = vals(rec)
    if typ == 'straight-curve':
        root, d = v[3][1], v[4][1]
        return add(root, mul(d, t))
    if typ == 'ellipse-curve':
        c, n, maj, ratio = v[3][1], v[4][1], v[5][1], v[6][1]
        minor = mul(cross(n, maj), ratio / norm(n))
        return add(c, add(mul(maj, math.cos(t)), mul(minor, math.sin(t))))
    return None
res = collections.Counter(); worst = {}
for f in sorted(glob.glob(sys.argv[2] + "/*.f3d")):
    for name, buf in sab.blobs_from_f3d(f):
        if name.endswith('.smbh'): continue
        h, recs = sab.parse(buf)
        for r in recs:
            if sab.record_type(r) != 'edge': continue
            v = vals(r)
            sv, sp, ev, ep, cv, rev = v[3][1], v[4][1], v[5][1], v[6][1], v[8][1], v[9][1] == 'true'
            crv = recs[cv]; typ = sab.record_type(crv)
            if typ not in ('straight-curve', 'ellipse-curve'): continue
            P = lambda vi: vals(recs[vals(recs[vi])[5][1]])[3][1]
            ps, pe = P(sv), P(ev)
            for mode, (a, b) in {'as-is': (sp, ep), 'negated': (-sp, -ep)}.items():
                ca, cb = evalc(crv, a), evalc(crv, b)
                err = max(norm(sub(ca, ps)), norm(sub(cb, pe)))
                key = (typ, 'rev' if rev else 'fwd', mode)
                res[key + ('ok' if err < 1e-6 else 'BAD',)] += 1
for k, n in sorted(res.items()): print(n, k)
