# -*- coding: utf-8 -*-
"""Set the render mode to Specular / Lookdev (emphasize reflectivity + roughness)."""
__title__ = "Specular"
__author__ = "Blendit"

import bir_bootstrap
bir_bootstrap.ensure_paths()
import bir_ui

bir_ui.set_mode("specular")
