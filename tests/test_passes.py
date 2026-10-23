"""Synthetic checks for the GLB passes (no Godot, no USD assets needed): python -m pytest tests/"""
import os
import struct
import sys
import tempfile
import zlib

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gamebake import glb as G  # noqa: E402


def _cube(size, center=(0.0, 0.0, 0.0)):
    """An outward-facing closed cube, 12 triangles."""
    s = size / 2.0
    v = np.array([[x, y, z] for x in (-s, s) for y in (-s, s) for z in (-s, s)], np.float32) + np.array(center, np.float32)
    f = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1],
                  [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]], np.uint32)
    return v, f


def _grid(n, noise=0.0, seed=0):
    xs = np.linspace(0, 1, n + 1)
    v = np.array([[x, 0.0, z] for z in xs for x in xs], np.float32)
    if noise:
        v[:, 1] += np.random.default_rng(seed).normal(0, noise, len(v)).astype(np.float32)
    f = []
    for r in range(n):
        for c in range(n):
            a = r * (n + 1) + c
            f += [[a, a + n + 1, a + 1], [a + 1, a + n + 1, a + n + 2]]
    return v, np.array(f, np.uint32)


def _png(rgb):
    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    raw = b'\x00' + bytes(rgb)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')


def _write(path, meshes, images=()):
    """meshes: [(verts, faces, material index or None)]; images: PNG payloads, one material per image."""
    j = {'asset': {'version': '2.0'}, 'scenes': [{'nodes': list(range(len(meshes)))}], 'nodes': [], 'meshes': [],
         'accessors': [], 'bufferViews': [], 'buffers': []}
    b = bytearray()

    def view(data, target=None):
        while len(b) % 4:
            b.append(0)
        bv = {'buffer': 0, 'byteOffset': len(b), 'byteLength': len(data)}
        if target:
            bv['target'] = target
        b.extend(data)
        j['bufferViews'].append(bv)
        return len(j['bufferViews']) - 1

    for i, (v, f, mat) in enumerate(meshes):
        pv = view(v.tobytes(), 34962)
        j['accessors'].append({'bufferView': pv, 'componentType': 5126, 'count': len(v), 'type': 'VEC3',
                               'min': v.min(0).tolist(), 'max': v.max(0).tolist()})
        iv = view(f.ravel().tobytes(), 34963)
        j['accessors'].append({'bufferView': iv, 'componentType': 5125, 'count': f.size, 'type': 'SCALAR'})
        pr = {'attributes': {'POSITION': 2 * i}, 'indices': 2 * i + 1}
        if mat is not None:
            pr['material'] = mat
        j['meshes'].append({'primitives': [pr]})
        j['nodes'].append({'mesh': i})
    if images:
        j['images'] = [{'bufferView': view(p), 'mimeType': 'image/png'} for p in images]
        j['textures'] = [{'source': k} for k in range(len(images))]
        j['materials'] = [{'pbrMetallicRoughness': {'baseColorTexture': {'index': k}}} for k in range(len(images))]
    while len(b) % 4:
        b.append(0)
    j['buffers'] = [{'byteLength': len(b)}]
    G.write(path, j, bytes(b))


def test_cull_removes_an_enclosed_box():
    from gamebake.cull import cull
    with tempfile.TemporaryDirectory() as d:
        src, dst = os.path.join(d, 'a.glb'), os.path.join(d, 'b.glb')
        _write(src, [_cube(1.0) + (None,), _cube(0.3) + (None,)])
        st = cull(src, dst, ndirs=42, pitch_m=0.01)
        assert st['tris_in'] == 24 and st['tris_out'] == 12
        g = G.Glb.load(dst)
        counts = [g.accessor(m['primitives'][0]['indices']).size // 3 for m in g.json['meshes']]
        assert counts == [12, 0] or counts == [12]


def test_shape_flat_grid_is_clean_and_noise_is_crumpled():
    from gamebake.shape import measure
    with tempfile.TemporaryDirectory() as d:
        flat, noisy = os.path.join(d, 'flat.glb'), os.path.join(d, 'noisy.glb')
        _write(flat, [_grid(20) + (None,)])
        _write(noisy, [_grid(20, noise=0.05, seed=7) + (None,)])
        a, b = measure(flat), measure(noisy)
        assert a['crumple_pct'] == 0.0 and a['fold_pct'] == 0.0 and a['ok']
        assert b['crumple_pct'] > 10.0 and not b['ok']


def test_dedupe_shares_identical_images():
    from gamebake.dedupe import dedupe
    with tempfile.TemporaryDirectory() as d:
        src, dst = os.path.join(d, 'a.glb'), os.path.join(d, 'b.glb')
        red = _png([255, 0, 0])
        _write(src, [_cube(1.0) + (0,), _cube(1.0, (2, 0, 0)) + (1,)], images=[red, red])
        st = dedupe(src, dst)
        assert (st['images_in'], st['images_out'], st['textures_out']) == (2, 1, 1)
        g = G.Glb.load(dst)
        assert all(m['pbrMetallicRoughness']['baseColorTexture']['index'] == 0 for m in g.json['materials'])
