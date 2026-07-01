# -*- coding: utf-8 -*-
"""Render the LOADED model as-is, headless (no interactive Blender).

Renders the model you've already loaded - the whole view, in the configured
Mode / Quality / Resolution - in the background. Use this when you just want a
straight render of the current view without composing in Blender; for a chosen
shot, use **Open Model** and render from the N-panel instead.

Honest by design: this can take a while on a large model (Cycles especially), but
Revit stays free and the image opens when it's done. You can't render a model that
isn't loaded - press **Load Model** first.
"""
__title__ = "Render\nLoaded"
__author__ = "Blendit"

import os
import subprocess

import bir_bootstrap
bir_bootstrap.ensure_paths()
import bir_config
from bir_contract.transport import stamped_name
from bir_ui import (report as _report, active_doc as _active_doc,
                    ensure_blender as _ensure_blender,
                    require_loaded as _require_loaded)


def main():
    cfg = bir_config.load()
    blender = _ensure_blender(cfg, _report)
    if not blender:
        return
    doc = _active_doc()
    bundle_ref, _blend = _require_loaded(doc)       # error popup if not loaded
    if bundle_ref is None:
        return

    res = cfg.get("resolution", [1600, 900])
    _report("**Blendit - Render Loaded Model**  \n"
            "mode **%s** | engine **%s** | %sx%s | %s samples%s"
            % (cfg.get("mode"), cfg.get("engine"), res[0], res[1],
               cfg.get("samples"), " | denoise" if cfg.get("denoise") else ""))

    out_dir = cfg.get("output_dir") or bir_bootstrap.default_output_dir()
    if not os.path.isdir(out_dir):
        try:
            os.makedirs(out_dir)
        except Exception:
            pass
    png = os.path.join(out_dir, stamped_name("render", "png"))
    log_path = os.path.join(out_dir, "render.log")
    render_py = bir_bootstrap.render_script_path()
    # --open: Blender opens the PNG itself when done, so Revit isn't blocked waiting
    # on the (possibly minutes-long) render.
    # The cached bundle is a pure geometry cache: the CURRENT config rides along as
    # CLI overrides, so Mode / Quality / Resolution / Engine changes made after
    # Load Model take effect without a re-Load.
    cmd = [blender, "--background", "--python", render_py, "--",
           "--bundle", bundle_ref, "--out", png, "--open",
           "--mode", str(cfg.get("mode") or "realistic"),
           "--engine", str(cfg.get("engine") or "EEVEE"),
           "--samples", str(cfg.get("samples") or 64),
           "--resolution", str(res[0]), str(res[1]),
           "--denoise", "on" if cfg.get("denoise") else "off"]

    try:
        logf = open(log_path, "wb")
        subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT)
    except OSError as ex:
        _report("**ERROR** launching Blender: %s\n\n"
                "Set the Blender path in Settings (or BLENDIT_BLENDER_EXE)." % ex)
        return

    _report("- rendering the loaded model in the background (this can take a while "
            "for a large model) - **Revit is free to use.** The image opens when "
            "it's done.\n- output: `%s`\n- log (if it fails): `%s`" % (png, log_path))


main()
