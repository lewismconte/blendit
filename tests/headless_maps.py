"""Real Revit texture maps, end to end - NO Revit needed (bpy only).

    blender --background --python tests/headless_maps.py

Covers the contract-0.2.0 `maps` path both directions:
  * exporter: absolute `source_path`s -> files copied into textures/, uris
    rewritten bundle-relative, shared bitmaps deduped, dead paths dropped;
  * importer: build_material builds a BOX-projected Image Texture at the real
    world scale on Object coords, wires the bump map, and the render shows it.

The Revit-side appearance READER (bir_extract/appearance.py) needs a live Revit
and is exercised by using the extension; everything downstream of it is here.
"""
import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
_LIB = os.path.join(_ROOT, "lib")
for _p in (_ROOT, _LIB):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import bpy  # noqa: E402
import numpy as np  # noqa: E402

from bir_contract.transport import MeshData, get_exporter  # noqa: E402
import bir_transports.gltf.exporter  # noqa: E402,F401  (registers "gltf")
sys.path.insert(0, _HERE)
from fixtures.build_fixture import build_spec, _box, _quad  # noqa: E402

OUT = os.path.join(_ROOT, "out")
CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append((name, bool(ok)))
    print("  %-52s %s %s" % (name, "OK" if ok else "FAIL", detail))


def _write_png(path, w, h, fn):
    """Tiny dependency-free PNG writer via bpy images; fn(x, y) -> (r, g, b)."""
    img = bpy.data.images.new("tmp", width=w, height=h)
    px = np.empty((h, w, 4), dtype=np.float32)
    for y in range(h):
        for x in range(w):
            r, g, b = fn(x, y)
            px[y, x] = (r, g, b, 1.0)
    img.pixels.foreach_set(px.ravel())
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def _brick(x, y):
    """A recognisable brick course: red brick, light mortar lines."""
    course = (y // 16) % 2
    bx = (x + (16 if course else 0)) % 32
    if y % 16 < 2 or bx < 2:
        return (0.85, 0.83, 0.80)
    return (0.55, 0.18, 0.12)


def _bumpmap(x, y):
    v = 0.5 + 0.5 * (((x // 4) + (y // 4)) % 2)
    return (v, v, v)


def main():
    work = tempfile.mkdtemp(prefix="blendit_maps_")
    src_dir = os.path.join(work, "src")
    os.makedirs(src_dir)
    diffuse_src = os.path.join(src_dir, "brick.png")
    bump_src = os.path.join(src_dir, "brick_bump.png")
    _write_png(diffuse_src, 64, 64, _brick)
    _write_png(bump_src, 64, 64, _bumpmap)

    # --- 1. exporter: bundle a spec whose material carries source_paths -------
    spec = build_spec()
    concrete = spec["materials"][0]
    concrete["maps"] = {
        "diffuse": {"source_path": diffuse_src,
                    "scale_m": [0.6, 0.3], "offset_m": [0.0, 0.0],
                    "rotation_deg": 0.0},
        "bump": {"source_path": bump_src, "amount": 0.4,
                 "scale_m": [0.6, 0.3]},
    }
    # A second material sharing the SAME bitmap (dedupe) + a dead path (drop).
    glass = spec["materials"][1]
    glass["maps"] = {
        "diffuse": {"source_path": diffuse_src, "scale_m": [1.0, 1.0]},
        "bump": {"source_path": os.path.join(src_dir, "missing.png")},
    }
    bundle = os.path.join(work, "bundle")
    meshes = [
        _box("Box_1", 0.0, 0.0, 0.0, 10.0, 10.0, 10.0, "mat_concrete"),
        _quad("Glass_1",
              [(2.0, -5.0, 0.0), (8.0, -5.0, 0.0), (8.0, -5.0, 8.0), (2.0, -5.0, 8.0)],
              (0.0, -1.0, 0.0), "mat_glass"),
    ]
    get_exporter("gltf").export(spec, meshes, bundle)

    tex_dir = os.path.join(bundle, "textures")
    files = sorted(os.listdir(tex_dir)) if os.path.isdir(tex_dir) else []
    check("exporter copies textures into textures/",
          files == ["brick.png", "brick_bump.png"], str(files))
    d = spec["materials"][0]["maps"]["diffuse"]
    check("diffuse uri rewritten bundle-relative",
          d.get("uri") == "textures/brick.png" and "source_path" not in d, str(d))
    check("shared bitmap deduped (one copy, same uri)",
          spec["materials"][1]["maps"]["diffuse"].get("uri") == "textures/brick.png")
    check("dead source path dropped",
          "bump" not in spec["materials"][1]["maps"])

    # Re-export into the SAME dir (the Load View cache slot is reused): textures/
    # must not accumulate suffixed copies, and uris must stay stable.
    spec2 = build_spec()
    spec2["materials"][0]["maps"] = {
        "diffuse": {"source_path": diffuse_src, "scale_m": [0.6, 0.3]},
        "bump": {"source_path": bump_src, "amount": 0.4, "scale_m": [0.6, 0.3]},
    }
    get_exporter("gltf").export(spec2, meshes, bundle)
    files2 = sorted(os.listdir(tex_dir))
    check("re-export into the same cache dir stays clean",
          files2 == ["brick.png", "brick_bump.png"] and
          spec2["materials"][0]["maps"]["diffuse"]["uri"] == "textures/brick.png",
          str(files2))

    # --- 2. importer: real pipeline render off that bundle --------------------
    from blender.pipeline.run import run_pipeline
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    out_png = os.path.join(OUT, "maps_realistic.png")
    run_pipeline(bundle, out_png, overrides={
        "engine": "CYCLES", "mode": "realistic", "samples": 32,
        "resolution": [640, 360],
    })
    check("realistic render wrote a PNG", os.path.isfile(out_png), out_png)

    # The material actually rendering = the one on the merged object (the glTF
    # importer also creates a same-named material from the glb; don't grab that).
    obj = bpy.data.objects.get("BIR_Mat_mat_concrete")
    mat = obj.data.materials[0] if obj and obj.data.materials else None
    check("concrete material assigned on the merged object", mat is not None)
    nodes = mat.node_tree.nodes if mat else []
    imgs = [n for n in nodes if n.type == "TEX_IMAGE"]
    check("two image textures (diffuse + bump)", len(imgs) == 2,
          str([os.path.basename(i.image.filepath) for i in imgs if i.image]))
    check("box projection on the image nodes",
          all(n.projection == "BOX" for n in imgs))
    mapping = next((n for n in nodes if n.type == "MAPPING"), None)
    sc = tuple(mapping.inputs["Scale"].default_value) if mapping else ()
    check("mapping scale = 1/real-world size (1/.6, 1/.6, 1/.3)",
          mapping is not None and
          abs(sc[0] - 1 / 0.6) < 1e-4 and abs(sc[2] - 1 / 0.3) < 1e-4, str(sc))
    bump = next((n for n in nodes if n.type == "BUMP"), None)
    check("bump node wired at the extracted amount",
          bump is not None and abs(bump.inputs["Strength"].default_value - 0.4) < 1e-4)
    tc = next((n for n in nodes if n.type == "TEX_COORD"), None)
    check("driven by Object coordinates (world metres)",
          tc is not None and mapping is not None and
          any(l.from_node == tc and l.from_socket.name == "Object"
              for l in mat.node_tree.links if l.to_node == mapping))

    # --- 3. override precedence: "plain" beats the real maps ------------------
    from blender.pipeline.materials import build_material
    plain = build_material(spec["materials"][0], surface="plain", base_dir=bundle)
    check("'plain' override suppresses the real maps",
          not [n for n in plain.node_tree.nodes if n.type == "TEX_IMAGE"])

    shutil.rmtree(work, ignore_errors=True)
    failed = [n for n, ok in CHECKS if not ok]
    print("MAPS: %d checks, %d failed%s"
          % (len(CHECKS), len(failed), (" -> " + ", ".join(failed)) if failed else ""))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
