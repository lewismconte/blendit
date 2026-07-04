# -*- coding: utf-8 -*-
"""Load the active view into Blendit's model cache.

Works on a **3D view** OR a **plan / section / elevation** - a 2D view loads as a
scale-true orthographic drawing (framed to its crop, cut at its view range) that you
can render straight away or refine in Open View.

This is the one slow step (it tessellates the whole view), so it is explicit and
shows a progress bar - no surprise long operations hidden behind a render button.
It does NOT open Blender; once loaded, use **Open View** to work it interactively
or **Render Loaded** to render it headless. Re-run after you change the model.
"""
__title__ = "Load\nView"
__author__ = "Blendit"

import bir_bootstrap
bir_bootstrap.ensure_paths()
import bir_config
import bir_export
from bir_ui import (report as _report, active_doc as _active_doc,
                    ensure_3d_view as _ensure_3d_view)


def main():
    cfg = bir_config.load()
    doc = _active_doc()
    if not _ensure_3d_view(doc, _report):     # need a 3D view to extract
        return
    _report("**Blendit - Load View** - extracting the active 3D view. This can take "
            "a while on a large model; the progress bar shows it working.")

    bundle_ref, _blend = bir_export.refresh_cache(doc, cfg, _report)

    _report("- **view loaded.** Now press **Open View** to work it in Blender, or "
            "**Render Loaded** to render it as-is.\n- cache: `%s`" % bundle_ref)


main()
