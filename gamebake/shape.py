"""Shape quality of a (simplified) triangle mesh: the crumple share and the fold share.

A decimated smooth form can come back CRUMPLED: neighbouring faces fold against each other at random, which reads as
ripple under a glossy material. A clean mesh keeps its sharp folds on designed feature LINES (a lip, a bolt circle, a
step). Per mesh:

- folds = interior edges whose dihedral angle exceeds 60 degrees (adjacency by welded position, quantised to 1e-5 of a
  unit; winding-aware, so a flipped patch reads 0 degrees, not 180);
- folds are joined into CHAINS through a shared vertex when the second continues the first: straight on (turn <= 10
  degrees) or a designed corner (a turn within 3 degrees of 45 or 90); folds in chains of >= 4 edges are features;
- crumple share = the remaining (loose) folds / all interior edge pairs;
- fold share = all folds / all interior edge pairs (a backstop: a corrugation chains perfectly but is still a fold field).

The asset value is the triangle-weighted mean over its mesh instances. Default gate: crumple <= 10 %, fold <= 20 %.
"""
import numpy as np

from . import glb as G

DIHEDRAL_DEG = 60.0
CHAIN_STRAIGHT_DEG = 10.0
CHAIN_CORNERS_DEG = (45.0, 90.0)
CHAIN_CORNER_TOL_DEG = 3.0
CHAIN_MIN_EDGES = 4
MAX_CRUMPLE = 0.10
MAX_FOLD = 0.20


class _UnionFind:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, i):
        r = i
        while self.p[r] != r:
            r = self.p[r]
        while self.p[i] != r:
            self.p[i], i = r, self.p[i]
        return r

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def _qround(x):
    return (np.sign(x) * np.floor(np.abs(x) * 1e5 + 0.5)).astype(np.int64)   # round half away from zero


def measure_soup(pos):
    """pos: (3*T, 3) corner positions (three per triangle). Returns {'tris', 'pairs', 'fold', 'crumple'}."""
    ntri = len(pos) // 3
    q = _qround(pos)
    _, wid = np.unique(q, axis=0, return_inverse=True)
    wid = wid.ravel()
    wpos = np.zeros((wid.max() + 1, 3))
    wpos[wid] = pos
    p = pos.reshape(ntri, 3, 3)
    nn = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    ln = np.linalg.norm(nn, axis=1)
    normals = np.where(ln[:, None] > 0, nn / np.maximum(ln, 1e-300)[:, None], 0.0)
    # every directed corner edge (t, e) in (t, e) order; degenerate welded edges are skipped
    c0 = wid.reshape(ntri, 3)
    c1 = np.roll(c0, -1, axis=1)
    a0 = c0.ravel()
    a1 = c1.ravel()
    tri = np.repeat(np.arange(ntri), 3)
    ok = a0 != a1
    a0, a1, tri = a0[ok], a1[ok], tri[ok]
    lo = np.minimum(a0, a1)
    hi = np.maximum(a0, a1)
    sgn = np.where(a0 == lo, 1, -1)
    order = np.lexsort((np.arange(len(lo)), hi, lo))   # group by (lo, hi), keeping the (t, e) order inside a group
    lo, hi, sgn, tri = lo[order], hi[order], sgn[order], tri[order]
    same = (lo[1:] == lo[:-1]) & (hi[1:] == hi[:-1])   # consecutive entries of one edge = one pair
    na = normals[tri[:-1][same]]
    nb = normals[tri[1:][same]] * np.where(sgn[:-1][same] == sgn[1:][same], -1.0, 1.0)[:, None]
    d = (na * nb).sum(1)
    n_pairs = int(same.sum())
    fold_pair = d < np.cos(np.radians(DIHEDRAL_DEG))
    n_fold = int(fold_pair.sum())
    fk = np.unique(np.c_[lo[:-1][same][fold_pair], hi[:-1][same][fold_pair]], axis=0) if n_fold else np.zeros((0, 2), np.int64)
    loose = _loose_folds(fk, wpos)
    return {'tris': ntri, 'pairs': n_pairs, 'fold': n_fold / max(n_pairs, 1), 'crumple': loose / max(n_pairs, 1)}


def _loose_folds(folds, wpos):
    nf = len(folds)
    if nf == 0:
        return 0
    dirs = wpos[folds[:, 1]] - wpos[folds[:, 0]]
    dirs /= np.maximum(np.linalg.norm(dirs, axis=1), 1e-300)[:, None]
    inc = {}
    for i, (a, b) in enumerate(folds.tolist()):
        inc.setdefault(a, []).append((i, 1.0))
        inc.setdefault(b, []).append((i, -1.0))
    uf = _UnionFind(nf)
    corners = np.array(CHAIN_CORNERS_DEG)
    for lst in inc.values():
        if len(lst) < 2:
            continue
        for x in range(len(lst)):
            di = dirs[lst[x][0]] * lst[x][1]   # pointing away from the vertex
            for y in range(x + 1, len(lst)):
                dj = dirs[lst[y][0]] * lst[y][1]
                turn = np.degrees(np.arccos(np.clip(np.dot(di, -dj), -1.0, 1.0)))   # 0 = straight on
                if turn <= CHAIN_STRAIGHT_DEG or np.any(np.abs(turn - corners) <= CHAIN_CORNER_TOL_DEG):
                    uf.union(lst[x][0], lst[y][0])
    roots = [uf.find(i) for i in range(nf)]
    size = {}
    for r in roots:
        size[r] = size.get(r, 0) + 1
    return sum(1 for r in roots if size[r] < CHAIN_MIN_EDGES)


def measure(path):
    """The triangle-weighted crumple and fold shares over every mesh instance of a GLB."""
    g = G.Glb.load(path)
    j = g.json
    tot = 0
    wc = wf = 0.0
    meshes = []
    for _ni, _m, mi in g.mesh_instances():
        corners = []
        for pr in j['meshes'][mi]['primitives']:
            if pr.get('mode', 4) != 4:
                continue
            p = g.accessor(pr['attributes']['POSITION']).astype(np.float64)
            idx = g.accessor(pr['indices']).ravel() if 'indices' in pr else np.arange(len(p))
            corners.append(p[idx])
        if not corners:
            continue
        r = measure_soup(np.concatenate(corners))
        meshes.append(dict(r, mesh=mi))
        tot += r['tris']
        wc += r['crumple'] * r['tris']
        wf += r['fold'] * r['tris']
    crumple = wc / max(tot, 1)
    fold = wf / max(tot, 1)
    return {'tris': tot, 'crumple_pct': 100 * crumple, 'fold_pct': 100 * fold, 'ok': crumple <= MAX_CRUMPLE and fold <= MAX_FOLD,
            'meshes': meshes}
