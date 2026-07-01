"""Export the Line Art as true vector SVG / PDF (scalable line drawings).

Only the NPR line modes (linework / pen / sketch / cel / hatch) build a Grease
Pencil Line Art object (npr.setup_line_art -> 'BIR_LineArt'); the lit modes are
shaded raster with no vector equivalent, so export raises there with a clear
message. The
Grease Pencil exporter projects the GP through the scene camera at the render
resolution, so the page matches the composed frame.

cel exports as OUTLINES ONLY: its colour bands are mesh-emission (raster), not GP
fills, so they don't carry into the vector.

SVG goes straight through Blender's (solid) Grease Pencil SVG exporter. PDF is the
same SVG run through svg_to_pdf - Blender's native GP PDF exporter is broken in the
5.0 build (HARU backend writes nothing and segfaults on repeat calls), so we do not
touch it.
"""
import os

import bpy

from .npr import _GP_NAME

VALID_FORMATS = ("svg", "pdf")


def has_line_art():
    """True if a Line Art GP object exists to export (i.e. we're in a line mode)."""
    return bpy.data.objects.get(_GP_NAME) is not None


def _svg_op():
    wm = bpy.ops.wm
    if hasattr(wm, "grease_pencil_export_svg"):
        return wm.grease_pencil_export_svg
    return None


def _view3d_override():
    """A (window, area, region) for a VIEW_3D if one exists, else (None, None,
    None). The exporter polls happily headless; supplying a 3D context is harmless
    and covers the interactive path."""
    try:
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                if area.type == "VIEW_3D":
                    region = next((r for r in area.regions if r.type == "WINDOW"),
                                  None)
                    return win, area, region
    except Exception:
        pass
    return None, None, None


def _export_svg(svg_path, use_fill):
    """Run Blender's Grease Pencil SVG exporter for the Line Art GP. Returns the
    written path; raises on any failure."""
    op = _svg_op()
    if op is None:
        raise RuntimeError("This Blender has no Grease Pencil SVG exporter.")
    gp = bpy.data.objects.get(_GP_NAME)

    # Make the Line Art the active + only-selected object so 'ACTIVE' targets it,
    # and force the procedural Line Art to (re)compute so the exporter sees strokes.
    try:
        for o in list(bpy.context.selected_objects):
            o.select_set(False)
    except Exception:
        pass
    try:
        gp.select_set(True)
        bpy.context.view_layer.objects.active = gp
    except Exception:
        pass
    try:
        from . import npr
        if not npr.is_line_art_baked():      # baked = already current, skip the retrace
            npr.refresh_line_art()           # live: re-trace for this camera
    except Exception:
        pass
    try:
        bpy.context.view_layer.update()      # ensure strokes are evaluated
    except Exception:
        pass

    kwargs = dict(filepath=svg_path, check_existing=False, use_fill=use_fill,
                  selected_object_type="ACTIVE", frame_mode="ACTIVE",
                  use_clip_camera=True)       # clip strokes to the camera frame
    win, area, region = _view3d_override()
    if area is not None and hasattr(bpy.context, "temp_override"):
        with bpy.context.temp_override(window=win, area=area, region=region):
            res = op("EXEC_DEFAULT", **kwargs)
    else:
        res = op("EXEC_DEFAULT", **kwargs)

    if "FINISHED" not in res:
        raise RuntimeError("Grease Pencil SVG export did not finish (%s)." % (res,))
    if not os.path.isfile(svg_path):
        raise RuntimeError("Grease Pencil SVG export wrote no file at %s."
                           % svg_path)
    return svg_path


def export_vector(out_path, fmt="svg", use_fill=True):
    """Write the Line Art GP to out_path as 'svg' or 'pdf'. Returns the written
    path. Raises RuntimeError if there's nothing to export (a lit mode), no camera,
    or the exporter isn't available."""
    fmt = (fmt or "svg").lower()
    if fmt not in VALID_FORMATS:
        raise RuntimeError("Unknown vector format %r (use svg or pdf)." % fmt)
    if not has_line_art():
        raise RuntimeError("No line work to export - switch to a line mode "
                           "(Linework / Pen / Sketch / Cel / Hatch) first.")
    if bpy.context.scene.camera is None:
        raise RuntimeError("No camera to project the drawing through.")

    out_path = os.path.abspath(out_path)
    d = os.path.dirname(out_path)
    if d and not os.path.isdir(d):
        try:
            os.makedirs(d)
        except Exception:
            pass

    if fmt == "svg":
        return _export_svg(out_path, use_fill)

    # PDF: export SVG to a temp sibling, convert, write the PDF, drop the temp.
    tmp_svg = out_path + ".tmp.svg"
    try:
        _export_svg(tmp_svg, use_fill)
        f = open(tmp_svg, "r", encoding="utf-8")
        try:
            svg_text = f.read()
        finally:
            f.close()
        from .svg_to_pdf import svg_to_pdf
        data = svg_to_pdf(svg_text)
        out = open(out_path, "wb")
        try:
            out.write(data)
        finally:
            out.close()
    finally:
        try:
            if os.path.isfile(tmp_svg):
                os.remove(tmp_svg)
        except Exception:
            pass
    if not os.path.isfile(out_path):
        raise RuntimeError("PDF conversion wrote no file at %s." % out_path)
    return out_path
