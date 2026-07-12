"""Revit materials -> neutral SceneSpec material records (contract 0.2.0).

The graphics-shading properties (Material.Color / Transparency / Smoothness)
always exist, so every material renders as *something* sane. The appearance
asset (real textures, glossiness, appearance class - bir_extract/appearance.py)
is then merged OVER that base when it can be read: a material whose asset is
missing or unreadable silently keeps the graphics approximation.

Material ids from LINKED models are namespaced "mat_l<instance-id>_<mat-id>"
(see geometry.extract_geometry) and resolve against the link's own Document -
both the graphics shading and the appearance asset live there, and the host
doc either lacks the id or owns an unrelated material under it.
"""
from bir_extract import _compat
from bir_extract import appearance

DB = _compat.DB


def extract_materials(doc, material_ids, link_docs=None):
    out = []
    resolved = 0
    for mid in sorted(material_ids):
        if mid == "mat_default":
            out.append(_default_record(mid))
            continue
        rec = None
        try:
            owner, val = _resolve(doc, mid, link_docs or {})
            el = owner.GetElement(_compat.make_element_id(val)) \
                if owner is not None else None
            if isinstance(el, DB.Material):
                rec = _from_material(owner, el)
                rec["id"] = mid
                resolved += 1
        except Exception:
            rec = None
        out.append(rec or _default_record(mid))
    # Warn (never fatal) when materials silently fall back to the flat "Default"
    # grey - that reads as an all-white render, and a silent fallback is what hid
    # the ElementId(int) ambiguity for days (see _compat.make_element_id).
    try:
        n = len(out)
        if n and resolved < n:
            print("Blendit: WARNING %d/%d materials fell back to Default grey "
                  "(unresolved) - render may look flat/white." % (n - resolved, n))
    except Exception:
        pass
    return out


def _resolve(doc, mid, link_docs):
    """-> (owning Document, integer material id) for a material key."""
    if mid.startswith("mat_l"):
        head, val = mid.rsplit("_", 1)
        return link_docs.get(head + "_"), int(val)
    return doc, int(mid[4:])  # strip "mat_"


def _default_record(mid):
    return {"id": mid, "name": "Default", "base_color": [0.7, 0.7, 0.7],
            "metallic": 0.0, "roughness": 0.6, "transparency": 0.0, "ior": 1.45}


def _from_material(doc, mat):
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

    rec = {"id": "", "name": name, "base_color": base, "metallic": 0.0,
           "roughness": roughness, "transparency": transparency, "ior": 1.45}
    # Appearance asset (textures / glossiness / class) wins over the graphics
    # approximation wherever it could actually be read.
    rec.update(appearance.read_appearance(doc, mat))
    return rec
