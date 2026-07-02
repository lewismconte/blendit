"""Shared Revit-side button helpers (IronPython 2.7 safe, pure ASCII).

The pushbuttons were each re-defining report() / active_doc() / tail(); this is the
one copy. Uses pyRevit's own `revit.doc` instead of the raw `__revit__` builtin so
these work from a lib module (the builtin is only injected into the script scope).
"""


def report(msg):
    """Print markdown to the pyRevit output window (falls back to stdout)."""
    try:
        from pyrevit import script
        script.get_output().print_md(msg)
    except Exception:
        print(msg)


def active_doc():
    """The active Revit document, or None outside Revit."""
    try:
        from pyrevit import revit
        return revit.doc
    except Exception:
        return None


def tail(data, n=2000):
    """Last `n` chars of subprocess output (bytes or str), for error reports."""
    if not data:
        return ""
    try:
        text = data.decode("utf-8", "replace")
    except Exception:
        text = str(data)
    return text[-n:]


_BLENDER_DOWNLOAD_URL = "https://www.blender.org/download/"


def open_path(target):
    """Open a folder / file / URL with the OS default handler. Returns True on
    success.

    Robust on .NET Core / .NET 8 (Revit 2025+), where `Process.Start(path)` defaults
    UseShellExecute=False and THROWS for folders/URLs/non-exe paths (and IronPython's
    os.startfile can hit the same). We explicitly request a shell-execute first, then
    fall back to os.startfile for older .NET Framework hosts. Blendit ships its own
    copy so it never depends on the Luitools shared lib."""
    try:
        from System.Diagnostics import Process, ProcessStartInfo
        psi = ProcessStartInfo(target)
        psi.UseShellExecute = True            # the .NET-8-safe shell open
        Process.Start(psi)
        return True
    except Exception:
        pass
    try:
        import os
        os.startfile(target)                  # .NET Framework / non-Revit fallback
        return True
    except Exception:
        return False


def ensure_blender(cfg, report=None):
    """Return a usable blender.exe path, or None after telling the user how to fix it.

    Checks the configured path, then auto-detect (bir_bootstrap.find_blender_exe).
    If neither resolves, shows an actionable dialog - Download Blender (opens the
    download page) / Set Blender path... (file picker, saved to config) / Cancel -
    and returns None. Call this at the TOP of a launch button so a user without
    Blender is told immediately, before any slow extraction runs."""
    import os
    import bir_bootstrap
    configured = (cfg or {}).get("blender_exe")
    if configured and os.path.isfile(configured):
        return configured
    found = bir_bootstrap.find_blender_exe()
    if found:
        return found

    try:
        from pyrevit import forms
    except Exception:                       # headless / no pyRevit - just report
        if report:
            report("**Blender not found.** Install Blender "
                   "(%s) or set the path in Settings."
                   % _BLENDER_DOWNLOAD_URL)
        return None

    choice = forms.alert(
        "Blender wasn't found on this PC.\n\n"
        "Blendit renders in Blender - a free, separate program. Install it, or "
        "point Blendit at an existing blender.exe.",
        title="Blendit - Blender not found",
        options=["Download Blender", "Set Blender path...", "Cancel"])
    if choice == "Download Blender":
        open_path(_BLENDER_DOWNLOAD_URL)
        if report:
            report("Opening the Blender download page. Install Blender, then press "
                   "the button again (or set the path in Settings).")
    elif choice == "Set Blender path...":
        p = forms.pick_file(file_ext="exe")
        if p and os.path.isfile(p):
            import bir_config
            bir_config.set_value("blender_exe", p)
            return p
    return None


def require_loaded(doc):
    """-> (bundle_ref, blend_path) if a model is already loaded (cached) for this
    document, else show an alert telling the user to Load Model first and return
    (None, None).

    Open Model / Render Loaded Model consume a loaded model; loading (the slow Revit
    extraction) is the explicit, clearly-labelled Load Model step - nothing else
    surprises the user with a long operation."""
    import bir_export
    bundle_ref, blend_path = bir_export.cached_bundle(doc)
    if bundle_ref is not None:
        # Soft staleness check: warn (never block) when the model looks different
        # from what Load Model extracted - the "why is my new wall missing?" fix.
        try:
            reason = bir_export.staleness(doc)
        except Exception:
            reason = None
        if reason:
            try:
                from pyrevit import forms
                choice = forms.alert(
                    "The loaded model may be out of date: %s.\n\n"
                    "Use the cached version anyway, or cancel and press "
                    "'Load Model' to re-extract first." % reason,
                    title="Blendit - model changed since Load",
                    options=["Use cached model", "Cancel"])
                if choice != "Use cached model":
                    return None, None
            except Exception:
                pass
        return bundle_ref, blend_path
    try:
        from pyrevit import forms
        forms.alert("No model is loaded yet.\n\nPress 'Load Model' to extract the "
                    "active 3D view first, then try again.",
                    title="Blendit - no model loaded")
    except Exception:
        pass
    return None, None


def ensure_3d_view(doc, report=None):
    """True if the active view is a renderable 3D view, else show an alert telling
    the user to open one and return False.

    Blendit renders the ACTIVE 3D view; pressing a button from a plan/sheet would
    otherwise extract nothing and fall back to a confusing demo box. doc is None
    only headless/in dev, where the demo box is wanted - so allow that."""
    if doc is None:
        return True
    try:
        from bir_extract import revit_extract
        if revit_extract.active_3d_view(doc) is not None:
            return True
    except Exception:
        return True            # don't block on an import hiccup; extraction reports
    try:
        from pyrevit import forms
        forms.alert("Open a 3D view first.\n\nBlendit renders the active 3D view - "
                    "switch to (or create) a 3D view, then press the button again.",
                    title="Blendit - no 3D view")
    except Exception:
        if report:
            report("**No 3D view active.** Open a 3D view and try again.")
    return False


def set_mode(key):
    """Set the render mode in config and confirm (shared by the Mode buttons).
    Reports honestly when the config file couldn't be written."""
    import bir_config
    ok = bir_config.set_value("mode", key)
    label = bir_config.MODE_LABELS.get(key, key)
    if ok:
        msg = "Render mode set to: %s" % label
        show_mode_preview_once(key)
    else:
        msg = ("Couldn't save the render mode (is the config file locked or "
               "read-only?). Nothing was changed.")
    try:
        from pyrevit import forms
        forms.alert(msg, title="Blendit")
    except Exception:
        print(msg)


def mode_preview_path(key):
    """Path to the shipped demo-scene preview image for a render mode."""
    import os
    import bir_bootstrap
    return os.path.join(bir_bootstrap.REPO_ROOT, "media", "modes",
                        "%s.png" % key)


def show_mode_preview_once(key):
    """The FIRST time a mode is picked, show what it looks like (the built-in
    demo scene) in the output window - visual onboarding without a nag. Seen
    modes are remembered in the config."""
    import os
    import bir_config
    seen = bir_config.get_value("previewed_modes", []) or []
    if key in seen:
        return
    path = mode_preview_path(key)
    if not os.path.isfile(path):
        return
    try:
        from pyrevit import script
        out = script.get_output()
        out.print_md("**%s** looks like this (built-in demo scene):"
                     % bir_config.MODE_LABELS.get(key, key))
        out.print_image(path)
        bir_config.set_value("previewed_modes", list(seen) + [key])
    except Exception:
        pass
