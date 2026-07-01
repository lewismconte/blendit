"""Revit materials -> neutral SceneSpec material records (contract 0.1.0 fields).

Phase 1 uses the graphics-shading properties (Material.Color / Transparency /
Smoothness), which always exist, so every material renders as *something* sane.
Richer appearance-asset reading (metallic detection, glossiness, textures, the
Appendix D `appearance_class`) is the next material iteration -> contract 0.2.0.
"""
from bir_extract import _compat

DB = _compat.DB


def extract_materials(doc, material_ids):
    out = []
    for mid in sorted(material_ids):
        if mid == "mat_default":
            out.append(_default_record(mid))
            continue
        rec = None
        try:
            val = int(mid[4:])  # strip "mat_"
            el = doc.GetElement(_compat.make_element_id(val))
            if isinstance(el, DB.Material):
                rec = _from_material(el)
                rec["id"] = mid
        except Exception:
            rec = None
        out.append(rec or _default_record(mid))
    return out


def _default_record(mid):
    return {"id": mid, "name": "Default", "base_color": [0.7, 0.7, 0.7],
            "metallic": 0.0, "roughness": 0.6, "transparency": 0.0, "ior": 1.45}


def _from_material(mat):
    base = [0.7, 0.7, 0.7]
    try:
        color = mat.Color
        if color is not None and color.IsValid:
            base = [_compat.srgb_to_linear(color.Red / 255.0),
                    _compat.srgb_to_linear(color.Green / 255.0),
                    _compat.srgb_to_linear(color.Blue / 255.0)]
    except Exception:
        pass

    transparency = 0.0
    try:
        transparency = max(0.0, min(1.0, mat.Transparency / 100.0))
    except Exception:
        pass

    smoothness = 50.0
    try:
        smoothness = float(mat.Smoothness)
    except Exception:
        pass
    roughness = max(0.05, min(1.0, 1.0 - smoothness / 100.0))

    name = "Material"
    try:
        name = mat.Name
    except Exception:
        pass

    return {"id": "", "name": name, "base_color": base, "metallic": 0.0,
            "roughness": roughness, "transparency": transparency, "ior": 1.45}
