# -*- coding: utf-8 -*-
"""Stream edits to the open Blender session automatically: changes are
collected as you work and pushed each time Revit goes idle. Open the view
with Open View first so a session is listening."""
__title__ = "Live\nSync"
__author__ = "Blendit"

import bir_bootstrap
bir_bootstrap.ensure_paths()
import bir_sync
import bir_ui

bir_sync.set_mode(__revit__, "live", report=bir_ui.report)
