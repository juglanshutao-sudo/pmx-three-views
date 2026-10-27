"""Render a material-ID map: every material gets a unique flat colour.

This is the fastest way to answer "which material is painting that black patch?".
Give each material one colour, render, then read the pixel at the problem area and
look it up in the emitted colour_key.json.

It also supports hiding a layer and re-rendering, which reveals *what is underneath*
a suspect material — the question that decides whether the layer itself is broken
or is simply covering something else.

Blender-side worker, driven by a UTF-8 job file:

    <blender> --background --python material_id_map.py -- <job.json>

Job schema:
    {"pmx": "<model>.pmx", "out": "<dir>",
     "res": [900, 1200], "hide": ["颜3"],
     "views": ["front"]}

Outputs, in <out>:
    id_map_<view>.png       flat colour per material
    color_key.json          materials: name -> {linear, rgb255};
                            lookup_rgb255: "r,g,b" -> name (use this with a colour picker)
"""
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if not argv:
    raise SystemExit("need job.json path after --")
job = json.loads(Path(argv[0]).read_text(encoding="utf8"))

SRC = Path(job["pmx"])
OUT = Path(job["out"])
RES = tuple(job.get("res", [900, 1200]))
HIDE = set(job.get("hide", []))
VIEWS = job.get("views", ["front"])
OUT.mkdir(parents=True, exist_ok=True)

for ob in list(bpy.data.objects):
    bpy.data.objects.remove(ob, do_unlink=True)
bpy.ops.mmd_tools_local.import_model(filepath=str(SRC), scale=0.08,
                                     types={"MESH", "ARMATURE", "MORPHS"}, log_level="ERROR")
scene = bpy.context.scene
scene.frame_set(1)
meshes = [o for o in scene.objects if o.type == "MESH"]
if not meshes:
    raise SystemExit("no mesh imported")

def to_srgb255(v: float) -> int:
    """Emission colour is linear; the saved PNG is sRGB-encoded. A colour picker
    in any image viewer reads the sRGB byte, so the key must record that too or
    lookups silently fail."""
    s = 12.92 * v if v <= 0.0031308 else 1.055 * (v ** (1 / 2.4)) - 0.055
    return int(round(max(0.0, min(1.0, s)) * 255))


# one distinct colour per material: 8x8x8 cube lattice, skipping near-black
mats = sorted({s.material for o in meshes for s in o.material_slots if s.material}, key=lambda m: m.name)
key = {}
for i, m in enumerate(mats):
    r = ((i + 1) % 8) / 8.0
    g = (((i + 1) // 8) % 8) / 8.0
    b = (((i + 1) // 64) % 8) / 8.0
    key[m.name] = {"linear": [round(r, 3), round(g, 3), round(b, 3)],
                   "rgb255": [to_srgb255(r), to_srgb255(g), to_srgb255(b)]}
    nt = m.node_tree
    for n in list(nt.nodes):
        if n.type == "OUTPUT_MATERIAL":
            nt.nodes.remove(n)
    out_node = nt.nodes.new("ShaderNodeOutputMaterial")
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    if m.name in HIDE:
        nt.links.new(tr.outputs[0], out_node.inputs["Surface"])
        continue
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (r, g, b, 1.0)
    em.inputs["Strength"].default_value = 1.0
    nt.links.new(em.outputs[0], out_node.inputs["Surface"])
    mm = getattr(m, "mmd_material", None)
    m.use_backface_culling = not bool(getattr(mm, "is_double_sided", True))

# 反查优先用 rgb255（取色器读到的值），linear 仅供脚本内部核对
lookup = {",".join(str(v) for v in meta["rgb255"]): name for name, meta in key.items()}
(OUT / "color_key.json").write_text(
    json.dumps({"materials": key, "lookup_rgb255": lookup}, ensure_ascii=False, indent=1),
    encoding="utf8")

pts = [o.matrix_world @ v.co for o in meshes for v in o.data.vertices]
low = Vector([min(p[i] for p in pts) for i in range(3)])
high = Vector([max(p[i] for p in pts) for i in range(3)])
center = (low + high) / 2
dim = high - low
ortho = max(dim.z, dim.x / (RES[0] / RES[1]), dim.y / (RES[0] / RES[1])) * 1.12

scene.render.engine = "BLENDER_EEVEE"
scene.eevee.taa_render_samples = 8
scene.render.resolution_x, scene.render.resolution_y = RES
scene.render.film_transparent = True
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.view_settings.view_transform = "Standard"
scene.view_settings.look = "None"

DIRS = {"front": (0, -1, 0), "side": (1, 0, 0), "back": (0, 1, 0)}
for view in VIEWS:
    d = DIRS.get(view)
    if d is None:
        print(f"[skip] unknown view {view}")
        continue
    cd = bpy.data.cameras.new(view)
    cam = bpy.data.objects.new(view, cd)
    scene.collection.objects.link(cam)
    cd.type = "ORTHO"
    cd.ortho_scale = ortho
    cd.clip_start = 0.01
    cd.clip_end = 1000
    cam.location = center + Vector(d) * (ortho * 3 + 5)
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam
    scene.render.filepath = str(OUT / f"id_map_{view}.png")
    bpy.ops.render.render(write_still=True)
    print(f"[render] {view}", flush=True)

print(f"[done] {len(mats)} materials, hidden={sorted(HIDE)} -> {OUT}", flush=True)
