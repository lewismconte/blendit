# -*- coding: utf-8 -*-
"""Configure the whole Blendit render process.

A small settings hub: Blender path, output folder, resolution, samples, denoise,
engine, and the default render mode. Stored in
%APPDATA%\\blendit\\config.json and shared by every button.
"""
__title__ = "Settings"
__author__ = "Blendit"

import os
import subprocess

import bir_bootstrap
bir_bootstrap.ensure_paths()
import bir_config


def _set_resolution(cfg):
    from pyrevit import forms
    labels = [r[0] for r in bir_config.RESOLUTIONS] + ["Custom..."]
    choice = forms.CommandSwitchWindow.show(labels, message="Output resolution")
    if not choice:
        return
    if choice == "Custom...":
        cur = cfg.get("resolution", [1600, 900])
        w = forms.ask_for_string(default=str(cur[0]), prompt="Width (px):",
                                 title="Resolution")
        if w is None:                       # cancelled - not an input error
            return
        h = forms.ask_for_string(default=str(cur[1]), prompt="Height (px):",
                                 title="Resolution")
        if h is None:
            return
        try:
            res = [int(w), int(h)]
        except Exception:
            forms.alert("Need two whole numbers.", title="Resolution")
            return
        if not bir_config.set_value("resolution", res):
            forms.alert("Couldn't save the resolution (is the config file "
                        "locked?).", title="Resolution")
        return
    for label, res in bir_config.RESOLUTIONS:
        if label == choice:
            bir_config.set_value("resolution", res)
            return


def _set_samples(cfg):
    from pyrevit import forms
    s = forms.ask_for_string(default=str(cfg.get("samples", 64)),
                             prompt="Render samples (higher = cleaner, slower):",
                             title="Samples")
    if s:
        try:
            bir_config.set_value("samples", max(1, int(s)))
        except Exception:
            forms.alert("Need a whole number.", title="Samples")


def _set_default_mode(cfg):
    from pyrevit import forms
    labels = [bir_config.MODE_LABELS[k] for k in bir_config.MODES]
    choice = forms.CommandSwitchWindow.show(labels, message="Default render mode")
    if not choice:
        return
    for key in bir_config.MODES:
        if bir_config.MODE_LABELS[key] == choice:
            bir_config.set_value("mode", key)
            return


def _test_render():
    """Prove the whole pipeline with the built-in demo scene - no model, no
    Load, about half a minute. The new-user 'does my install work?' answer."""
    from pyrevit import forms
    import bir_ui
    import bir_export
    from bir_contract.transport import stamped_name
    cfg = bir_config.load()
    blender = bir_ui.ensure_blender(cfg, bir_ui.report)
    if not blender:
        return
    bir_ui.report("**Blendit - test render** - rendering the built-in demo scene "
                  "(no model needed) to prove the whole pipeline...")
    cdir = bir_bootstrap.cache_dir_for("demo")
    bundle_ref, _ = bir_export.export_bundle(None, cfg, bir_ui.report,
                                             out_dir=cdir)
    out_dir = cfg.get("output_dir") or bir_bootstrap.default_output_dir()
    if not os.path.isdir(out_dir):
        try:
            os.makedirs(out_dir)
        except Exception:
            pass
    png = os.path.join(out_dir, stamped_name("test_render", "png"))
    log_path = os.path.splitext(png)[0] + ".log"
    # Fixed fast settings (not the user's config): the point is a quick,
    # predictable proof that Blender + the pipeline work end to end.
    cmd = [blender, "--background", "--python",
           bir_bootstrap.render_script_path(), "--",
           "--bundle", bundle_ref, "--out", png, "--open",
           "--mode", "realistic", "--engine", "CYCLES", "--samples", "32",
           "--resolution", "960", "540"]
    try:
        logf = open(log_path, "wb")
        try:
            subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT)
        finally:
            logf.close()
    except OSError as ex:
        forms.alert("Couldn't launch Blender: %s" % ex,
                    title="Blendit - Test render")
        return
    bir_ui.report("- test render started (about half a minute). **The image "
                  "opens when it's done.**\n- output: `%s`\n- log (if it "
                  "fails): `%s`" % (png, log_path))


def _clear_cache():
    from pyrevit import forms
    choice = forms.alert(
        "Delete all cached model extractions and prepared scenes?\n\n"
        "The next Load Model re-extracts from scratch. Close any open Blendit "
        "Blender sessions first.",
        title="Blendit - Clear model cache",
        options=["Clear cache", "Cancel"])
    if choice != "Clear cache":
        return
    removed, failed = bir_bootstrap.clear_cache()
    msg = "Removed %d cached model(s)." % removed
    if failed:
        msg += ("\n%d couldn't be removed (still in use?) - close Blender and "
                "try again." % failed)
    forms.alert(msg, title="Blendit - Clear model cache")


def _show_all(cfg):
    from pyrevit import forms
    res = cfg.get("resolution", [1600, 900])
    forms.alert(
        "Blender:    %s\nOutput:     %s\n\nMode:       %s\nEngine:     %s\n"
        "Samples:    %s\nDenoise:    %s\nResolution: %sx%s"
        % (cfg.get("blender_exe") or "(auto-detect)",
           cfg.get("output_dir") or "(temp folder)",
           bir_config.MODE_LABELS.get(cfg.get("mode"), cfg.get("mode")),
           cfg.get("engine"), cfg.get("samples"),
           "on" if cfg.get("denoise") else "off", res[0], res[1]),
        title="Blendit - Current settings")


def main():
    from pyrevit import forms
    while True:
        cfg = bir_config.load()
        res = cfg.get("resolution", [1600, 900])
        options = [
            "Blender.exe path",
            "Output folder",
            "Resolution  (%sx%s)" % (res[0], res[1]),
            "Samples  (%s)" % cfg.get("samples"),
            "Denoise  (%s)" % ("on" if cfg.get("denoise") else "off"),
            "Engine  (%s)" % cfg.get("engine"),
            "Default mode  (%s)" % bir_config.MODE_LABELS.get(cfg.get("mode"),
                                                              cfg.get("mode")),
            "Test render (demo scene)",
            "Clear model cache",
            "Show all settings",
        ]
        choice = forms.CommandSwitchWindow.show(
            options, message="Blendit - Settings")
        if not choice:
            return
        if choice == "Blender.exe path":
            p = forms.pick_file(file_ext="exe")
            if p:
                bir_config.set_value("blender_exe", p)
        elif choice == "Output folder":
            p = forms.pick_folder()
            if p:
                bir_config.set_value("output_dir", p)
        elif choice.startswith("Resolution"):
            _set_resolution(cfg)
        elif choice.startswith("Samples"):
            _set_samples(cfg)
        elif choice.startswith("Denoise"):
            bir_config.set_value("denoise", not cfg.get("denoise"))
        elif choice.startswith("Engine"):
            new = "CYCLES" if str(cfg.get("engine")).upper() == "EEVEE" else "EEVEE"
            bir_config.set_value("engine", new)
        elif choice.startswith("Default mode"):
            _set_default_mode(cfg)
        elif choice == "Test render (demo scene)":
            _test_render()
            return                      # leave the loop; the report is on screen
        elif choice == "Clear model cache":
            _clear_cache()
        elif choice == "Show all settings":
            _show_all(cfg)


main()
