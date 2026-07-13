# -*- coding: utf-8 -*-
"""Stop listening for model changes entirely - zero overhead, no surprises.
The default state; Load / Open / Render keep working as always."""
__title__ = "Sync\nOff"
__author__ = "Blendit"

import bir_bootstrap
bir_bootstrap.ensure_paths()
import bir_sync
import bir_ui

bir_sync.set_mode(__revit__, "off", report=bir_ui.report)
