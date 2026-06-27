# -*- coding: utf-8 -*-
"""Open the renders output folder in Explorer."""
__title__ = "Open\nRenders"
__author__ = "Blendit"

import os

import bir_bootstrap
bir_bootstrap.ensure_paths()
import bir_config
from bir_ui import open_path as _open_path


def main():
    out = bir_config.get_value("output_dir") or bir_bootstrap.default_output_dir()
    if not os.path.isdir(out):
        try:
            os.makedirs(out)
        except Exception:
            pass
    # open_path shell-executes (works for folders on .NET 8 / Revit 2025+, where a
    # bare os.startfile/Process.Start can throw).
    if not _open_path(out):
        try:
            from pyrevit import forms
            forms.alert("Couldn't open the folder:\n%s" % out, title="Blendit")
        except Exception:
            print(out)


main()
