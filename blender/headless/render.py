"""Headless bpy entry point.

    blender --background --python blender/headless/render.py -- \
        --bundle "<scene_spec.json or bundle dir>" --out "<output.png>" \
        [--engine CYCLES|EEVEE] [--mode MODE] [--samples N] [--camera persp|ortho]

MODE is one of: realistic, white, shadow, specular, linework, pen, sketch, cel, hatch.

Args after `--` are ours; everything before is Blender's. CLI flags override the
SceneSpec's render settings, so the same bundle can be re-rendered in any mode /
engine without re-exporting from Revit.
"""
import argparse
import os
import sys
import time


def _repo_root():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", ".."))


def _parse_args():
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser(prog="blendit", description=__doc__)
    p.add_argument("--bundle", required=True,
                   help="path to scene_spec.json or the bundle directory")
    p.add_argument("--out", required=True, help="output PNG path")
    p.add_argument("--engine", choices=["CYCLES", "EEVEE"])
    p.add_argument("--mode",
                   choices=["realistic", "white", "shadow", "linework", "specular",
                            "pen", "sketch", "cel", "hatch", "yellowtrace",
                            "kraft", "blueprint"])
    p.add_argument("--samples", type=int)
    p.add_argument("--resolution", nargs=2, type=int, metavar=("W", "H"),
                   help="override the output resolution")
    p.add_argument("--denoise", choices=["on", "off"],
                   help="override the denoise toggle")
    p.add_argument("--camera", choices=["perspective", "orthographic"],
                   help="override the view's camera type")
    p.add_argument("--two-point", dest="two_point", choices=["on", "off"],
                   help="keep verticals vertical (level the camera); off by default")
    p.add_argument("--vector", choices=["svg", "pdf"],
                   help="export the line work as scalable SVG / PDF instead of a "
                        "raster (needs a line mode: linework/pen/sketch/cel/hatch)")
    p.add_argument("--open", action="store_true",
                   help="open the result when done (so the launcher needn't wait)")
    return p.parse_args(args)


_LINE_MODES = ("linework", "pen", "sketch", "cel", "hatch", "yellowtrace",
               "kraft", "blueprint")


def _fmt_duration(seconds):
    mins, secs = divmod(int(round(seconds)), 60)
    return "%dm %02ds" % (mins, secs) if mins else "%ds" % secs


def _notify_done(png_path, seconds):
    """Best-effort Windows toast: the render landed, and how long it took.
    Purely additive (the PNG still auto-opens with --open); any failure is
    swallowed - a missing toast must never break a finished render.

    Windows only DELIVERS toasts for a registered AppUserModelID (an unknown
    id fails silently), so the script first idempotently registers 'Blendit'
    under HKCU\\Software\\Classes\\AppUserModelId - same as bir_ui.toast on
    the Revit side."""
    try:
        import base64
        import subprocess
        title = "Blendit"
        body = "Render finished in %s" % _fmt_duration(seconds)
        img_uri = "file:///" + png_path.replace("\\", "/").replace("'", "''")
        icon = os.path.join(_repo_root(), "Blendit.tab", "Render.panel",
                            "About.pushbutton", "icon.png")
        reg = ("$k='HKCU:\\SOFTWARE\\Classes\\AppUserModelId\\Blendit';"
               "if (-not (Test-Path $k)) { New-Item -Path $k -Force "
               "| Out-Null };"
               "Set-ItemProperty -Path $k -Name DisplayName -Value 'Blendit';")
        if os.path.isfile(icon):
            reg += ("Set-ItemProperty -Path $k -Name IconUri -Value '"
                    + icon.replace("'", "''") + "';")
        ps = (
            reg
            + "[Windows.UI.Notifications.ToastNotificationManager, "
            "Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null;"
            "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, "
            "ContentType=WindowsRuntime] | Out-Null;"
            "$x = New-Object Windows.Data.Xml.Dom.XmlDocument;"
            "$x.LoadXml('<toast><visual><binding template=\"ToastGeneric\">"
            "<text>" + title + "</text><text>" + body + "</text>"
            "<image placement=\"hero\" src=\"" + img_uri + "\"/>"
            "</binding></visual></toast>');"
            "$t = New-Object Windows.UI.Notifications.ToastNotification $x;"
            "[Windows.UI.Notifications.ToastNotificationManager]::"
            "CreateToastNotifier('Blendit').Show($t)"
        )
        b64 = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
        subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive",
                          "-WindowStyle", "Hidden", "-EncodedCommand", b64])
    except Exception:
        pass


def _failure_hint(tb):
    """A plain-English first-aid line for the render_FAILED note, matched from
    the traceback. Grows as real user failures come in."""
    low = tb.lower()
    if "out of memory" in low or "cuda" in low or "optix" in low or "hip" in low:
        return ("Likely the GPU ran out of memory - lower the Resolution or "
                "Samples (Quality button) and try again, or switch the "
                "Engine to EEVEE.")
    if "scene.glb" in low or "no such file" in low or "filenotfounderror" in low:
        return ("The cached bundle looks incomplete - press Load View in "
                "Revit to re-extract, then render again.")
    if "permission" in low or "access is denied" in low:
        return ("Couldn't write the output - check the Output folder in "
                "Settings is writable (not read-only / cloud-locked).")
    return ("Press Load View in Revit and try again; if it keeps failing, "
            "check the .log file next to where the image should be.")


def main():
    root = _repo_root()
    if root not in sys.path:
        sys.path.insert(0, root)

    ns = _parse_args()
    overrides = {}
    if ns.engine:
        overrides["engine"] = ns.engine
    if ns.mode:
        overrides["mode"] = ns.mode
    if ns.samples:
        overrides["samples"] = ns.samples
    if ns.resolution:
        overrides["resolution"] = list(ns.resolution)
    if ns.denoise:
        overrides["denoise"] = (ns.denoise == "on")
    if ns.camera:
        overrides["camera_type"] = ns.camera
    if ns.two_point:
        overrides["two_point"] = (ns.two_point == "on")

    # Resolve to absolute paths: Blender relativizes render.filepath against its
    # own base (not the process CWD), so a relative --out would land off-repo.
    bundle = os.path.abspath(ns.bundle)
    out_path = os.path.abspath(ns.out)

    # Vector export: build in a line mode and write SVG / PDF instead of a PNG.
    if ns.vector:
        mode = ns.mode or "linework"
        if mode not in _LINE_MODES:
            sys.stderr.write("--vector needs a line mode "
                             "(linework/pen/sketch/cel/hatch); got --mode %s\n" % mode)
            sys.exit(2)
        overrides["mode"] = mode
        vec_out = os.path.splitext(out_path)[0] + "." + ns.vector
        from blender.pipeline.run import run_vector_pipeline
        out = run_vector_pipeline(bundle, vec_out, ns.vector,
                                  overrides=overrides or None)
        print("Blendit: vector ->", out)
        if ns.open and os.path.isfile(out):
            try:
                os.startfile(out)
            except Exception:
                pass
        return

    from blender.pipeline.run import run_pipeline
    started = time.time()
    try:
        out = run_pipeline(bundle, out_path, overrides=overrides or None)
    except Exception:
        # The Revit launcher is DETACHED, so without a visible signal a failed render
        # just silently never opens. Drop a note where the PNG would have been (and
        # open it if asked) so the user isn't left wondering, then re-raise for a
        # non-zero exit + full traceback in the log.
        import traceback
        tb = traceback.format_exc()
        sys.stderr.write(tb)
        note = os.path.join(os.path.dirname(out_path) or ".", "render_FAILED.txt")
        try:
            f = open(note, "w")
            try:
                f.write("Blendit render failed.\n\nWHAT TO TRY: "
                        + _failure_hint(tb) + "\n\nDetails:\n" + tb)
            finally:
                f.close()
            if ns.open:
                try:
                    os.startfile(note)
                except Exception:
                    pass
        except Exception:
            pass
        raise
    took = time.time() - started
    print("Blendit: rendered in %s -> %s" % (_fmt_duration(took), out))

    if ns.open and os.path.isfile(out):
        _notify_done(out, took)
        # Blender opens its own result so the Revit launcher can return immediately
        # (no blocking wait). startfile is Windows-only; harmless to guard.
        try:
            os.startfile(out)
        except Exception:
            pass


if __name__ == "__main__":
    main()
