"""USD -> game-ready GLB.

Bakes one USD asset through the patched godot-usd importer at a ladder of simplify ratios, gates every step on shape
(crumple / fold) and texture fidelity (UV smear, shell penetration) against the full-ratio bake, keeps the lightest step
that passes, then removes hidden geometry.

Each step: write the importer options into the asset's .import file, re-import headless, export the imported scene to
GLB with every texture capped at max_tex px (godot/bake_to_glb.gd), dedupe its images, measure.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import time

from . import cull as C
from . import dedupe as D
from . import fidelity as F
from . import shape as S

HERE = os.path.dirname(os.path.abspath(__file__))
BAKE_SCRIPT = os.path.join(os.path.dirname(HERE), 'godot', 'bake_to_glb.gd')
MAX_SMEAR_INCREASE = 2.0       # percentage points of area with UV error > 4 texels, over the full bake's own floor
MAX_PENETRATION_INCREASE = 1.0  # percentage points of a layered shell pushed through the surface under it


def _json_default(o):
    """The report's encoder fallback: numpy scalars from the measurement passes (np.bool_, np.float64, np.int64) as Python values."""
    if hasattr(o, 'item'):
        return o.item()
    raise TypeError('Object of type %s is not JSON serializable' % type(o).__name__)


def _run(cmd, timeout):
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return time.time() - t0, r.returncode, r.stdout + r.stderr


def _set_params(imp, ratio, guard, lock):
    s = open(imp).read()
    if '[params]' not in s:
        s = s.rstrip('\n') + '\n\n[params]\n'
    s = re.sub(r'\nusd/simplify_(ratio|max_error|shell_lock)=.*', '', s)
    s = s.replace('[params]\n', '[params]\n\nusd/simplify_ratio=%s\nusd/simplify_max_error=%s\nusd/simplify_shell_lock=%s\n' % (ratio, guard, lock), 1)
    with open(imp, 'w') as f:
        f.write(s)


def _stage(usd, project):
    """The asset inside the tools project (its folder is copied in, so relative texture paths keep working)."""
    usd = os.path.abspath(usd)
    project = os.path.abspath(project)
    if usd.startswith(project + os.sep):
        return usd
    stem = os.path.splitext(os.path.basename(usd))[0]
    dst = os.path.join(project, 'gamebake_assets', stem)
    shutil.copytree(os.path.dirname(usd), dst, dirs_exist_ok=True)
    return os.path.join(dst, os.path.basename(usd))


def bake(usd, project, out, godot, ratios=(1.0, 0.5, 0.25, 0.12), shell_lock=0.003, guards=(0.00025, 0.0001), max_tex=1024,
         samples=60000, do_cull=True, log=print):
    project = os.path.abspath(project)
    if not os.path.exists(os.path.join(project, 'godot_usd.gdextension')):
        raise FileNotFoundError('%s is not a tools project (no godot_usd.gdextension); start from godot/project/' % project)
    os.makedirs(out, exist_ok=True)
    # a fresh project registers the extension DURING its first file scan, too late for the importer: a .usd seen in that scan is
    # taken for a plain resource (a .uid lands beside it) and is never imported. Open the project once before staging assets.
    if not os.path.exists(os.path.join(project, '.godot', 'extension_list.cfg')):
        _run([godot, '--headless', '--path', project, '--import'], 600)
    asset = _stage(usd, project)
    if not os.path.exists(asset + '.import') and os.path.exists(asset + '.uid'):
        os.remove(asset + '.uid')   # left by such a scan
    name = os.path.basename(asset)
    stem = os.path.splitext(name)[0]
    imp = asset + '.import'
    res_path = 'res://' + os.path.relpath(asset, project).replace(os.sep, '/')
    if not os.path.exists(imp):
        _run([godot, '--headless', '--path', project, '--import'], 1500)
        if not os.path.exists(imp):
            raise RuntimeError('Godot did not import %s: is the extension in %s/bin and built for this editor?' % (res_path, project))
    report = {'asset': os.path.basename(usd), 'steps': []}
    full = {'glb': None, 'smear_floor': 0.0}

    def step(ratio, guard):
        lock = shell_lock if ratio < 1.0 else 0.0
        glb = os.path.join(out, '%s_r%s_g%s.glb' % (stem, ratio, guard))
        _set_params(imp, ratio, guard, lock)
        for f in glob.glob(os.path.join(project, '.godot', 'imported', name + '-*')):
            os.remove(f)
        t_imp, _, _ = _run([godot, '--headless', '--path', project, '--import'], 1500)
        scn = glob.glob(os.path.join(project, '.godot', 'imported', name + '-*.scn'))
        if not scn:
            return {'ratio': ratio, 'guard_mm': guard * 1000, 'error': 'import produced no scene'}
        t_bake, rc, o = _run([godot, '--headless', '--path', project, '-s', BAKE_SCRIPT, '--',
                              'res://.godot/imported/' + os.path.basename(scn[0]), os.path.abspath(glb), str(max_tex)], 900)
        if rc != 0 or not os.path.exists(glb):
            return {'ratio': ratio, 'guard_mm': guard * 1000, 'error': 'GLB export failed', 'log': o[-2000:]}
        D.dedupe(glb, glb + '.tmp')
        os.replace(glb + '.tmp', glb)
        sh = S.measure(glb)
        fi = F.fidelity(full['glb'] or glb, glb, samples)
        st = {'ratio': ratio, 'guard_mm': guard * 1000, 'shell_lock_mm': lock * 1000, 'import_s': round(t_imp, 1), 'bake_s': round(t_bake, 1),
              'tris': sh['tris'], 'crumple_pct': round(sh['crumple_pct'], 2), 'fold_pct': round(sh['fold_pct'], 2),
              'uv_smear_pct': round(fi['uv_smear_pct'], 2), 'penetration_increase_pct': round(fi['penetration_increase_pct'], 2),
              'glb': os.path.basename(glb), 'mb': round(os.path.getsize(glb) / 1e6, 2), 'shape_ok': sh['ok']}
        st['uv_smear_increase'] = round(st['uv_smear_pct'] - full['smear_floor'], 2) if full['glb'] else 0.0
        # a dip below the full bake's own floor is sampling noise, not a failure
        st['texture_ok'] = st['uv_smear_increase'] <= MAX_SMEAR_INCREASE and 0 <= st['penetration_increase_pct'] <= MAX_PENETRATION_INCREASE
        log('%s r%s g%.2fmm: %d tris, crumple %.2f%% fold %.2f%%, smear +%.2f, penetration +%.2f -> shape %s texture %s' % (
            stem, ratio, guard * 1000, st['tris'], st['crumple_pct'], st['fold_pct'], st['uv_smear_increase'], st['penetration_increase_pct'],
            'ok' if st['shape_ok'] else 'FAIL', 'ok' if st['texture_ok'] else 'FAIL'))
        return st

    s0 = step(ratios[0], 0.0)
    if 'error' in s0:
        raise RuntimeError('%s: the full bake failed: %s' % (stem, s0['error']))
    full['glb'] = os.path.join(out, s0['glb'])
    full['smear_floor'] = s0['uv_smear_pct']
    s0['uv_smear_increase'] = 0.0
    s0['texture_ok'] = True
    report['steps'].append(s0)
    for r in ratios[1:]:
        st = step(r, 0.0)
        report['steps'].append(st)
        if st.get('shape_ok') and not st.get('texture_ok'):
            for g in guards:   # the error guard refuses levels that drift too far; retry the ratio under it
                sg = step(r, g)
                report['steps'].append(sg)
                if sg.get('texture_ok'):
                    break
    ok = [s for s in report['steps'] if s.get('shape_ok') and s.get('texture_ok')]
    pick = min(ok, key=lambda s: s['tris'])
    report['pick'] = pick
    final = os.path.join(out, stem + '.glb')
    if do_cull:
        cs = C.cull(os.path.join(out, pick['glb']), final)
        report['final'] = {'glb': os.path.basename(final), 'tris': cs['tris_out'], 'hidden_area_pct': round(cs['hidden_area_pct'], 1),
                           'mb': round(cs['mb_out'], 2)}
    else:
        shutil.copyfile(os.path.join(out, pick['glb']), final)
        report['final'] = {'glb': os.path.basename(final), 'tris': pick['tris'], 'mb': pick['mb']}
    report['final']['of_full_pct'] = round(100 * report['final']['tris'] / s0['tris'])
    with open(os.path.join(out, stem + '.report.json'), 'w') as f:
        json.dump(report, f, indent=1, default=_json_default)
    log('%s: full %d tris -> pick r%s %d tris -> final %d tris (%d%% of full), %.2f MB' % (
        stem, s0['tris'], pick['ratio'], pick['tris'], report['final']['tris'], report['final']['of_full_pct'], report['final']['mb']))
    return report
