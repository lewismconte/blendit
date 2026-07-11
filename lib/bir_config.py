"""User config for Blendit (IronPython 2.7 safe).

Stored as JSON at %APPDATA%\\blendit\\config.json. Shared by the
Settings / Mode / Engine ribbon buttons (writers) and the render button (reader).
Every accessor is exception-safe so a missing/corrupt config never breaks a button.
"""
import os

_DEFAULTS = {
    "blender_exe": "",          # empty -> auto-detect via bir_bootstrap
    "output_dir": "",           # empty -> bir_bootstrap.default_output_dir()
    # realistic | white | shadow | specular | linework | pen | sketch | cel | hatch
    "mode": "realistic",
    "engine": "EEVEE",          # EEVEE | CYCLES
    "samples": 64,
    "denoise": True,            # OpenImageDenoise (Cycles) / temporal AA (EEVEE)
    "resolution": [1600, 900],
}

# Shared catalogs so the ribbon buttons and Settings present the same choices.
# Must list every contract render mode: tests/test_contract.py locks this against
# scene_spec.RENDER_MODES so the Revit UI can't silently miss a mode again.
MODES = ["realistic", "white", "shadow", "specular",
         "linework", "pen", "sketch", "cel", "hatch", "crosshatch",
         "yellowtrace", "kraft", "blueprint",
         "diagram", "watercolor", "risograph"]
MODE_LABELS = {
    "realistic": "Realistic", "white": "White / Clay", "shadow": "Shadow study",
    "specular": "Specular", "linework": "Linework", "pen": "Pen",
    "sketch": "Sketch", "cel": "Cel / Anime", "hatch": "Hatch",
    "crosshatch": "Crosshatch", "yellowtrace": "Yellowtrace",
    "kraft": "Brown Paper", "blueprint": "Blueprint", "diagram": "Diagram",
    "watercolor": "Watercolor", "risograph": "Risograph",
}
RESOLUTIONS = [("720p", [1280, 720]), ("1080p", [1920, 1080]),
               ("1440p", [2560, 1440]), ("4K", [3840, 2160])]
# Quality presets bundle engine + samples + denoise for one-click effort control.
QUALITY = {
    "Draft":    {"engine": "EEVEE",  "samples": 16,  "denoise": False},
    "Standard": {"engine": "EEVEE",  "samples": 64,  "denoise": True},
    "High":     {"engine": "CYCLES", "samples": 128, "denoise": True},
    "Final":    {"engine": "CYCLES", "samples": 512, "denoise": True},
}


def _config_dir():
    base = os.environ.get("APPDATA") or os.environ.get("TEMP") or "."
    d = os.path.join(base, "blendit")
    if not os.path.isdir(d):
        try:
            os.makedirs(d)
        except Exception:
            pass
    return d


def _config_path():
    return os.path.join(_config_dir(), "config.json")


def defaults():
    return dict(_DEFAULTS)


def load():
    cfg = dict(_DEFAULTS)
    try:
        from bir_contract.transport import read_json
        data = read_json(_config_path())     # UTF-8 (paths may carry accents)
        if isinstance(data, dict):
            cfg.update(data)
    except Exception:
        pass
    return cfg


def save(cfg):
    """Write the config. Returns True on success, False when the file couldn't
    be written (locked / read-only) so callers can tell the user instead of
    silently confirming a change that never persisted."""
    try:
        from bir_contract.transport import write_json
        write_json(_config_path(), cfg)      # UTF-8 (paths may carry accents)
        return True
    except Exception:
        return False


def get_value(key, default=None):
    val = load().get(key)
    if val is None:
        return default if default is not None else _DEFAULTS.get(key)
    return val


def set_value(key, value):
    """Set one key and persist. Returns save()'s success flag."""
    cfg = load()
    cfg[key] = value
    return save(cfg)
