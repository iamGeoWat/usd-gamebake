extends SceneTree
## Export a baked (imported) scene to GLB, capping every material texture at a maximum size first.
## Usage: godot --headless --path <tools project> -s bake_to_glb.gd -- <res:// scene> <out.glb> [max_texture_px=1024]
## Prints: BAKEGLB <scene> -> <glb> err=<append>/<write> capped=<n> <ms> ms size=<MB> MB

func _initialize() -> void:
	var a := OS.get_cmdline_user_args()
	if a.size() < 2:
		push_error("usage: -s bake_to_glb.gd -- <res:// scene> <out.glb> [max_texture_px]")
		quit(2)
		return
	var cap: int = int(a[2]) if a.size() > 2 else 1024
	var n: Node = (load(a[0]) as PackedScene).instantiate()
	root.add_child(n)
	var capped := _cap_textures(n, cap)
	var doc := GLTFDocument.new()
	var st := GLTFState.new()
	var t0 := Time.get_ticks_msec()
	var err := doc.append_from_scene(n, st)
	var err2 := doc.write_to_filesystem(st, a[1]) if err == OK else err
	print("BAKEGLB %s -> %s err=%d/%d capped=%d %d ms size=%.2f MB" % [a[0].get_file(), a[1].get_file(), err, err2, capped, Time.get_ticks_msec() - t0, FileAccess.get_file_as_bytes(a[1]).size() / 1.0e6])
	n.queue_free()
	quit(0 if err2 == OK else 1)

## Every material texture larger than `cap` px on its long side is resized (aspect kept) before export.
func _cap_textures(n: Node, cap: int) -> int:
	var done := {}
	var count := 0
	for mi in n.find_children("*", "MeshInstance3D", true, false):
		var m: Mesh = (mi as MeshInstance3D).mesh
		if m == null:
			continue
		for s in m.get_surface_count():
			var mat = m.surface_get_material(s)
			if not (mat is BaseMaterial3D):
				continue
			for slot in [BaseMaterial3D.TEXTURE_ALBEDO, BaseMaterial3D.TEXTURE_NORMAL, BaseMaterial3D.TEXTURE_ROUGHNESS, BaseMaterial3D.TEXTURE_METALLIC, BaseMaterial3D.TEXTURE_EMISSION, BaseMaterial3D.TEXTURE_AMBIENT_OCCLUSION]:
				var t: Texture2D = mat.get_texture(slot)
				if t == null or maxi(t.get_width(), t.get_height()) <= cap:
					continue
				var key := t.get_instance_id()
				if not done.has(key):
					var img := t.get_image()
					if img == null:
						continue
					if img.is_compressed():
						img.decompress()
					var k := float(cap) / float(maxi(img.get_width(), img.get_height()))
					img.resize(maxi(1, int(img.get_width() * k)), maxi(1, int(img.get_height() * k)), Image.INTERPOLATE_LANCZOS)
					done[key] = ImageTexture.create_from_image(img)
					count += 1
				mat.set_texture(slot, done[key])
	return count
