# -*- coding: utf-8 -*-
"""About Blendit - what it is, the source repo, and the author's portfolio."""
__title__ = "About"
__author__ = "Blendit"

import bir_bootstrap
bir_bootstrap.ensure_paths()
from bir_ui import report as _report, open_path as _open_path

_GITHUB = "https://github.com/lewismconte/blendit"
_PORTFOLIO = "https://lewismconte.github.io/portfolio"

_ABOUT_MD = (
    "# Blendit\n"
    "One click in Revit -> the active 3D view, rendered in Blender.\n\n"
    "An open-source (MIT) **bridge** between Revit and Blender: press a button "
    "and get a high-quality render of the current 3D view with curated, "
    "good-out-of-the-box defaults and **twelve render looks** - photoreal, "
    "clay, shadow study, showroom, and a stylised drawing family: linework, "
    "pen, sketch, cel, hatch, yellowtrace, brown paper, and blueprint - plus "
    "an interactive **Open Model** session, saved views with batch rendering, "
    "a 12-look contact sheet, and **SVG / PDF** vector export.\n\n"
    "- **Source + docs:** %s\n"
    "- **Portfolio:** %s\n" % (_GITHUB, _PORTFOLIO))


def main():
    _report(_ABOUT_MD)                       # full blurb + clickable links in output
    try:
        from pyrevit import forms
        choice = forms.alert(
            "Blendit\n\nOne click in Revit, rendered in Blender.\n"
            "Open-source, MIT licensed.",
            title="About Blendit",
            options=["Open GitHub", "Open Portfolio", "Close"])
        if choice == "Open GitHub":
            _open_path(_GITHUB)
        elif choice == "Open Portfolio":
            _open_path(_PORTFOLIO)
    except Exception:
        pass                                 # headless: the report() above stands


main()
