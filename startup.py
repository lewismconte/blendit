# -*- coding: utf-8 -*-
"""Blendit extension startup (run by pyRevit when the extension loads).

Decorates the ribbon: attaches each Mode button's preview image
(media/modes/<mode>.png) to its hover tooltip - hover a mode to SEE what it
looks like - and reflects the saved default mode in the Mode pulldown's
tooltip. Best-effort only: tooltip decoration must never break the ribbon
load, and bir_ui.ensure_mode_tooltips re-runs on first mode use in case this
executes before the ribbon items exist.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
for _p in (_ROOT, os.path.join(_ROOT, "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import bir_ui
    bir_ui.ensure_mode_tooltips(force=True)
    print("Blendit startup: mode previews attached to the ribbon tooltips")
except Exception as ex:
    print("Blendit startup: tooltip decoration skipped (%s)" % ex)
