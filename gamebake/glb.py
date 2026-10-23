"""Minimal binary glTF 2.0 (GLB) reading and writing, shared by the passes.

Only what the passes need: the JSON chunk, the BIN chunk, typed accessor reads, node transforms, and a compaction
step that drops unreferenced accessors / buffer views and repacks the BIN chunk 4-byte aligned.
"""
import json
import struct

import numpy as np

COMPONENT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
NCOMP = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT2': 4, 'MAT3': 9, 'MAT4': 16}


class Glb:
    def __init__(self, data):
        if data[:4] != b'glTF':
            raise ValueError('not a GLB file')
        jl = struct.unpack('<I', data[12:16])[0]
        self.json = json.loads(data[20:20 + jl])
        if len(data) > 28 + jl:
            bl = struct.unpack('<I', data[20 + jl:24 + jl])[0]
            self.bin = data[28 + jl:28 + jl + bl]
        else:
            self.bin = b''
        self.size = len(data)

    @classmethod
    def load(cls, path):
        with open(path, 'rb') as f:
            return cls(f.read())

    def accessor(self, i):
        """Accessor i as an (count, ncomp) array of its component type (strided views are copied out)."""
        a = self.json['accessors'][i]
        bv = self.json['bufferViews'][a['bufferView']]
        dt = np.dtype(COMPONENT[a['componentType']])
        n = NCOMP[a['type']]
        off = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
        stride = bv.get('byteStride', 0) or dt.itemsize * n
        raw = np.frombuffer(self.bin, np.uint8, stride * (a['count'] - 1) + dt.itemsize * n, off)
        out = np.lib.stride_tricks.as_strided(raw, (a['count'], dt.itemsize * n), (stride, 1)).copy()
        return out.view(dt).reshape(a['count'], n)

    def buffer_view_bytes(self, i):
        bv = self.json['bufferViews'][i]
        o = bv.get('byteOffset', 0)
        return self.bin[o:o + bv['byteLength']]

    def mesh_instances(self):
        """Yield (node index, 4x4 world matrix, mesh index) for every node with a mesh in the default scene."""
        j = self.json

        def walk(ni, parent):
            nd = j['nodes'][ni]
            m = parent @ node_matrix(nd)
            if 'mesh' in nd:
                yield ni, m, nd['mesh']
            for c in nd.get('children', []):
                yield from walk(c, m)

        for r in j['scenes'][j.get('scene', 0)]['nodes']:
            yield from walk(r, np.eye(4))


def node_matrix(nd):
    if 'matrix' in nd:
        return np.array(nd['matrix'], float).reshape(4, 4).T
    t = np.array(nd.get('translation', [0, 0, 0]))
    x, y, z, w = nd.get('rotation', [0, 0, 0, 1])
    s = np.array(nd.get('scale', [1, 1, 1]))
    r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    m = np.eye(4)
    m[:3, :3] = r * s
    m[:3, 3] = t
    return m


def _referenced_accessors(j):
    refs = set()
    for m in j.get('meshes', []):
        for pr in m['primitives']:
            refs |= set(pr['attributes'].values())
            if 'indices' in pr:
                refs.add(pr['indices'])
            for t in pr.get('targets', []):
                refs |= set(t.values())
    for s in j.get('skins', []):
        if 'inverseBindMatrices' in s:
            refs.add(s['inverseBindMatrices'])
    for an in j.get('animations', []):
        for sm in an.get('samplers', []):
            refs.add(sm['input'])
            refs.add(sm['output'])
    return refs


def compact(j, binb):
    """Drop accessors nothing references and buffer views nothing uses, repack the BIN chunk (4-byte aligned) and
    remap every index. Mutates j; returns the new BIN bytes."""
    refs = sorted(_referenced_accessors(j))
    acc_map = {old: new for new, old in enumerate(refs)}
    j['accessors'] = [j['accessors'][i] for i in refs]

    def remap_acc(o):
        return acc_map[o]

    for m in j.get('meshes', []):
        for pr in m['primitives']:
            pr['attributes'] = {k: remap_acc(v) for k, v in pr['attributes'].items()}
            if 'indices' in pr:
                pr['indices'] = remap_acc(pr['indices'])
            if 'targets' in pr:
                pr['targets'] = [{k: remap_acc(v) for k, v in t.items()} for t in pr['targets']]
    for s in j.get('skins', []):
        if 'inverseBindMatrices' in s:
            s['inverseBindMatrices'] = remap_acc(s['inverseBindMatrices'])
    for an in j.get('animations', []):
        for sm in an.get('samplers', []):
            sm['input'] = remap_acc(sm['input'])
            sm['output'] = remap_acc(sm['output'])

    used = set()
    for a in j['accessors']:
        if 'bufferView' in a:
            used.add(a['bufferView'])
        sp = a.get('sparse')
        if sp:
            used.add(sp['indices']['bufferView'])
            used.add(sp['values']['bufferView'])
    for im in j.get('images', []):
        if 'bufferView' in im:
            used.add(im['bufferView'])
    bv_map = {}
    new_bvs = []
    out = bytearray()
    for i, bv in enumerate(j.get('bufferViews', [])):
        if i not in used:
            continue
        o = bv.get('byteOffset', 0)
        data = binb[o:o + bv['byteLength']]
        while len(out) % 4:
            out.append(0)
        nb = dict(bv)
        nb['byteOffset'] = len(out)
        nb['buffer'] = 0
        out += data
        bv_map[i] = len(new_bvs)
        new_bvs.append(nb)
    while len(out) % 4:
        out.append(0)
    for a in j['accessors']:
        if 'bufferView' in a:
            a['bufferView'] = bv_map[a['bufferView']]
        sp = a.get('sparse')
        if sp:
            sp['indices']['bufferView'] = bv_map[sp['indices']['bufferView']]
            sp['values']['bufferView'] = bv_map[sp['values']['bufferView']]
    for im in j.get('images', []):
        if 'bufferView' in im:
            im['bufferView'] = bv_map[im['bufferView']]
    j['bufferViews'] = new_bvs
    j['buffers'] = [{'byteLength': len(out)}]
    return bytes(out)


def write(path, j, binb):
    js = json.dumps(j, separators=(',', ':')).encode()
    js += b' ' * ((4 - len(js) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(binb)
    with open(path, 'wb') as f:
        f.write(b'glTF' + struct.pack('<II', 2, total))
        f.write(struct.pack('<I', len(js)) + b'JSON' + js)
        f.write(struct.pack('<I', len(binb)) + b'BIN\x00' + binb)
    return total
