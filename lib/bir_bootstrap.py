"""Revit-side bootstrap helpers (IronPython 2.7 safe).

Resolves the things the pushbutton needs from the pyRevit environment:
  * put the repo's `bir_contract/` package on sys.path (it lives at the repo
    root, outside the extension's auto-added lib/) -- the single-source-of-truth
    way for the Revit side to reach the seam, instead of vendoring transport.py.
  * locate `blender.exe` and the headless render script.
  * pick an output directory for the bundle + PNG.

No RevitAPI imports here, so this imports cleanly outside Revit.
"""
import glob
import hashlib
import os
import sys
import tempfile

_LIB_DIR = os.path.dirname(os.path.abspath(__file__))
# The repo root IS the extension root (.tab at root, for the pyRevit catalog):
# lib/ + blender/ + bir_contract/ all live one level up from lib/.
REPO_ROOT = os.path.abspath(os.path.join(_LIB_DIR, ".."))


def ensure_paths():
    """Make `bir_contract` and the extension's `bir_transports` importable.

    All Blendit packages exposed to pyRevit's SHARED sys.path carry the bir_
    prefix, so they can never collide with (or shadow) another extension's
    generically-named packages in the same IronPython engine."""
    for p in (REPO_ROOT, _LIB_DIR):
        if p not in sys.path:
            sys.path.insert(0, p)


def render_script_path():
    return os.path.join(REPO_ROOT, "blender", "headless", "render.py")


def live_script_path():
    return os.path.join(REPO_ROOT, "blender", "interactive", "live.py")


def prepare_cache_script_path():
    return os.path.join(REPO_ROOT, "blender", "headless", "prepare_cache.py")


def windowed_blender_exe(blender_exe):
    """The console-free launcher for a WINDOWED Blender session: Blender ships
    blender-launcher.exe next to blender.exe precisely so the app can start
    without the black cmd window (it forwards all arguments). Falls back to the
    given exe when the launcher isn't there (old/portable installs)."""
    try:
        launcher = os.path.join(os.path.dirname(blender_exe),
                                "blender-launcher.exe")
        if os.path.isfile(launcher):
            return launcher
    except Exception:
        pass
    return blender_exe


def find_blender_exe():
    """A real, existing blender.exe path, or None.

    Env BLENDIT_BLENDER_EXE wins; then common Windows install dirs (highest version
    last); then probe each PATH entry. Returns None when nothing is found, so callers
    can warn the user BEFORE doing slow work instead of failing at launch."""
    env = os.environ.get("BLENDIT_BLENDER_EXE")
    if env and os.path.isfile(env):
        return env
    found = []
    for pat in (r"C:\Program Files\Blender Foundation\Blender *\blender.exe",
                r"C:\Program Files\Blender Foundation\Blender\blender.exe"):
        found.extend(glob.glob(pat))
    if found:
        found.sort()                      # highest version string last
        return found[-1]
    for entry in (os.environ.get("PATH") or "").split(os.pathsep):
        entry = entry.strip().strip('"')
        if not entry:
            continue
        cand = os.path.join(entry, "blender.exe")
        if os.path.isfile(cand):
            return cand
    return None


def resolve_blender_exe():
    """Back-compat: a real path if found, else the bare name 'blender' (resolved on
    PATH at launch). Prefer find_blender_exe() + the bir_ui.ensure_blender pre-flight,
    which warns the user up front instead of failing inside subprocess."""
    return find_blender_exe() or "blender"


def default_output_dir():
    d = os.path.join(tempfile.gettempdir(), "blendit")
    if not os.path.isdir(d):
        os.makedirs(d)
    return d


# --- model cache (so Open View / Render reuse the last Load) ----------------
def cache_root():
    """Stable per-user cache for extracted bundles + prepared .blend scenes.
    LOCALAPPDATA (not temp, not the Pictures render folder) so it survives reboots
    but stays out of the user's documents."""
    base = (os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
            or tempfile.gettempdir())
    d = os.path.join(base, "blendit", "cache")
    if not os.path.isdir(d):
        try:
            os.makedirs(d)
        except Exception:
            pass
    return d


def cache_dir_for(key):
    d = os.path.join(cache_root(), key)
    if not os.path.isdir(d):
        try:
            os.makedirs(d)
        except Exception:
            pass
    return d


def clear_cache():
    """Delete every cached model extraction + prepared .blend scene. Returns
    (removed, failed) counts; a slot that can't be deleted (in use by an open
    Blender session / running render) is skipped and counted as failed."""
    import shutil
    root = cache_root()
    removed, failed = 0, 0
    try:
        entries = os.listdir(root)
    except Exception:
        return 0, 0
    for name in entries:
        p = os.path.join(root, name)
        try:
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
            removed += 1
        except Exception:
            failed += 1
    return removed, failed


def view_cache_key(view):
    """A stable, filesystem-safe cache key for one VIEW of a document: a hash of
    the view's UniqueId ONLY (no name part), so a view keeps its slot when it's
    renamed and two views with the same name never collide. The readable name
    lives in the slot's fingerprint.json (what the Views list shows). Duck-typed
    + guarded like doc_cache_key."""
    uid = ""
    try:
        uid = str(view.UniqueId or "")
    except Exception:
        pass
    if not uid:
        try:
            uid = str(view.Name or "")
        except Exception:
            pass
    raw = uid or "view"
    try:
        digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]
    except Exception:
        digest = hashlib.md5(str(raw)).hexdigest()[:12]
    return "view_%s" % digest


def doc_cache_key(doc):
    """A stable, filesystem-safe cache key for a Revit document: a readable name
    prefix + a hash of the full path, so two models never share a cache slot and
    re-opening the same model finds its cache. No Revit API import - just reads
    attributes off the passed doc, guarded for headless/None."""
    raw = ""
    for attr in ("PathName", "Title"):
        try:
            val = getattr(doc, attr, None)
            if val:
                raw = str(val)
                break
        except Exception:
            pass
    if not raw:
        raw = "default"
    try:
        digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]
    except Exception:
        digest = hashlib.md5(str(raw)).hexdigest()[:8]
    name = os.path.basename(raw) or "model"
    safe = "".join(c for c in name if c.isalnum() or c in "._-")[:40] or "model"
    return "%s_%s" % (safe, digest)
