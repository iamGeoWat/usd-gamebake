extends SceneTree
## Does a geometry pass change the picture? Renders GLB A (before) and GLB B (after) from K seeded random
## directions (none of them in the cull's Fibonacci set) at the same framing, and prints the share of pixels differing by > 8/255.
## Usage (needs a window, not --headless): godot -s cull_check.gd -- a.glb b.glb out_dir [K=24]   (diff PNGs for views > 0.05 %)
func _initialize() -> void:
	_run.call_deferred(OS.get_cmdline_user_args())
func _load(p: String) -> Node3D:
	var doc := GLTFDocument.new(); var st := GLTFState.new(); doc.append_from_file(p, st); return doc.generate_scene(st)
func _aabb(n: Node3D) -> AABB:
	var aabb := AABB(); var first := true
	for mi in n.find_children("*", "MeshInstance3D", true, false):
		var b: AABB = (mi as MeshInstance3D).global_transform * (mi as MeshInstance3D).get_aabb()
		aabb = b if first else aabb.merge(b); first = false
	return aabb
func _run(a: Array) -> void:
	await process_frame
	root.size = Vector2i(720, 720)
	var k: int = int(a[3]) if a.size() > 3 else 24
	var world := Node3D.new(); root.add_child(world)
	var env := WorldEnvironment.new(); var e := Environment.new(); e.background_mode = Environment.BG_COLOR; e.background_color = Color(0.2, 0.2, 0.22)
	e.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR; e.ambient_light_color = Color(0.5, 0.5, 0.5); env.environment = e; world.add_child(env)
	var cam := Camera3D.new(); world.add_child(cam); cam.current = true; cam.fov = 35.0
	var sun := DirectionalLight3D.new(); world.add_child(sun)
	var imgs := [[], []]
	var rng := RandomNumberGenerator.new(); rng.seed = 20261023
	var dirs := []
	for i in k:
		var z := rng.randf_range(-1.0, 1.0); var t := rng.randf_range(0.0, TAU); var r := sqrt(1.0 - z * z)
		dirs.append(Vector3(r * cos(t), z, r * sin(t)))
	var frame := AABB()
	for which in 2:
		var n := _load(a[which]); world.add_child(n); await process_frame
		if which == 0: frame = _aabb(n)
		var c := frame.get_center(); var rad := frame.size.length() * 0.55
		for d in dirs:
			var up := Vector3.UP if absf(d.y) < 0.95 else Vector3.FORWARD
			cam.look_at_from_position(c + d * rad / tan(deg_to_rad(17.5)), c, up)
			sun.look_at_from_position(c + d * 10.0 + up * 3.0, c, up)
			for _f in 3: await process_frame
			await RenderingServer.frame_post_draw
			imgs[which].append(root.get_texture().get_image())
		n.queue_free(); await process_frame
	var worst := 0.0; var sum := 0.0
	for i in k:
		var A: Image = imgs[0][i]; var B: Image = imgs[1][i]; var diff := 0; var tot := A.get_width() * A.get_height()
		var D := Image.create(A.get_width(), A.get_height(), false, Image.FORMAT_RGB8)
		for y in A.get_height():
			for x in A.get_width():
				var ca := A.get_pixel(x, y); var cb := B.get_pixel(x, y)
				if absf(ca.r - cb.r) > 8.0 / 255.0 or absf(ca.g - cb.g) > 8.0 / 255.0 or absf(ca.b - cb.b) > 8.0 / 255.0:
					diff += 1; D.set_pixel(x, y, Color(1, 0, 0))
				else:
					D.set_pixel(x, y, ca * 0.5)
		var share := 100.0 * diff / tot; worst = maxf(worst, share); sum += share
		if share > 0.05: D.save_png("%s/diff_%02d.png" % [a[2], i])
	print("CULLCHECK %s vs %s: %d views, mean %.3f%% worst %.3f%% pixels differ (>8/255)" % [a[0].get_file(), a[1].get_file(), k, sum / k, worst])
	quit(0)
