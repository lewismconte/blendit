"""Appearance-asset reader tests (no Revit, no Blender - pure Python).

    python tests/test_appearance.py

The Revit API is faked with just enough surface for bir_extract.appearance:
assets/properties/connected UnifiedBitmaps, a material and a document. The
checks lock the lessons from BimGo's materials round:

  * Advanced / Physical (Prism) colour slots are read, not just Generic;
  * real-world scale is divided by the texture U/V repeats;
  * resolution finds a texture beside the model and through env/| alternatives;
  * a missing or procedural texture falls back to the material's SHADING colour,
    not the appearance's often-white render colour.
"""
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
_LIB = os.path.join(_ROOT, "lib")
for p in (_ROOT, _LIB):
    if p not in sys.path:
        sys.path.insert(0, p)

from bir_extract import appearance  # noqa: E402

CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append((name, bool(ok)))
    print("  %-58s %s %s" % (name, "OK" if ok else "FAIL", detail))


# --- fake Revit API ----------------------------------------------------------
class _XYZ(object):
    def __init__(self, x, y, z):
        self.X, self.Y, self.Z = x, y, z


class _UnitUtils(object):
    @staticmethod
    def ConvertToInternalUnits(value, unit):
        return float(value)          # test values are already feet


class _ElementId(object):
    InvalidElementId = -1


class _DB(object):
    ElementId = _ElementId
    UnitUtils = _UnitUtils


_ORIG_DB = appearance.DB
appearance.DB = _DB


class _Prop(object):
    def __init__(self, name, value=None, doubles=None, xyz=None, connected=None):
        self.Name = name
        self.Value = value
        self._doubles = doubles
        self._xyz = xyz
        self._connected = list(connected or [])

    def GetValueAsDoubles(self):
        if self._doubles is None:
            raise TypeError("not a colour array")
        return self._doubles

    def GetValueAsXYZ(self):
        if self._xyz is None:
            raise TypeError("not a 3d colour")
        return self._xyz

    def GetUnitTypeId(self):
        return "unit"

    @property
    def NumberOfConnectedProperties(self):
        return len(self._connected)

    def GetSingleConnectedAsset(self):
        return self._connected[0] if self._connected else None


class _Asset(object):
    def __init__(self, name, props):
        self.Name = name
        self._props = list(props)

    @property
    def Size(self):
        return len(self._props)

    def FindByName(self, name):
        for p in self._props:
            if p.Name == name:
                return p
        return None

    def __getitem__(self, i):
        return self._props[i]


class _AppearanceElement(object):
    def __init__(self, asset):
        self._asset = asset

    def GetRenderingAsset(self):
        return self._asset


class _Material(object):
    def __init__(self, name, asset):
        self.Name = name
        self.AppearanceAssetId = 1
        self._asset = asset

    def GetRenderingAsset(self):
        return self._asset


class _Application(object):
    VersionNumber = "2025"


class _Doc(object):
    def __init__(self, path, asset):
        self.PathName = path
        self.Application = _Application()
        self._asset = asset

    def GetElement(self, aid):
        return _AppearanceElement(self._asset)


def _bitmap(raw, sx=1.0, sy=1.0, us=1.0, vs=1.0, angle=0.0,
            tint=None, invert=False, rgb_amount=None):
    props = [
        _Prop("unifiedbitmap_Bitmap", value=raw),
        _Prop("texture_RealWorldScaleX", value=sx),
        _Prop("texture_RealWorldScaleY", value=sy),
        _Prop("texture_UScale", value=us),
        _Prop("texture_VScale", value=vs),
        _Prop("texture_WAngle", value=angle),
    ]
    if tint:
        props.append(_Prop("common_Tint_toggle", value=True))
        props.append(_Prop("common_Tint_color", doubles=list(tint)))
    if invert:
        props.append(_Prop("unifiedbitmap_Invert", value=True))
    if rgb_amount is not None:
        props.append(_Prop("unifiedbitmap_RGBAmount", value=rgb_amount))
    return _Asset("UnifiedBitmap", props)


def _write(path, data=b"png"):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    f = open(path, "wb")
    try:
        f.write(data)
    finally:
        f.close()


def main():
    work = tempfile.mkdtemp(prefix="blendit_appearance_")
    model = os.path.join(work, "Project.rvt")
    _write(model, b"rvt")
    tex = os.path.join(work, "textures", "brick_%s.png" % os.getpid())
    _write(tex)

    # --- 1. Advanced/Prism slot + UScale/VScale + roughness -------------------
    appearance.reset_stats()
    appearance.reset_texture_cache()
    diffuse = _Prop("opaque_albedo", doubles=[0.12, 0.22, 0.32],
                    connected=[_bitmap("textures/" + os.path.basename(tex),
                                       sx=2.0, sy=1.0, us=2.0, vs=1.0,
                                       angle=45.0, tint=[0.5, 1.0, 1.0],
                                       invert=True, rgb_amount=2.0)])
    asset = _Asset("PrismOpaque", [
        _Prop("BaseSchema", value="PrismOpaqueSchema"),
        _Prop("common_Tint_toggle", value=True),
        _Prop("common_Tint_color", doubles=[0.5, 0.5, 0.5]),
        diffuse,
        _Prop("surface_roughness", value=0.25),
    ])
    rec = appearance.read_appearance(_Doc(model, asset), _Material("Brick", asset),
                                     shading_color=[0.2, 0.3, 0.4])
    check("Advanced slot read (opaque_albedo colour)",
          rec.get("base_color") == [0.06, 0.11, 0.16], str(rec.get("base_color")))
    check("Advanced schema classified as generic",
          rec.get("appearance_class") == "generic", rec.get("appearance_class"))
    d = (rec.get("maps") or {}).get("diffuse") or {}
    check("UScale divides the real-world size",
          abs(d.get("scale_m", [0, 0])[0] - 0.3048) < 1e-6,
          str(d.get("scale_m")))
    check("VScale keeps the V size",
          abs(d.get("scale_m", [0, 0])[1] - 0.3048) < 1e-6)
    check("texture resolved beside the model",
          d.get("source_path") == tex, d.get("source_path"))
    check("rotation read", abs(d.get("rotation_deg", 0) - 45.0) < 1e-6)
    check("image + appearance tint multiply",
          d.get("tint") is not None and
          abs(d["tint"][0] - 0.5) < 1e-6 and abs(d["tint"][1] - 1.0) < 1e-6,
          str(d.get("tint")))
    check("inverted bitmap flagged", d.get("invert") is True)
    check("surface_roughness wins",
          abs(rec.get("roughness", -1) - 0.25) < 1e-6, str(rec.get("roughness")))

    # --- 1b. Generic image fade + appearance tint on plain colour ------------
    appearance.reset_stats()
    fade_asset = _Asset("Generic", [
        _Prop("BaseSchema", value="GenericSchema"),
        _Prop("generic_diffuse", doubles=[0.8, 0.8, 0.8],
              connected=[_bitmap("textures/" + os.path.basename(tex))]),
        _Prop("generic_diffuse_image_fade", value=0.4),
    ])
    rec = appearance.read_appearance(_Doc(model, fade_asset),
                                     _Material("Paint", fade_asset))
    check("image fade read",
          abs((rec.get("maps", {}).get("diffuse") or {}).get("fade", 1) - 0.4) < 1e-6)

    plain_asset = _Asset("Generic", [
        _Prop("BaseSchema", value="GenericSchema"),
        _Prop("generic_diffuse", doubles=[0.8, 0.8, 0.8]),
        _Prop("common_Tint_toggle", value=True),
        _Prop("common_Tint_color", doubles=[0.5, 0.5, 0.5]),
    ])
    rec = appearance.read_appearance(_Doc(model, plain_asset),
                                     _Material("Plain", plain_asset))
    check("appearance tint multiplies a plain colour",
          all(abs(v - 0.4) < 1e-6 for v in rec.get("base_color", [])),
          str(rec.get("base_color")))

    # --- 2. missing texture -> shading colour --------------------------------
    appearance.reset_stats()
    missing = "blendit_missing_%s.png" % os.getpid()
    asset = _Asset("Generic", [
        _Prop("BaseSchema", value="GenericSchema"),
        _Prop("generic_diffuse", doubles=[1.0, 1.0, 1.0],
              connected=[_bitmap(missing)]),
    ])
    rec = appearance.read_appearance(_Doc(model, asset), _Material("Plaster", asset),
                                     shading_color=[0.2, 0.3, 0.4])
    check("missing texture falls back to the shading colour",
          rec.get("base_color") == [0.2, 0.3, 0.4], str(rec.get("base_color")))
    check("missing texture leaves no map", not (rec.get("maps") or {}).get("diffuse"))
    check("missing texture counted", appearance._STATS["missing"] == 1,
          str(appearance._STATS))

    # --- 3. procedural slot -> shading colour --------------------------------
    appearance.reset_stats()
    asset = _Asset("Generic", [
        _Prop("BaseSchema", value="GenericSchema"),
        _Prop("generic_diffuse", doubles=[1.0, 1.0, 1.0],
              connected=[_Asset("Noise", [])]),
    ])
    rec = appearance.read_appearance(_Doc(model, asset), _Material("NoiseWall", asset),
                                     shading_color=[0.5, 0.4, 0.3])
    check("procedural slot falls back to the shading colour",
          rec.get("base_color") == [0.5, 0.4, 0.3])
    check("procedural counted", appearance._STATS["procedural"] == 1)

    # --- 4. | alternatives + environment variable ----------------------------
    appearance.reset_texture_cache()
    os.environ["BLENDIT_TEST_TEXTURES"] = os.path.join(work, "textures")
    raw = "Z:\\nowhere\\nope.png|%BLENDIT_TEST_TEXTURES%\\" + os.path.basename(tex)
    got = appearance._resolve_texture_path(raw, _Doc(model, None))
    check("environment variable and | alternative resolve", got == tex, str(got))

    # --- 5. schema classes ----------------------------------------------------
    for schema, klass in (("MirrorSchema", "mirror"),
                          ("PrismMetalSchema", "metal"),
                          ("PrismTransparentSchema", "glass"),
                          ("LayeredSchema", "generic")):
        appearance.reset_stats()
        a = _Asset("x", [_Prop("BaseSchema", value=schema)])
        r = appearance.read_appearance(_Doc(model, a), _Material("m", a))
        check("schema %s -> %s" % (schema, klass), r.get("appearance_class") == klass,
              r.get("appearance_class"))
        if klass == "mirror":
            check("mirror gets metallic + sharp",
                  r.get("metallic") == 1.0 and r.get("roughness") == 0.05)

    appearance.reset_stats()
    a = _Asset("Plate", [_Prop("BaseSchema", value="GenericSchema"),
                        _Prop("generic_is_metal", value=True)])
    r = appearance.read_appearance(_Doc(model, a), _Material("Plate", a))
    check("Generic generic_is_metal -> metallic",
          r.get("metallic") == 1.0, str(r.get("metallic")))

    failed = [n for n, ok in CHECKS if not ok]
    appearance.DB = _ORIG_DB
    print("APPEARANCE: %d checks, %d failed%s"
          % (len(CHECKS), len(failed), (" -> " + ", ".join(failed)) if failed else ""))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
