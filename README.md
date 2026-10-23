# usd-gamebake

Turn production OpenUSD assets into game-ready glTF through Godot: import with a fixed-up
[godot-usd](https://github.com/migueldeicaza/godot-usd), simplify without breaking labels or textures, remove every
triangle no one can see, and keep only the lightest result that passes measured quality gates.

It exists because there was no cross-platform, open-source tool for the "make this CAD-grade USD prop cheap enough for
a game" step. The optimizers that do this are closed or tied to one vendor's platform, and no open-source tool removed
hidden geometry per triangle.

## What is in here

| part | what it does |
|---|---|
| `patches/godot-usd/` | Fixes and additions to godot-usd (applied to a pinned upstream commit, see below): authored normals actually read, inward fallback normals fixed, linear USD colours converted for Godot's sRGB inputs, `doubleSided`, metal / roughness maps no longer zeroed, `displayColor` only where USD says it applies, instance proxies, UDIM atlases, a real bake through Godot's mesh import pipeline, vertex welding, and an import-time simplifier with a **shell lock**. Details: [`patches/godot-usd/CHANGES.md`](patches/godot-usd/CHANGES.md). |
| shell lock (in the importer) | Layered surfaces, such as a label 0.3-1.5 mm over a body, are simplified one surface at a time, so the body pokes through the label. Before simplifying, every triangle within `usd/simplify_shell_lock` metres of another surface is kept as authored, and only the rest is simplified, with the seam pinned. On the test assets this is what made simplification possible at all for several props. |
| `gamebake cull` | **Per-triangle hidden-geometry removal.** Embree ray grids from 162 directions plus an exact per-triangle centroid pass. Transparent materials never occlude, so a chain behind a glass shield stays. |
| `gamebake bake` | The pipeline: bake at a ladder of simplify ratios, cap textures, dedupe images, gate each step on shape and texture fidelity against the full-resolution bake, pick the lightest passing step, cull. Writes the GLB plus a JSON report. |
| `gamebake shape` | Crumple / fold shares: random folds from decimation, as opposed to designed feature lines. |
| `gamebake fidelity` | UV smear in texels (exact closest point, wrap-aware) and shell penetration, simplified vs full. |
| `gamebake dedupe` | Godot's glTF exporter writes one image per material; this shares identical payloads. |
| `godot/cull_check.gd` | Renders before / after GLBs from 24 random views and reports the share of changed pixels. |

## Results

Nine props from NVIDIA's openly published SimReady OpenUSD collection (no assets are included here):

| asset | full triangles | picked step | after hidden-geometry cull | of full |
|---|---:|---|---:|---:|
| multimeter | 55,492 | ratio 0.25 (15,336) | 14,069 | 25 % |
| forklift | 329,976 | ratio 0.25 (129,295) | 97,303 | 29 % |
| pallet jack | 380,248 | ratio 0.25 (196,466) | 155,422 | 41 % |
| plastic drum | 27,858 | ratio 0.12 (2,624) | 2,439 | 9 % |
| plywood crate | 25,110 | ratio 0.25 (7,702) | 6,715 | 27 % |
| fire extinguisher | 107,250 | ratio 0.12 (20,264) | 10,378 | 10 % |
| step ladder | 29,890 | ratio 0.25 (10,818) | 10,618 | 36 % |
| office monitor | 10,867 | ratio 0.25 (7,148) | 6,440 | 59 % |
| medicine cabinet | 472,064 | ratio 0.25 (291,370) | 141,449 | 30 % |

- **Every pick passes all gates:**
  - crumple ≤ 10 % and fold ≤ 20 %;
  - UV smear (> 4 texels) at most 2 points over the full bake's own floor;
  - shell penetration at most 1 point over the full bake.
- **The cull changes nothing visible:** across 24 random views per asset, the worst view has ≤ 0.011 % of pixels differing
  by more than 8/255.
- **Textures** are capped at 1024 px.
- The drum and crate rows were re-run end to end from this repository; they match the numbers above exactly.

## Requirements

- **OpenUSD**, built without Python or imaging. Validated: 26.11.1.
  ```
  python3 OpenUSD/build_scripts/build_usd.py --no-python --no-imaging --no-usdview --no-tests --no-examples \
      --no-tutorials --no-docs --no-materialx --no-build-apple-framework --build-variant release <install-prefix>
  ```
- **A Godot 4 editor** (4.3+ per godot-usd). Validated: 4.7.2 built with `precision=double`. A standard single-precision
  editor needs `PRECISION=single` builds.
- **godot-cpp.** Validated: master at `8070599`; the build script dumps the API of your editor so the extension
  matches it.
- **Python 3.10+:** `pip install -r requirements.txt` (numpy, scipy, trimesh, embreex).

## Build

```
git clone --recurse-submodules <this repo> && cd usd-gamebake
USD_SDK_PATH=<install-prefix> GODOT=/path/to/godot PRECISION=single scripts/build_extension.sh
```

This applies the patch series to `extern/godot-usd` (pinned to upstream `9c76c65`), dumps your editor's extension API,
builds, and copies the library into `godot/project/bin/`.

## Use

```
cp -R godot/project ./tools_project            # once: the tools project the importer runs in (holds the extension)
GODOT=/path/to/godot python -m gamebake bake path/to/asset.usd --project tools_project --out out/
# -> out/<asset>.glb (game-ready), out/<asset>.report.json (every step, its gates, the pick), the per-step GLBs

python -m gamebake cull in.glb out.glb          # the passes also run alone
python -m gamebake shape a.glb b.glb
python -m gamebake fidelity full.glb simplified.glb
godot -s godot/cull_check.gd -- before.glb after.glb diffs/   # needs a window
```

- `bake` copies the asset's folder into the tools project, so relative texture paths keep working.
- A fresh tools project is opened once before any asset goes in. In its first scan Godot registers the extension too late
  for the importer, and a `.usd` seen then is never imported.
- Options: `--ratios 1,0.5,0.25,0.12`, `--shell-lock 0.003` (metres), `--max-texture 1024`, `--no-cull`.

## Limitations

- **Validated on macOS arm64 only,** with the stack above. Linux / Windows and single-precision builds should work but
  are untested.
- **The cull assumes the asset is seen from outside.** Interiors meant to be looked into (an open cabinet, a cab) lose
  their insides; use `--no-cull` for those.
- **The gates are heuristics with fixed thresholds.**
  - Texture fidelity looks at `TEXCOORD_0` and the base colour texture's size.
  - Skinned and blend-shape meshes are not simplified.
  - The simplifier is Godot's own meshoptimizer LOD generation with locked borders, not an attribute-weighted one.
- **Known residual:** the simplified office monitor shows a faint diagonal shading on its screen.

## How this was made

- This project was developed with substantial help from an AI assistant (Anthropic's Claude), under the maintainer's
  direction and review.
- Commits carry a `Co-Authored-By` trailer.
- The measurements above come from the code in this repository.

## License

- MIT for this repository ([LICENSE](LICENSE)).
- The godot-usd patches modify godot-usd (MIT, © Miguel de Icaza) and are offered under the same terms.
- Third-party notices: [THIRD_PARTY.md](THIRD_PARTY.md).
