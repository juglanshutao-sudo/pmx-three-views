"""Render orthographic three-views (front / side / back) from one PMX model.

Blender-side worker. All paths come from a UTF-8 JSON job file so that Chinese
paths never have to travel through a command line.

    <blender> --background --python render_three_views.py -- <job.json>

Job schema:
    {"name": "<角色名>", "pmx": "<素材>/<角色>.pmx", "out": "<输出>/<角色名>",
     "res": [1600, 2000], "samples": 32, "margin": 1.12,
     "hide_materials": []}

Material model (all learned the hard way, see 接手指南 note):
  * colour  = mmd_base_tex straight into an Emission shader (unlit texture colour)
  * alpha   = mmd_material.alpha, multiplied by the texture alpha ONLY when the
              image really carries an alpha channel (`image.depth == 32`).
              RGB-only PNGs return alpha 0 from the sampler and would otherwise
              turn the whole material invisible -> dither artefacts.
  * culling = `not mmd_material.is_double_sided` (PMX single-sided layers must be
              culled, otherwise inner shells paint over the correct surface)
  * blend   = DITHERED for opaque materials, BLENDED only for materials whose
              texture really carries an alpha channel.
              Two traps, both hit for real:
                - forcing BLENDED on everything makes opaque layers stop writing
                  depth, so alpha accumulates and the whole body turns see-through
                  (早柚 / 可莉 regression);
                - EEVEE's DITHERED does not remove a near-zero-alpha face, it
                  stochastically dithers it into black speckle. So any material
                  with alpha == 0 bypasses the MixShader entirely and goes
                  straight to a Transparent BSDF (爱诺 颜3 covering the head).
"""
import bpy
import json
import sys
from pathlib import Path
from mathutils import Vector

import numpy as np

_ALPHA_CACHE = {}


def real_alpha(img) -> bool:
    """True only if the texture actually has semi-transparent pixels.

    `image.depth == 32` is not enough: plenty of PMX packs ship RGBA PNGs whose
    alpha channel is entirely 1. Treating those as transparent pushes every
    material into BLENDED, which stops depth writes and turns the whole model
    see-through (早柚 / 可莉 regression). What we need to know is whether any
    pixel is actually < 1.
    """
    if img is None or img.depth != 32:
        return False
    if img.name in _ALPHA_CACHE:
        return _ALPHA_CACHE[img.name]
    try:
        buf = np.empty(len(img.pixels), dtype=np.float32)
        img.pixels.foreach_get(buf)
        has = bool(buf[3::4].min() < 0.98)
    except Exception:
        has = True
    _ALPHA_CACHE[img.name] = has
    print(f"[alpha] {img.name}: real_alpha={has}", flush=True)
    return has

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if not argv:
    raise SystemExit("need job.json path after --")
job = json.loads(Path(argv[0]).read_text(encoding="utf8"))

NAME = job["name"]
SRC = Path(job["pmx"])
OUT = Path(job["out"])
RES = tuple(job.get("res", [1600, 2000]))
SAMPLES = int(job.get("samples", 32))
MARGIN = float(job.get("margin", 1.12))
HIDE = set(job.get("hide_materials", []))
OUT.mkdir(parents=True, exist_ok=True)

print(f"[job] {NAME} <- {SRC}", flush=True)
if not SRC.is_file():
    raise SystemExit(f"missing pmx: {SRC}")


def wipe():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.cameras,
                 bpy.data.lights, bpy.data.armatures, bpy.data.images):
        for item in list(coll):
            if item.users == 0:
                try:
                    coll.remove(item)
                except Exception:
                    pass


wipe()

bpy.ops.mmd_tools_local.import_model(
    filepath=str(SRC), scale=0.08,
    types={"MESH", "ARMATURE", "MORPHS"}, log_level="ERROR")
scene = bpy.context.scene
scene.frame_set(1)
meshes = [o for o in scene.objects if o.type == "MESH"]
if not meshes:
    raise SystemExit("no mesh imported")
print(f"[import] meshes={len(meshes)}", flush=True)

report = {"name": NAME, "source": str(SRC), "materials": [],
          "missing_base_textures": [], "hidden": sorted(HIDE), "render_as": []}
for m in {s.material for o in meshes for s in o.material_slots if s.material}:
    if not m.node_tree:
        continue
    nt = m.node_tree
    mm = getattr(m, "mmd_material", None)
    base = next((n for n in nt.nodes if n.type == "TEX_IMAGE" and n.name == "mmd_base_tex" and n.image), None)
    if base is None:
        base = next((n for n in nt.nodes
                     if n.type == "TEX_IMAGE" and n.image
                     and n.name not in ("mmd_sphere_tex", "mmd_toon_tex")), None)
    image = None
    if base is not None and base.image is not None:
        resolved = Path(bpy.path.abspath(base.image.filepath))
        if not resolved.is_file():
            stem = Path(base.image.filepath.replace("\\", "/")).name
            hits = sorted(SRC.parent.rglob(stem))
            if hits:
                base.image.filepath = str(hits[0])
                base.image.reload()
                resolved = hits[0]
        if resolved.is_file():
            image = base.image
        else:
            report["missing_base_textures"].append({"material": m.name, "path": base.image.filepath})
        if base.name == "mmd_base_tex":
            base.extension = "EXTEND"

    has_alpha = real_alpha(image)
    pmx_alpha = float(getattr(mm, "alpha", 1.0)) if mm is not None else 1.0
    double = bool(getattr(mm, "is_double_sided", True)) if mm is not None else True

    for n in list(nt.nodes):
        if n.type == "OUTPUT_MATERIAL":
            nt.nodes.remove(n)
    out_node = nt.nodes.new("ShaderNodeOutputMaterial")
    out_node.location = (420, 0)
    transparent = nt.nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (160, -300)

    # alpha 0 layers must not go through a MixShader at all: with DITHERED they
    # survive as speckle, and 顔3 in 爱诺 covers the whole head.
    if m.name in HIDE or pmx_alpha <= 0.001:
        nt.links.new(transparent.outputs[0], out_node.inputs["Surface"])
        m.use_backface_culling = not double
        if hasattr(m, "surface_render_method"):
            m.surface_render_method = "BLENDED"
        report["materials"].append({
            "name": m.name, "texture": image.name if image else None,
            "texture_has_alpha": has_alpha, "pmx_alpha": round(pmx_alpha, 3),
            "double_sided": double, "transparent": True,
        })
        continue

    emission = nt.nodes.new("ShaderNodeEmission")
    emission.location = (160, 0)
    emission.inputs["Strength"].default_value = 1.0
    emission.inputs["Color"].default_value = (*m.diffuse_color[:3], 1.0)
    if image is not None:
        # reuse the imported node: it keeps the mmd_tex_uv group (UV morph / layer choice)
        nt.links.new(base.outputs["Color"], emission.inputs["Color"])
    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.location = (300, -120)
    nt.links.new(transparent.outputs[0], mix.inputs[1])
    nt.links.new(emission.outputs[0], mix.inputs[2])
    if has_alpha:
        amp = nt.nodes.new("ShaderNodeMath")
        amp.operation = "MULTIPLY"
        amp.location = (0, -260)
        amp.inputs[1].default_value = pmx_alpha
        nt.links.new(base.outputs["Alpha"], amp.inputs[0])
        nt.links.new(amp.outputs[0], mix.inputs[0])
    else:
        mix.inputs[0].default_value = pmx_alpha
    nt.links.new(mix.outputs[0], out_node.inputs["Surface"])
    m.use_backface_culling = not double
    if hasattr(m, "surface_render_method"):
        m.surface_render_method = "BLENDED" if has_alpha else "DITHERED"

    report["materials"].append({
        "name": m.name,
        "texture": image.name if image else None,
        "texture_has_alpha": has_alpha,
        "pmx_alpha": round(pmx_alpha, 3),
        "double_sided": double,
        "hidden": False,
    })
print(f"[materials] {len(report['materials'])} hidden={len(HIDE)} "
      f"missing={len(report['missing_base_textures'])}", flush=True)

bpy.context.view_layer.update()
points = [o.matrix_world @ v.co for o in meshes for v in o.data.vertices]
low = Vector([min(p[i] for p in points) for i in range(3)])
high = Vector([max(p[i] for p in points) for i in range(3)])
center = (low + high) / 2
dim = high - low
report["bounds"] = {"low": [round(v, 4) for v in low], "high": [round(v, 4) for v in high],
                    "size": [round(v, 4) for v in dim]}
aspect_w = RES[0] / RES[1]
ortho = max(dim.z, dim.x / aspect_w, dim.y / aspect_w) * MARGIN
report["ortho_scale"] = round(ortho, 4)
report["resolution"] = list(RES)
print(f"[bounds] size={[round(v, 3) for v in dim]} ortho={ortho:.3f}", flush=True)

scene.render.engine = "BLENDER_EEVEE"
scene.eevee.taa_render_samples = SAMPLES
scene.render.resolution_x, scene.render.resolution_y = RES
scene.render.resolution_percentage = 100
scene.render.film_transparent = True
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.render.image_settings.color_depth = "8"
scene.render.image_settings.compression = 50
scene.render.use_file_extension = True
scene.view_settings.view_transform = "Standard"
scene.view_settings.look = "None"
scene.view_settings.exposure = 0.0
scene.view_settings.gamma = 1.0
scene.world.color = (1, 1, 1)

VIEWS = [("front", "正面", (0, -1, 0)),
         ("side", "侧面", (1, 0, 0)),
         ("back", "背面", (0, 1, 0))]
report["views"] = []
for key, label, direction in VIEWS:
    cam_data = bpy.data.cameras.new(key)
    cam = bpy.data.objects.new(key, cam_data)
    scene.collection.objects.link(cam)
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = ortho
    cam_data.clip_start = 0.01
    cam_data.clip_end = 1000.0
    cam.location = center + Vector(direction) * (ortho * 3.0 + 5.0)
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam
    target = OUT / f"{key}.png"
    scene.render.filepath = str(target)
    print(f"[render] {key}", flush=True)
    bpy.ops.render.render(write_still=True)
    report["views"].append({"key": key, "label": label, "file": str(target)})

report["ok"] = True
(OUT / "_render_report.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
print(f"[done] {NAME} -> {OUT}", flush=True)
