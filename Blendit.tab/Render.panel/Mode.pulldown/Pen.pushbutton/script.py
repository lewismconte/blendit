# -*- coding: utf-8 -*-
"""Set the render mode to Pen (Rhino-style technical pen: white fill, black lines)."""
__title__ = "Pen"
__author__ = "Blendit"

import bir_bootstrap
bir_bootstrap.ensure_paths()
import bir_ui

bir_ui.set_mode("pen")
