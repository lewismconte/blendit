# -*- coding: utf-8 -*-
"""Your loaded views, in one list.

Every view you've pressed **Load View** on keeps its own cached copy, so plans,
sections, elevations and 3D shots can all be loaded side by side. This lists
them - newest first, marked **out of date** when the model has changed since
Load (or the view was deleted) - and lets you **Open** one in Blender,
**Render** it, **Reload** it (re-extract, even if it's not the active view),
or **Remove** its cache.
"""
__title__ = "Views"
__author__ = "Blendit"

import bir_bootstrap
bir_bootstrap.ensure_paths()
import bir_config
import bir_export
from bir_ui import (report as _report, active_doc as _active_doc,
                    pick_loaded_view as _pick, toast as _toast,
                    launch_open_view as _open, launch_headless_render as _render,
                    dismiss_output as _dismiss_output,
                    launch_cache_build as _launch_cache_build)


def _alert(msg, title="Blendit - Views"):
    try:
        from pyrevit import forms
        forms.alert(msg, title=title)
    except Exception:
        _report(msg)


def main():
    cfg = bir_config.load()
    doc = _active_doc()
    slots = bir_export.loaded_views(doc)
    if not slots:
        _alert("No views are loaded yet.\n\nPress 'Load View' on a 3D, plan, "
               "section or elevation view - each loaded view keeps its own "
               "cached copy and shows up here.")
        return

    slot = _pick(doc, slots, "Pick a loaded view:")
    if slot is None:
        return

    try:
        from pyrevit import forms
        action = forms.CommandSwitchWindow.show(
            ["Open in Blender", "Render", "Reload", "Remove"],
            message="'%s' - what would you like to do?" % slot["view_name"])
    except Exception:
        action = None
    if not action:
        return

    if action == "Open in Blender":
        _open(cfg, _report, slot["bundle_ref"], slot["blend_path"])
    elif action == "Render":
        _render(cfg, _report, banner="Render '%s'" % slot["view_name"],
                bundle_ref=slot["bundle_ref"])
    elif action == "Reload":
        view = bir_export.resolve_view(doc, slot.get("view_uid"))
        if view is None:
            _alert("'%s' no longer exists in the model - its cache can only be "
                   "opened or removed." % slot["view_name"])
            return
        _report("**Blendit - reloading '%s'**" % slot["view_name"])
        bundle_ref, blend_path = bir_export.refresh_cache(doc, cfg, _report,
                                                          view=view)
        _launch_cache_build(cfg, bundle_ref, blend_path)
        _toast("Reloaded: %s" % slot["view_name"])
    elif action == "Remove":
        if bir_export.remove_slot(slot):
            _toast("Removed: %s" % slot["view_name"])
        else:
            _alert("Couldn't remove '%s' - its files may be open in a running "
                   "Blender session." % slot["view_name"])
    _dismiss_output(10)     # info only - the window closes itself


main()
