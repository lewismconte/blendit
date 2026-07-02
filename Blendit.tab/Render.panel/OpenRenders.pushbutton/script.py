# -*- coding: utf-8 -*-
"""Open the renders output folder in Explorer, with the latest renders shown
inline in the output window (you pressed this to SEE renders, after all)."""
__title__ = "Open\nRenders"
__author__ = "Blendit"

import os

import bir_bootstrap
bir_bootstrap.ensure_paths()
import bir_config
from bir_ui import open_path as _open_path

_GALLERY_COUNT = 4


def _latest_renders(out):
    """The newest PNGs across the output root + captures/ + finals/."""
    pngs = []
    for sub in ("", "captures", "finals"):
        d = os.path.join(out, sub) if sub else out
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if fn.lower().endswith(".png"):
                p = os.path.join(d, fn)
                try:
                    pngs.append((os.path.getmtime(p), p))
                except Exception:
                    pass
    pngs.sort(reverse=True)
    return [p for _mt, p in pngs[:_GALLERY_COUNT]]


def _print_gallery(out):
    """Inline thumbnails of the latest renders in the pyRevit output window."""
    latest = _latest_renders(out)
    if not latest:
        return
    try:
        from pyrevit import script
        o = script.get_output()
        o.print_md("**Blendit - latest renders** (full folder is opening "
                   "in Explorer):")
        for p in latest:
            o.print_image(p)
            o.print_md("`%s`" % os.path.basename(p))
    except Exception:
        pass


def main():
    out = bir_config.get_value("output_dir") or bir_bootstrap.default_output_dir()
    if not os.path.isdir(out):
        try:
            os.makedirs(out)
        except Exception:
            pass
    _print_gallery(out)
    # open_path shell-executes (works for folders on .NET 8 / Revit 2025+, where a
    # bare os.startfile/Process.Start can throw).
    if not _open_path(out):
        try:
            from pyrevit import forms
            forms.alert("Couldn't open the folder:\n%s" % out, title="Blendit")
        except Exception:
            print(out)


main()
