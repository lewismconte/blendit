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
    """Set the render mode (shared by the Mode buttons). Deliberately
    popup-free: picking a mode is a one-click action, not a dialog
    conversation - feedback is a passive toast (auto-dismisses, steals no
    focus, stacks no windows) carrying the mode's preview image, plus a
    refreshed Mode-pulldown tooltip. Only a FAILED save interrupts."""
    import bir_config
    ok = bir_config.set_value("mode", key)
    label = bir_config.MODE_LABELS.get(key, key)
    if not ok:
        msg = ("Couldn't save the render mode (is the config file locked or "
               "read-only?). Nothing was changed.")
        try:
            from pyrevit import forms
            forms.alert(msg, title="Blendit")
        except Exception:
            print(msg)
        return
    ensure_mode_tooltips()          # in case startup ran before the ribbon existed
    toast("Render mode: %s" % label, image=mode_preview_path(key))
    update_mode_tooltip(label)


def mode_preview_path(key):
    """Path to the shipped demo-scene preview image for a render mode."""
    import os
    import bir_bootstrap
    return os.path.join(bir_bootstrap.REPO_ROOT, "media", "modes",
                        "%s.png" % key)


# --- passive feedback: Windows toast ----------------------------------------
def _xml_escape(s):
    s = str(s)
    for a, b in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"),
                 ('"', "&quot;"), ("'", "&apos;")):
        s = s.replace(a, b)
    return s


def _toast_icon():
    """A PNG to brand the Blendit toasts with, or None."""
    import os
    import bir_bootstrap
    p = os.path.join(bir_bootstrap.REPO_ROOT, "Blendit.tab", "Render.panel",
                     "About.pushbutton", "icon.png")
    return p if os.path.isfile(p) else None


def toast(message, title="Blendit", image=None):
    """Fire-and-forget Windows toast via a hidden PowerShell (WinRT). The
    polite alternative to a modal alert. `image` (a PNG path) becomes the
    toast's hero image. Returns True if launched; never raises - missing
    toast support must never break a button.

    Windows only DELIVERS toasts for a registered AppUserModelID - an
    unknown id fails silently (Show() succeeds, nothing appears). So the
    script first (idempotently) registers 'Blendit' under
    HKCU\\Software\\Classes\\AppUserModelId (user-writable, no admin), the
    documented route for unpackaged apps."""
    try:
        import base64
        import os
        img = ""
        if image and os.path.isfile(image):
            img = ('<image placement="hero" src="'
                   + _xml_escape("file:///" + image.replace("\\", "/"))
                   + '"/>')
        xml = ('<toast><visual><binding template="ToastGeneric"><text>'
               + _xml_escape(title) + "</text><text>" + _xml_escape(message)
               + "</text>" + img + "</binding></visual></toast>")
        reg = ("$k='HKCU:\\SOFTWARE\\Classes\\AppUserModelId\\Blendit';"
               "if (-not (Test-Path $k)) { New-Item -Path $k -Force "
               "| Out-Null };"
               "Set-ItemProperty -Path $k -Name DisplayName -Value 'Blendit';")
        icon = _toast_icon()
        if icon:
            reg += ("Set-ItemProperty -Path $k -Name IconUri -Value '"
                    + icon.replace("'", "''") + "';")
        # -EncodedCommand sidesteps every quoting pitfall; the XML is safe
        # inside PS single quotes because _xml_escape removed the apostrophes.
        ps = (reg
              + "[Windows.UI.Notifications.ToastNotificationManager, "
              "Windows.UI.Notifications, ContentType=WindowsRuntime] "
              "| Out-Null;"
              "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom."
              "XmlDocument, ContentType=WindowsRuntime] | Out-Null;"
              "$x = New-Object Windows.Data.Xml.Dom.XmlDocument;"
              "$x.LoadXml('" + xml + "');"
              "$t = New-Object Windows.UI.Notifications.ToastNotification $x;"
              "[Windows.UI.Notifications.ToastNotificationManager]::"
              "CreateToastNotifier('Blendit').Show($t)")
        b64 = base64.b64encode(ps.encode("utf-16-le"))
        if not isinstance(b64, str):
            b64 = b64.decode("ascii")
        from System.Diagnostics import Process, ProcessStartInfo
        psi = ProcessStartInfo(
            "powershell.exe",
            "-NoProfile -NonInteractive -WindowStyle Hidden -EncodedCommand "
            + b64)
        psi.CreateNoWindow = True
        psi.UseShellExecute = False
        Process.Start(psi)
        return True
    except Exception:
        return False


# --- ribbon hover tooltips (previews live on hover, not in popups) ----------
# The mode key -> the ribbon button label (each Mode script's __title__).
MODE_BUTTON_TEXT = {
    "realistic": "Realistic", "white": "White", "shadow": "Shadow",
    "specular": "Specular", "linework": "Linework", "pen": "Pen",
    "sketch": "Sketch", "cel": "Cel", "hatch": "Hatch",
}

_TOOLTIPS_DONE = [False]


def find_ribbon_item(text, tab_title="Blendit"):
    """The AdWindows RibbonItem on our tab whose label equals `text`, or None.
    Raw AdWindows walk (stable API, no pyRevit-version coupling); callers
    guard the import."""
    import Autodesk.Windows as adw

    def _walk(items):
        for it in items:
            t = getattr(it, "Text", None)
            if t and str(t).replace("\r", " ").replace("\n", " ") == text:
                return it
            kids = getattr(it, "Items", None)
            if kids:
                found = _walk(kids)
                if found is not None:
                    return found
        return None

    for tab in adw.ComponentManager.Ribbon.Tabs:
        if tab.Title == tab_title:
            for panel in tab.Panels:
                found = _walk(panel.Source.Items)
                if found is not None:
                    return found
    return None


def set_ribbon_tooltip_image(text, image_path):
    """Attach a preview image to a ribbon item's extended (hover) tooltip."""
    try:
        import os
        if not os.path.isfile(image_path):
            return False
        import Autodesk.Windows as adw
        from System import Uri
        from System.Windows.Media.Imaging import BitmapImage
        item = find_ribbon_item(text)
        if item is None:
            return False
        tip = item.ToolTip
        if not isinstance(tip, adw.RibbonToolTip):
            new_tip = adw.RibbonToolTip()
            new_tip.Title = text
            if tip:
                new_tip.Content = str(tip)
            tip = new_tip
        tip.ExpandedImage = BitmapImage(Uri(image_path))
        item.ToolTip = tip
        return True
    except Exception:
        return False


def set_ribbon_tooltip_text(text, tooltip):
    """Set / refresh a ribbon item's hover tooltip text."""
    try:
        import Autodesk.Windows as adw
        item = find_ribbon_item(text)
        if item is None:
            return False
        tip = item.ToolTip
        if isinstance(tip, adw.RibbonToolTip):
            tip.Content = tooltip
        else:
            item.ToolTip = tooltip
        return True
    except Exception:
        return False


def update_mode_tooltip(label):
    """Hovering the Mode pulldown answers 'what is it set to right now?'."""
    set_ribbon_tooltip_text(
        "Mode", "Render mode for the next render.\nCurrent: %s" % label)


def ensure_mode_tooltips(force=False):
    """Attach every mode's preview image to its button tooltip + reflect the
    current mode on the pulldown. Idempotent and cheap; called from startup.py
    AND on first mode use, because startup may run before the ribbon exists."""
    if _TOOLTIPS_DONE[0] and not force:
        return
    import bir_config
    ok_any = False
    for key, text in MODE_BUTTON_TEXT.items():
        if set_ribbon_tooltip_image(text, mode_preview_path(key)):
            ok_any = True
    try:
        cur = bir_config.get_value("mode")
        update_mode_tooltip(bir_config.MODE_LABELS.get(cur, cur))
    except Exception:
        pass
    if ok_any:
        _TOOLTIPS_DONE[0] = True
