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

import bir_bootstrap
bir_bootstrap.ensure_paths()
import bir_config
from bir_ui import (report as _report, active_doc as _active_doc,
                    require_loaded as _require_loaded,
                    launch_open_view as _launch_open_view,
                    dismiss_output as _dismiss_output)


def main():
    cfg = bir_config.load()
    doc = _active_doc()
    bundle_ref, blend_path = _require_loaded(doc)   # error popup if not loaded
    if bundle_ref is None:
        return
    if _launch_open_view(cfg, _report, bundle_ref, blend_path):
        _dismiss_output(10)     # info only - the window closes itself


main()
