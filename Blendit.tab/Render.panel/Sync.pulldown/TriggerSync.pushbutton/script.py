# -*- coding: utf-8 -*-
"""Collect edits quietly and push them only when you press Sync Now - the
controlled, low-distraction link: do a batch of edits, then sync once."""
__title__ = "Trigger\nSync"
__author__ = "Blendit"

import bir_bootstrap
bir_bootstrap.ensure_paths()
import bir_sync
import bir_ui

bir_sync.set_mode(__revit__, "trigger", report=bir_ui.report)
