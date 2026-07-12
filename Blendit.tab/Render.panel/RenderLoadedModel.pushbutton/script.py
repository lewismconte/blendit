# -*- coding: utf-8 -*-
"""Render the LOADED view as-is, headless (no interactive Blender).

Renders the view you've already loaded - the whole view, in the configured
Mode / Quality / Resolution - in the background. Use this when you just want a
straight render of the current view without composing in Blender; for a chosen
shot, use **Open View** and render from the N-panel instead.

Honest by design: this can take a while on a large model (Cycles especially), but
Revit stays free and the image opens when it's done. You can't render a view that
isn't loaded - press **Load View** first.

Shift+Click: the same render at FINAL quality (Cycles, high samples, denoised)
- liked the draft? One click gets the keeper, without touching your Quality
setting.
"""
__title__ = "Render\nView"
__author__ = "Blendit"

import bir_bootstrap
bir_bootstrap.ensure_paths()
import bir_config
from bir_ui import (report as _report, launch_headless_render,
                    dismiss_output as _dismiss_output)


if launch_headless_render(bir_config.load(), _report):
    _dismiss_output(12)     # render continues detached; the PNG opens itself
