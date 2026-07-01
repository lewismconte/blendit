# -*- coding: utf-8 -*-
"""Toggle the render engine for the next render: EEVEE <-> CYCLES.

EEVEE = fast / realtime feel; CYCLES = accurate final render.
"""
__title__ = "Engine"
__author__ = "Blendit"

import bir_bootstrap
bir_bootstrap.ensure_paths()
import bir_config


def main():
    cur = str(bir_config.get_value("engine", "EEVEE")).upper()
    new = "CYCLES" if cur == "EEVEE" else "EEVEE"
    if bir_config.set_value("engine", new):
        msg = ("Render engine set to: %s\n\n"
               "EEVEE = fast / realtime, CYCLES = accurate final." % new)
    else:
        msg = ("Couldn't save the engine setting (is the config file locked?). "
               "Nothing was changed.")
    try:
        from pyrevit import forms
        forms.alert(msg, title="Blendit - Engine")
    except Exception:
        print(msg)


main()
