# -*- coding: utf-8 -*-
"""Resolution quick-pick: 720p / 1080p / 1440p / 4K (custom lives in Settings)."""
__title__ = "Resolution"
__author__ = "Blendit"

import bir_bootstrap
bir_bootstrap.ensure_paths()
import bir_config


def main():
    from pyrevit import forms
    cur = bir_config.get_value("resolution", [1600, 900])
    labels = [r[0] for r in bir_config.RESOLUTIONS]
    choice = forms.CommandSwitchWindow.show(
        labels, message="Output resolution (now: %sx%s)" % (cur[0], cur[1]))
    if not choice:
        return
    for label, res in bir_config.RESOLUTIONS:
        if label == choice:
            bir_config.set_value("resolution", res)
            forms.alert("Resolution: %s  (%sx%s)" % (label, res[0], res[1]),
                        title="Blendit - Resolution")
            break


main()
