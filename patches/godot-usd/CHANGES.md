# godot-usd patch series

Applied in order to [migueldeicaza/godot-usd](https://github.com/migueldeicaza/godot-usd) at
`9c76c6529dc663d52f064919fc25e1408744b7de` (`scripts/apply_patches.sh`). Each patch covers one file group; together they
are 550 added and 21 removed lines. Every fix was found by comparing bakes against the assets' reference renders.

## 0001 textures: UDIM atlases, imported textures (`usd_usdz.*`)

- **UDIM.** A texture path containing `<UDIM>` loads every tile on disk into one atlas. The material maps it through
  `uv1_scale` / `uv1_offset`, so mesh UVs stay untouched.
- **Imported textures.** A texture file that lives inside the Godot project is loaded as the project's imported texture
  (VRAM compression, mipmaps), not decoded again as a raw image.

## 0002 instance proxies (`usd_stage_utils.cpp`, `usd_scene_loader.cpp`)

- **Instance proxies.** Children are walked with `UsdTraverseInstanceProxies()`. Instanceable prims, which are common in
  production assets, were skipped, so whole parts of an asset were missing.
- **Math constant.** `Math_PI` → `Math::PI`, which current godot-cpp requires.

## 0003 mesh builder (`usd_mesh_builder.cpp`)

- **Authored normals are read.**
  - `UsdGeomPrimvar(GetNormalsAttr())` is never valid: `normals` is a plain PointBased attribute, not a primvar.
  - So every mesh got generated, faceted normals.
  - USD's rule now applies: `primvars:normals` when authored, else `normals` with `GetNormalsInterpolation()`.
- **Generated normals face outward.**
  - The builder's corner order is Godot's clockwise front order, so the face normal is `(c - a) x (b - a)`.
  - The old cross product pointed every generated normal into the surface, which lit props from behind.
- **`displayColor` only where USD applies it,** that is to unbound gprims, or to materials that read vertex colours.
  Otherwise a glTF round trip multiplies it into the albedo.
- **`doubleSided`** renders both faces, through a duplicated material with `CULL_DISABLED`, so single-sided meshes
  sharing the material keep their culling.

## 0004 materials (`usd_materials.cpp`)

- **Colour space.**
  - UsdPreviewSurface colours are linear, while `BaseMaterial3D` albedo and emission are sRGB colours.
  - Diffuse and emissive are converted on import and converted back on export. A linear orange rendered dark red before.
- **No tint under a texture.** A connected input ignores its authored value, so the albedo is white when a texture drives
  it.
- **Metal and roughness maps survive.**
  - Godot multiplies the metallic / roughness scalar into the texture.
  - A connected input has no authored value, so the default 0 zeroed every metal map (chrome rendered as white plastic).
  - The scalar is now 1 whenever a texture is connected.
- **UDIM atlases get their uv transform.**

## 0005 scene importer (`usd_scene_importer.cpp`)

- **A real bake.**
  - The importer hands Godot `ImporterMeshInstance3D` nodes, as the glTF / FBX importers do, so the scene import pipeline
    applies LODs, mesh compression and shadow meshes.
  - Owners are set recursively; otherwise only the root was packed and the bake was an empty node.
- **The preview rig is stripped.** The loader's preview `WorldEnvironment` and sun (added when a stage has no lights) no
  longer ride into baked assets, where they were exported as `KHR_lights_punctual`.
- **Vertex weld.**
  - Face-varying data gave every triangle three private vertices (a 330k-triangle asset had 990k vertices).
  - Vertices identical in every attribute are now welded. Note that `SurfaceTool::index()` is a no-op on an already
    indexed surface, hence `deindex()` first.
- **Import-time simplifier,** with three options:
  - `usd/simplify_ratio`: the target, as a share of the triangles; 1 = off.
  - `usd/simplify_max_error`: a guard in world metres; a level whose error exceeds it is refused.
  - `usd/simplify_shell_lock`: metres, described below.
  - It uses Godot's meshoptimizer LOD generation with `SIMPLIFY_LOCK_BORDER`, and takes the coarsest level within the
    ratio and the guard as the new base mesh.
- **Shell lock.**
  - Every triangle within `usd/simplify_shell_lock` metres of another surface of the asset is marked: a 1 cm grid, the
    exact closest point on the triangle, both sides of the pair.
  - Marked triangles are kept as authored; only the free set is simplified, with its border locked.
  - Without this, a body simplified on its own drifts through the label over it.

## 0006 UDIM cache teardown (`usd_usdz.*`, `register_types.cpp`)

- **No crash at exit.** The 0001 UDIM caches were `thread_local HashMap<String, Ref<Texture2D>>`, destroyed in `exit()`'s
  thread-local finalizer after Godot had shut down; the `Ref`'s unreference called into the dead engine, so every
  import step that touched the cache ended in a SIGSEGV and a macOS "quit unexpectedly" report. The caches now live on
  the heap behind a trivially destructible `thread_local` pointer, every thread's cache is emptied at the extension's
  SCENE uninitialize while the engine is alive, and the emptied maps are deliberately leaked.
