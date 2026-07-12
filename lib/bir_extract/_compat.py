"""Small RevitAPI compat helpers (IronPython 2.7 safe).

RevitAPI import is GUARDED so the extract package imports cleanly outside Revit
(the guardrail: Revit-side code must be testable headless). `DB` is None when not
running inside Revit; the extractor functions only touch it when actually called.
"""
try:
    from Autodesk.Revit import DB
    _HAVE_REVIT = True
except Exception:
    DB = None
    _HAVE_REVIT = False


def have_revit():
    return _HAVE_REVIT


def id_value(eid):
    # ElementId.Value (Revit 2024+) or .IntegerValue (older). -> int / long
    try:
        return eid.Value
    except Exception:
        return eid.IntegerValue


def make_element_id(val):
    # Revit 2024+ added ElementId(System.Int64) alongside the ENUM constructors
    # ElementId(BuiltInParameter) / ElementId(BuiltInCategory). Passing a bare
    # Python int is then AMBIGUOUS under IronPython - it raises "Multiple targets
    # could match" - so every doc.GetElement(make_element_id(id)) threw and every
    # material silently fell back to flat grey (the all-white-render bug). Cast to
    # an explicit .NET integer so the numeric overload is chosen; fall back to
    # Int32 for older Revit that lacks the Int64 constructor.
    try:
        from System import Int64
        return DB.ElementId(Int64(val))
    except Exception:
        from System import Int32
        return DB.ElementId(Int32(val))


def srgb_to_linear(c):
    # Revit display colors are sRGB-ish; the contract wants linear 0..1.
    c = max(0.0, min(1.0, float(c)))
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4
