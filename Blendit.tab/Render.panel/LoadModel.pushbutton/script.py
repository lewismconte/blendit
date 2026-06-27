# -*- coding: utf-8 -*-
"""Load the active 3D view into Blendit's model cache.

This is the one slow step (it tessellates the whole view), so it is explicit and
shows a progress bar - no surprise long operations hidden behind a render button.
It does NOT open Blender; once loaded, use **Open Model** to view it interactively
or **Render Loaded Model** to render it headless. Re-run after you change the model.
"""
__title__ = "Load\nModel"
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
    _report("**Blendit - Load Model** - extracting the active 3D view. This can take "
            "a while on a large model; the progress bar shows it working.")

    bundle_ref, _blend = bir_export.refresh_cache(doc, cfg, _report)

    _report("- **model loaded.** Now press **Open Model** to view it in Blender, or "
            "**Render Loaded Model** to render it as-is.\n- cache: `%s`" % bundle_ref)


main()
