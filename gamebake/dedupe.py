"""Texture dedupe: Godot's GLTFDocument writes one image payload per material (a 48-image file can hold 4 unique ones).

Keeps the first copy of each identical payload, points every texture at it, collapses identical textures, and compacts
the file. Geometry is untouched.
"""
import hashlib
import json

from . import glb as G

TEXTURE_KEYS = ('baseColorTexture', 'metallicRoughnessTexture', 'normalTexture', 'occlusionTexture', 'emissiveTexture')


def dedupe(src, dst):
    g = G.Glb.load(src)
    j = g.json
    imgs = j.get('images', [])
    first, img_map, keep_imgs = {}, {}, []
    for i, im in enumerate(imgs):
        if 'bufferView' in im:
            key = (im.get('mimeType'), hashlib.sha256(g.buffer_view_bytes(im['bufferView'])).hexdigest())
        else:
            key = ('uri', im.get('uri'))
        if key not in first:
            first[key] = len(keep_imgs)
            keep_imgs.append(im)
        img_map[i] = first[key]
    for t in j.get('textures', []):
        if 'source' in t:
            t['source'] = img_map[t['source']]
        for ext in t.get('extensions', {}).values():
            if isinstance(ext, dict) and 'source' in ext:
                ext['source'] = img_map[ext['source']]
    tex_first, tex_map, keep_tex = {}, {}, []
    for i, t in enumerate(j.get('textures', [])):
        key = json.dumps(t, sort_keys=True)
        if key not in tex_first:
            tex_first[key] = len(keep_tex)
            keep_tex.append(t)
        tex_map[i] = tex_first[key]

    def remap(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if (k in TEXTURE_KEYS or k.endswith('Texture')) and isinstance(v, dict) and 'index' in v:
                    v['index'] = tex_map[v['index']]
                remap(v)
        elif isinstance(o, list):
            for v in o:
                remap(v)

    if 'textures' in j:
        remap(j.get('materials', []))
        j['textures'] = keep_tex
    j['images'] = keep_imgs
    out = G.compact(j, g.bin)
    size = G.write(dst, j, out)
    return {'file': src, 'images_in': len(imgs), 'images_out': len(keep_imgs), 'textures_in': len(tex_map),
            'textures_out': len(keep_tex), 'mb_in': g.size / 1e6, 'mb_out': size / 1e6}
