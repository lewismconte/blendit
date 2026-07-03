# -*- coding: utf-8 -*-
"""Open the loaded view in an interactive Blender session (real-time navigation).

Opens the view you've already loaded (press **Load View** first). Fly around,
frame your shot, pose 2D plans / elevations, and render from the 'Blendit' N-panel
(press N in Blender) - Capture for a quick grab, Render Final for a high-quality one.
Reopening is fast: it uses the prepared scene cache, so no re-import.

You can't open a view that isn't loaded - if none is, you'll be told to Load first.
"""
__title__ = "Open\nView"
__author__ = "Blendit"

import os
import subprocess

import bir_bootstrap
bir_bootstrap.ensure_paths()
import bir_config
from bir_ui import (report as _report, active_doc as _active_doc,
                    ensure_blender as _ensure_blender,
                    require_loaded as _require_loaded)


def main():
    cfg = bir_config.load()
    blender = _ensure_blender(cfg, _report)
    if not blender:
        return
    doc = _active_doc()
    bundle_ref, blend_path = _require_loaded(doc)   # error popup if not loaded
    if bundle_ref is None:
        return

    live_py = bir_bootstrap.live_script_path()
    cap_dir = cfg.get("output_dir") or bir_bootstrap.default_output_dir()
    # Force EEVEE for a responsive realtime viewport. --save-blend builds/refreshes
    # the fast-open cache; --blend opens it directly when it already exists.
    # Open in White/Clay (fast, robust for composing) - switch to any mode live from
    # the N-panel. The render-mode config drives Render Loaded finals.
    cmd = [blender, "--python", live_py, "--",
           "--bundle", bundle_ref, "--save-blend", blend_path,
           "--capture-dir", cap_dir,
           "--engine", "EEVEE", "--mode", "white"]
    if os.path.isfile(blend_path):
        cmd += ["--blend", blend_path]
        _report("**Blendit** - opening the loaded view (fast: cached scene)")
    else:
        _report("**Blendit** - opening the loaded view (first open builds the "
                "fast-open cache)")
    _report("- launching Blender... Navigate to compose, **Enter** to capture, "
            "**F10** for the full Blender interface.")

    try:
        # Detached: do NOT wait. Blender stays open; Revit is not blocked.
        subprocess.Popen(cmd)
    except OSError as ex:
        _report("**ERROR** launching Blender: %s\n\n"
                "Set the Blender path in Settings (or BLENDIT_BLENDER_EXE)." % ex)


main()
