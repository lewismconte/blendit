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
    # DIAGNOSTIC (temporary): why does a material fall back to the flat "Default"
    # grey? Everything-white renders mean every id failed to resolve to a
    # DB.Material; this logs the reason so a re-extraction reveals the cause.
    diag = {"resolved": 0, "default": 0}
    reasons = {}
    examples = []
    for mid in sorted(material_ids):
        if mid == "mat_default":
            out.append(_default_record(mid))
            continue
        rec = None
        reason = None
        val = None
        try:
            owner, val = _resolve(doc, mid, link_docs or {})
            if owner is None:
                reason = "owner_none"
            else:
                el = owner.GetElement(_compat.make_element_id(val))
                if el is None:
                    reason = "getelement_none"
                elif not isinstance(el, DB.Material):
                    reason = "not_material:" + type(el).__name__
                else:
                    rec = _from_material(owner, el)
                    rec["id"] = mid
        except Exception as ex:
            reason = "exc:" + type(ex).__name__ + ":" + str(ex)[:60]
        if rec is not None:
            diag["resolved"] += 1
        else:
            diag["default"] += 1
            key = (reason or "unknown").split(":")[0]
            reasons[key] = reasons.get(key, 0) + 1
            if len(examples) < 8:
                examples.append((mid, val, reason))
        out.append(rec or _default_record(mid))
    lines = ["Blendit materials: %d resolved, %d Default. reasons=%s"
             % (diag["resolved"], diag["default"], reasons)]
    for mid, val, reason in examples:
        lines.append("  FAIL key=%s -> elementid=%s : %s" % (mid, val, reason))
    text = "\n".join(lines)
    try:
        print(text)
    except Exception:
        pass
    # Also write to a fixed temp file so the root cause can be read directly
    # (no need to copy the pyRevit console). Overwritten each extraction.
    try:
        import os
        import tempfile
        p = os.path.join(tempfile.gettempdir(), "blendit_material_diag.txt")
        h = open(p, "w")
        h.write(text)
        h.close()
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
