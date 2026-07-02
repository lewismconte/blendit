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

# SILENT by design: pyRevit pops an output window for anything a startup
# script prints, on every reload. Breadcrumbs go to the debug logger instead
# (visible only in pyRevit debug mode).
try:
    from pyrevit.coreutils import logger as _pyrevit_logger
    _log = _pyrevit_logger.get_logger("Blendit.startup")
except Exception:
    _log = None

try:
    import bir_ui
    bir_ui.ensure_mode_tooltips(force=True)
    if _log:
        _log.debug("mode previews attached to the ribbon tooltips")
except Exception as ex:
    if _log:
        _log.debug("tooltip decoration skipped (%s)" % ex)
