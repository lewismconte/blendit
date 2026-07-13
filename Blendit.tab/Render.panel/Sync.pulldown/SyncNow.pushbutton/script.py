# -*- coding: utf-8 -*-
"""Push the changes collected since the last sync (the Trigger Sync flush;
also works as a manual nudge while Live Sync is on)."""
__title__ = "Sync\nNow"
__author__ = "Blendit"

import bir_bootstrap
bir_bootstrap.ensure_paths()
import bir_sync
import bir_ui

bir_sync.sync_now(__revit__, report=bir_ui.report)
