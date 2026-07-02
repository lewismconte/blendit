# -*- coding: utf-8 -*-
"""Quality preset quick-pick: one click sets engine + samples + denoise together.

Draft   = EEVEE, few samples, no denoise   (fast previews)
Standard= EEVEE, denoised                  (the everyday default)
High    = Cycles, denoised                  (good finals)
Final   = Cycles, many samples, denoised    (best quality, slow)
"""
__title__ = "Quality"
__author__ = "Blendit"

import bir_bootstrap
bir_bootstrap.ensure_paths()
import bir_config
import bir_ui


def main():
    from pyrevit import forms
    order = ["Draft", "Standard", "High", "Final"]
    cur = bir_config.load()
    choice = forms.CommandSwitchWindow.show(
        order, message="Render quality (engine + samples + denoise) - now: %s / %s smp"
        % (cur.get("engine"), cur.get("samples")))
    if not choice:
        return
    preset = bir_config.QUALITY[choice]
    cfg = bir_config.load()
    cfg.update(preset)
    if bir_config.save(cfg):
        # The user just chose from a dialog; don't make them dismiss another.
        bir_ui.toast("Quality: %s  -  %s, %s samples, denoise %s"
                     % (choice, preset["engine"], preset["samples"],
                        "on" if preset["denoise"] else "off"))
    else:
        forms.alert("Couldn't save the quality preset (is the config file "
                    "locked?). Nothing was changed.", title="Blendit - Quality")


main()
