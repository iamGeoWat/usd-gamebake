"""Texture fidelity of a simplified mesh against its full-resolution source.

UV smear: area-weighted samples of the full mesh (position + uv) are matched to the EXACT closest point on the
simplified mesh's triangles of the same material; the error is the uv distance at that point, in texels of the
material's base colour texture (wrap-aware: a whole tile away is the same texel). At a UV seam, where several triangles
lie within 0.2 mm of the closest point, the smallest error counts. Reported: the area share with error > 4 texels.

Shell penetration: for pairs of surfaces (A over B) where at least 20 % of A's area lies within 10 mm of B in the full
mesh and B is inside A, the signed gap from A's samples to B's closest point along A's normal. Penetration = the share
with gap < -0.05 mm; reported as simplified minus full (the worst pair).

Comparing a mesh with itself reads ~0 by construction, so both numbers are increases a simplifier caused.
"""
import struct

import numpy as np

from . import glb as G


def _load(path):
    g = G.Glb.load(path)
    j = g.json

    def tex_size(mi):
        try:
            t = j['materials'][mi]['pbrMetallicRoughness']['baseColorTexture']['index']
            d = g.buffer_view_bytes(j['images'][j['textures'][t]['source']]['bufferView'])[:32]
            return struct.unpack('>II', d[16:24]) if d[:8] == b'\x89PNG\r\n\x1a\n' else (1024, 1024)
        except (KeyError, IndexError, TypeError):
            return None

    per = {}
    for _ni, m, mi in g.mesh_instances():
        for pr in j['meshes'][mi]['primitives']:
            at = pr['attributes']
            if 'TEXCOORD_0' not in at or pr.get('mode', 4) != 4:
                continue
            p = g.accessor(at['POSITION']).astype(np.float64)
            uv = g.accessor(at['TEXCOORD_0']).astype(np.float64)
            idx = g.accessor(pr['indices']).reshape(-1, 3).astype(np.int64) if 'indices' in pr else np.arange(len(p)).reshape(-1, 3)
            p = (np.c_[p, np.ones(len(p))] @ m.T)[:, :3]
            mat = pr.get('material', -1)
            d = per.setdefault(str(mat), {'tri': [], 'uv': [], 'tex': tex_size(mat) if mat >= 0 else None})
            d['tri'].append(p[idx])
            d['uv'].append(uv[idx])
    out = {}
    for k, d in per.items():
        t = np.concatenate(d['tri'])
        u = np.concatenate(d['uv'])
        fn = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        ar = 0.5 * np.linalg.norm(fn, axis=1)
        keep = ar > 1e-14
        out[k] = {'T': t[keep], 'U': u[keep], 'A': ar[keep], 'N': fn[keep] / (2 * ar[keep, None]), 'tex': d['tex']}
    return out


def _sample(m, n, rng):
    k = rng.choice(len(m['T']), size=n, p=m['A'] / m['A'].sum())
    a = rng.random(n)
    b = rng.random(n)
    f = a + b > 1
    a[f] = 1 - a[f]
    b[f] = 1 - b[f]
    c = 1 - a - b
    t = m['T'][k]
    u = m['U'][k]
    return (t[:, 0] * c[:, None] + t[:, 1] * a[:, None] + t[:, 2] * b[:, None],
            u[:, 0] * c[:, None] + u[:, 1] * a[:, None] + u[:, 2] * b[:, None], m['N'][k], k)


def _closest_on_tris(p, t):
    """p (N,3), t (N,K,3,3) -> squared distance (N,K), barycentrics (N,K,3): the interior projection or the closest edge point."""
    a, b, c = t[..., 0, :], t[..., 1, :], t[..., 2, :]
    x = p[:, None, :]
    v0 = b - a
    v1 = c - a
    v2 = x - a
    d00 = (v0 * v0).sum(-1)
    d01 = (v0 * v1).sum(-1)
    d11 = (v1 * v1).sum(-1)
    d20 = (v2 * v0).sum(-1)
    d21 = (v2 * v1).sum(-1)
    den = d00 * d11 - d01 * d01
    ok = den > 1e-24
    den = np.where(ok, den, 1.0)
    v = (d11 * d20 - d01 * d21) / den
    w = (d00 * d21 - d01 * d20) / den
    u = 1 - v - w
    inside = ok & (u >= 0) & (v >= 0) & (w >= 0)
    q = u[..., None] * a + v[..., None] * b + w[..., None] * c
    best = np.where(inside, ((x - q) ** 2).sum(-1), np.inf)
    bary = np.stack([u, v, w], -1) * inside[..., None]
    for (i, j, e0, e1) in ((0, 1, a, b), (1, 2, b, c), (2, 0, c, a)):
        e = e1 - e0
        ee = np.maximum((e * e).sum(-1), 1e-30)
        s = np.clip(((x - e0) * e).sum(-1) / ee, 0, 1)
        qe = e0 + s[..., None] * e
        de = ((x - qe) ** 2).sum(-1)
        better = de < best
        be = np.zeros(bary.shape)
        be[..., i] = 1 - s
        be[..., j] = s
        best = np.where(better, de, best)
        bary = np.where(better[..., None], be, bary)
    return best, bary


class _Surface:
    # candidates = triangles of the k nearest dense SAMPLES (big triangles: the closest point is interior) UNION triangles
    # of the k nearest mesh VERTICES (slivers too small to draw a sample); the exact test then picks the closest
    def __init__(self, m, rng, n):
        from scipy.spatial import cKDTree
        self.m = m
        pts, _, _, tri = _sample(m, n, rng)
        self.tree = cKDTree(pts)
        self.tri = tri
        self.vtree = cKDTree(m['T'].reshape(-1, 3))
        self.vtri = np.repeat(np.arange(len(m['T'])), 3)
        self.lo = m['T'].reshape(-1, 3).min(0)
        self.hi = m['T'].reshape(-1, 3).max(0)

    def query(self, p, k=8):
        _, i1 = self.tree.query(p, k=k)
        _, i2 = self.vtree.query(p, k=min(3 * k, len(self.vtri)))   # corners repeat once per incident triangle
        cand = np.concatenate([self.tri[i1].reshape(len(p), -1), self.vtri[i2].reshape(len(p), -1)], 1)
        d2, bary = _closest_on_tris(p, self.m['T'][cand])
        return d2, bary, cand


def fidelity(full, simplified, n=60000, seed=7):
    """Returns {'uv_smear_pct', 'penetration_increase_pct', 'materials': [...], 'shells': [...]}."""
    rng = np.random.default_rng(seed)
    fa_all = _load(full)
    fb_all = _load(simplified)
    tot = bad = 0.0
    rows = []
    surf_b = {k: _Surface(fb_all[k], rng, 4 * n) for k in fb_all}
    for key, fa in fa_all.items():
        if key not in fb_all:
            continue
        p, uv, _, _ = _sample(fa, n, rng)
        tw, th = fa['tex'] or (1024, 1024)
        d2, bary, cand = surf_b[key].query(p)
        uvq = (bary[..., None] * fb_all[key]['U'][cand]).sum(-2)
        du = uvq - uv[:, None, :]
        du -= np.round(du)
        err = np.sqrt(((du * np.array([tw, th])) ** 2).sum(-1))
        dmin = np.sqrt(d2.min(1, keepdims=True))
        near = np.sqrt(d2) <= dmin + 2e-4
        e = np.where(near, err, np.inf).min(1)
        s4 = float((e > 4).mean())
        ar = fa['A'].sum()
        tot += ar
        bad += s4 * ar
        rows.append({'material': key, 'area_m2': float(ar), 'smear_pct': 100 * s4, 'p95_px': float(np.percentile(e, 95))})
    surf_a = {k: _Surface(fa_all[k], rng, 4 * n) for k in fa_all}
    worst = 0.0
    shells = []
    for a in fa_all:
        for b in fa_all:
            if a == b or a not in fb_all or b not in fb_all:
                continue
            if np.any(surf_a[a].lo > surf_a[b].hi + 0.01) or np.any(surf_a[b].lo > surf_a[a].hi + 0.01):
                continue
            ps, _, _, _ = _sample(fa_all[a], 3000, rng)
            if (surf_a[b].tree.query(ps)[0] < 0.01).mean() < 0.15:
                continue
            pa, _, na, _ = _sample(fa_all[a], n, rng)
            d2, bary, cand = surf_a[b].query(pa)
            i = d2.argmin(1)
            r = np.arange(len(pa))
            d = np.sqrt(d2[r, i])
            q = (bary[r, i][..., None] * fa_all[b]['T'][cand[r, i]]).sum(-2)
            m0 = d < 0.01
            if m0.mean() < 0.2:
                continue
            g0 = ((pa - q) * na).sum(1)
            if np.median(g0[m0]) < 0:
                continue
            pb, _, nb, _ = _sample(fb_all[a], n, rng)
            d2, bary, cand = surf_b[b].query(pb)
            i = d2.argmin(1)
            r = np.arange(len(pb))
            d = np.sqrt(d2[r, i])
            q = (bary[r, i][..., None] * fb_all[b]['T'][cand[r, i]]).sum(-2)
            m1 = d < 0.01
            g1 = ((pb - q) * nb).sum(1)
            p0 = float((g0[m0] < -5e-5).mean())
            p1 = float((g1[m1] < -5e-5).mean()) if m1.any() else 0.0
            shells.append({'over': a, 'under': b, 'gap_p10_mm': 1000 * float(np.percentile(g0[m0], 10)), 'full_pct': 100 * p0, 'simplified_pct': 100 * p1})
            worst = max(worst, p1 - p0)
    return {'uv_smear_pct': 100 * bad / max(tot, 1e-12), 'penetration_increase_pct': 100 * worst, 'materials': rows, 'shells': shells}
