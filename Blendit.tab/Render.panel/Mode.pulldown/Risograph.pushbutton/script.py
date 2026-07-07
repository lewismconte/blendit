# -*- coding: utf-8 -*-
"""Set the render mode to Risograph (a two-tone riso print with a blue keyline)."""
__title__ = "Risograph"
__author__ = "Blendit"

import bir_bootstrap
bir_bootstrap.ensure_paths()
import bir_ui

bir_ui.set_mode("risograph")
