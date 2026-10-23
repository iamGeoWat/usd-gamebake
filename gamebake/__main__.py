"""Command line: python -m gamebake <command> ...  (see README.md)."""
import argparse
import json
import os
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog='gamebake', description='OpenUSD assets -> game-ready glTF through Godot.')
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('bake', help='USD -> simplified, gated, hidden-culled GLB')
    b.add_argument('usd', nargs='+')
    b.add_argument('--project', required=True, help='the tools project (a copy of godot/project with the extension in bin/)')
    b.add_argument('--out', required=True)
    b.add_argument('--godot', default=os.environ.get('GODOT', 'godot'), help='Godot editor binary (default: $GODOT or godot)')
    b.add_argument('--ratios', default='1,0.5,0.25,0.12', help='simplify ladder; the first is the full-resolution reference')
    b.add_argument('--shell-lock', type=float, default=0.003, help='metres; triangles this close to another surface stay as authored')
    b.add_argument('--max-texture', type=int, default=1024)
    b.add_argument('--samples', type=int, default=60000, help='texture-fidelity samples per material')
    b.add_argument('--no-cull', action='store_true')
    c = sub.add_parser('cull', help='remove triangles no outside view can see')
    c.add_argument('src')
    c.add_argument('dst')
    c.add_argument('--dirs', type=int, default=162)
    c.add_argument('--pitch', type=float, default=0.0005, help='ray grid pitch in metres')
    d = sub.add_parser('dedupe', help='share identical image payloads between materials')
    d.add_argument('src')
    d.add_argument('dst')
    s = sub.add_parser('shape', help='crumple / fold shares of a GLB')
    s.add_argument('glb', nargs='+')
    f = sub.add_parser('fidelity', help='UV smear + shell penetration of a simplified GLB against its full source')
    f.add_argument('full')
    f.add_argument('simplified')
    f.add_argument('--samples', type=int, default=60000)
    a = ap.parse_args(argv)

    if a.cmd == 'bake':
        from .bake import bake
        ratios = tuple(float(x) for x in a.ratios.split(','))
        for u in a.usd:
            bake(u, a.project, a.out, a.godot, ratios=ratios, shell_lock=a.shell_lock, max_tex=a.max_texture, samples=a.samples,
                 do_cull=not a.no_cull)
    elif a.cmd == 'cull':
        from .cull import cull
        print(json.dumps(cull(a.src, a.dst, a.dirs, a.pitch), indent=1))
    elif a.cmd == 'dedupe':
        from .dedupe import dedupe
        print(json.dumps(dedupe(a.src, a.dst), indent=1))
    elif a.cmd == 'shape':
        from .shape import measure
        for g in a.glb:
            r = measure(g)
            print('%s: %d tris, crumple %.2f%%, fold %.2f%% -> %s' % (g, r['tris'], r['crumple_pct'], r['fold_pct'], 'ok' if r['ok'] else 'FAIL'))
    elif a.cmd == 'fidelity':
        from .fidelity import fidelity
        r = fidelity(a.full, a.simplified, a.samples)
        print(json.dumps({k: v for k, v in r.items()}, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
