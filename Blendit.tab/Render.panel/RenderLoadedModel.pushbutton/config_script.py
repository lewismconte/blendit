# -*- coding: utf-8 -*-
"""Shift+Click variant of Render Loaded Model: the same render at FINAL
quality (Cycles, high samples, denoised). The 'that draft, but better'
one-click - your saved Quality setting is untouched."""

import bir_bootstrap
bir_bootstrap.ensure_paths()
import bir_config
from bir_ui import report as _report, launch_headless_render


cfg = bir_config.load()
cfg.update(bir_config.QUALITY["Final"])   # engine + samples + denoise only
launch_headless_render(cfg, _report,
                       banner="Render Loaded Model at FINAL quality")
