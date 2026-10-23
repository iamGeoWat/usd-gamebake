"""Hidden-geometry culling: drop every triangle that no view from outside the asset can see.

Orthographic Embree ray grids are cast from N directions on a Fibonacci sphere (trimesh + embreex); a triangle that is
never the first hit is hidden. Triangles smaller than the grid pitch that the grid missed get one TARGETED ray at their
own centroid per direction, which is exact per triangle. Transparent materials (alphaMode != OPAQUE, or a base colour
alpha < 1) never occlude and are never culled, so whatever sits behind glass survives.

Only index buffers change: each culled primitive gets a new index accessor; vertices, attributes, materials, images and
nodes are kept, and the file is compacted (unreferenced accessors and buffer views dropped).
"""
import time

import numpy as np

from . import glb as G


def _fibonacci(n):
    i = np.arange(n) + 0.5
    phi = np.arccos(1 - 2 * i / n)
    th = np.pi * (1 + 5 ** 0.5) * i
    return np.c_[np.cos(th) * np.sin(phi), np.sin(th) * np.sin(phi), np.cos(phi)]


def cull(src, dst, ndirs=162, pitch_m=0.0005, seed=3):
    """Cull src into dst. Returns a dict of statistics."""
    import trimesh
    from trimesh.ray.ray_pyembree import RayMeshIntersector

    t0 = time.time()
    g = G.Glb.load(src)
    j = g.json
    # every (node instance, primitive) in world space; a mesh used by several nodes is kept where ANY instance is seen
    verts, faces, tag = [], [], []
    off = 0
    for _ni, m, mi in g.mesh_instances():
        for k, pr in enumerate(j['meshes'][mi]['primitives']):
            if pr.get('mode', 4) != 4 or 'indices' not in pr:
                continue
            p = g.accessor(pr['attributes']['POSITION']).astype(float)
            idx = g.accessor(pr['indices']).reshape(-1, 3).astype(np.int64)
            verts.append((np.c_[p, np.ones(len(p))] @ m.T)[:, :3])
            faces.append(idx + off)
            off += len(p)
            mt = j['materials'][pr['material']] if 'material' in pr else {}
            base = mt.get('pbrMetallicRoughness', {}).get('baseColorFactor') or [1, 1, 1, 1]
            transparent = mt.get('alphaMode', 'OPAQUE') != 'OPAQUE' or base[3] < 1.0
            tag.append((mi, k, len(idx), transparent))
    if not verts:
        raise ValueError('%s: no indexed triangle primitives' % src)
    vw = np.concatenate(verts)
    fw = np.concatenate(faces)
    transp = np.concatenate([np.full(n, t) for (_, _, n, t) in tag])
    mesh_all = trimesh.Trimesh(vw, fw, process=False)
    area = mesh_all.area_faces
    opaque = np.where(~transp)[0]
    occluder = trimesh.Trimesh(vw, fw[opaque], process=False)
    c = vw.mean(0)
    rad = np.linalg.norm(vw - c, axis=1).max() * 1.02
    res = int(np.clip(2 * rad / pitch_m, 400, 2400))
    pitch = 2 * rad / res
    rmi = RayMeshIntersector(occluder)
    seen = np.zeros(len(fw), bool)
    rng = np.random.default_rng(seed)
    dirs = _fibonacci(ndirs)
    grid = (np.arange(res) + 0.5) / res * 2 - 1
    gu, gv = np.meshgrid(grid, grid)
    gu = gu.ravel()
    gv = gv.ravel()
    for d in dirs:
        u = np.cross(d, [0, 0, 1] if abs(d[2]) < 0.9 else [1, 0, 0])
        u /= np.linalg.norm(u)
        v = np.cross(d, u)
        jit = (rng.random((len(gu), 2)) - 0.5) * (2.0 / res)
        org = c - d * rad * 1.5 + np.outer((gu + jit[:, 0]) * rad, u) + np.outer((gv + jit[:, 1]) * rad, v)
        hit = rmi.intersects_first(org, np.tile(d, (len(org), 1)))
        seen[opaque[hit[hit >= 0]]] = True
    # targeted pass: a sub-pitch triangle the grid never hit gets one ray AT ITS OWN CENTROID per direction; it is visible
    # when that ray's first hit is itself
    small = np.where(~seen & (area < pitch * pitch) & ~transp)[0]
    if len(small):
        cen = mesh_all.triangles_center[small]
        alive = np.ones(len(small), bool)
        for d in dirs:
            idx = np.where(alive)[0]
            if len(idx) == 0:
                break
            hit = rmi.intersects_first(cen[idx] - d * rad * 3.0, np.tile(d, (len(idx), 1)))
            hit_g = np.where(hit >= 0, opaque[np.maximum(hit, 0)], -1)
            ok = hit_g == small[idx]
            seen[small[idx[ok]]] = True
            alive[idx[ok]] = False
    keep_w = seen | transp
    keep = {}
    s = 0
    for (mi, k, n, _t) in tag:
        kk = keep.setdefault((mi, k), np.zeros(n, bool))
        kk |= keep_w[s:s + n]
        s += n
    new_bin = bytearray(g.bin)
    dropped = total = 0
    for (mi, k), kk in keep.items():
        pr = j['meshes'][mi]['primitives'][k]
        idx = g.accessor(pr['indices']).reshape(-1, 3)
        total += len(idx)
        dropped += int((~kk).sum())
        if kk.all():
            continue
        ik = idx[kk].astype(np.uint32).ravel()
        while len(new_bin) % 4:
            new_bin.append(0)
        j['bufferViews'].append({'buffer': 0, 'byteOffset': len(new_bin), 'byteLength': ik.nbytes, 'target': 34963})
        new_bin += ik.tobytes()
        j['accessors'].append({'bufferView': len(j['bufferViews']) - 1, 'componentType': 5125, 'count': int(len(ik)), 'type': 'SCALAR'})
        pr['indices'] = len(j['accessors']) - 1
    out = G.compact(j, bytes(new_bin))
    size = G.write(dst, j, out)
    return {'file': src, 'tris_in': total, 'tris_out': total - dropped, 'hidden_area_pct': 100 * area[~keep_w].sum() / area.sum(),
            'pitch_mm': 1000 * pitch, 'dirs': ndirs, 'mb_in': g.size / 1e6, 'mb_out': size / 1e6, 'seconds': time.time() - t0}
