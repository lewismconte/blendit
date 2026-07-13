# -*- coding: utf-8 -*-
"""Load the active view into Blendit's model cache.

Works on a **3D view** OR a **plan / section / elevation** - a 2D view loads as a
scale-true orthographic drawing (framed to its crop, cut at its view range) that you
can render straight away or refine in Open View.

This is the one slow step (it tessellates the whole view), so it is explicit and
shows a progress bar - no surprise long operations hidden behind a render button.
It does NOT open Blender; once loaded, use **Open View** to work it interactively
or **Render View** to render it headless. Re-run after you change the model.
"""
__title__ = "Load\nView"
__author__ = "Blendit"

import bir_bootstrap
bir_bootstrap.ensure_paths()
import bir_config
import bir_export
from bir_ui import (report as _report, active_doc as _active_doc,
                    ensure_loadable_view as _ensure_loadable_view,
                    dismiss_output as _dismiss_output,
                    launch_cache_build as _launch_cache_build)


def main():
    cfg = bir_config.load()
    doc = _active_doc()
    if not _ensure_loadable_view(doc, _report):   # 3D view or a 2D plan/section/elev
        return
    _report("**Blendit - Load View** - extracting the active view. This can take "
            "a while on a large model; the progress bar shows it working.")

    bundle_ref, blend_path = bir_export.refresh_cache(doc, cfg, _report)

    msg = ("- **view loaded.** Now press **Open View** to work it in Blender, or "
           "**Render View** to render it as-is.\n- cache: `%s`" % bundle_ref)
    # Build the fast-open scene cache NOW, in the background - the import +
    # merge is Open View's slow step, so it's usually done before the user is.
    if _launch_cache_build(cfg, bundle_ref, blend_path):
        msg += ("\n- preparing the fast-open scene in the background - "
                "**Open View** will be quick once it's ready (the **Views** "
                "list shows *scene building...* until then).")
    _report(msg)
    _dismiss_output(10)     # info only - the window closes itself


main()
