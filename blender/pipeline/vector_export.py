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
import re

import bpy

from .npr import _GP_NAME

VALID_FORMATS = ("svg", "pdf")

_GROUND_NAME = "BIR_Ground"


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


# --- true-scale paper reframing ---------------------------------------------
# Blender's GP SVG exporter sizes the page to the ink bounding box and (for an
# orthographic camera at a non-square resolution) applies an ANISOTROPIC transform
# - so the raw export is neither paper-sized nor guaranteed proportional. When a
# paper size is supplied we remap the drawing onto a true-scale, paper-sized page:
# calibrate the exporter's per-axis world->SVG scale against the geometry's extent
# (clamped to the camera frame == the clipped ink extent), extrapolate to the camera
# frame, then map that frame onto the paper rectangle. The frame's world size equals
# paper_size x scale_denominator, so the result is exactly to scale.

def _calibrate_axes(scene, camera):
    """(umin, umax, wmin, wmax, ortho_w, frame_h): the drawn geometry's extent along
    the camera right / up axes (metres, relative to the eye, clamped to the frame),
    plus the camera frame's world width + height. None if it can't be computed."""
    if camera is None or camera.data.type != "ORTHO":
        return None
    try:
        import numpy as np
        import mathutils
    except Exception:
        return None
    q = camera.matrix_world.to_quaternion()
    right = np.array((q @ mathutils.Vector((1.0, 0.0, 0.0))).normalized())
    up = np.array((q @ mathutils.Vector((0.0, 1.0, 0.0))).normalized())
    pos = np.array(camera.matrix_world.translation)
    ortho_w = float(camera.data.ortho_scale)
    rx = scene.render.resolution_x
    ry = scene.render.resolution_y
    frame_h = ortho_w * (ry / float(rx)) if rx else ortho_w   # sensor_fit HORIZONTAL
    hu, hw = ortho_w / 2.0, frame_h / 2.0
    umin = wmin = 1e18
    umax = wmax = -1e18
    found = False
    for o in scene.objects:
        if o.type != "MESH" or o.name == _GROUND_NAME:
            continue
        me = o.data
        n = len(me.vertices)
        if n == 0:
            continue
        co = np.empty(n * 3, dtype=np.float64)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        M = np.array(o.matrix_world)
        world = co @ M[:3, :3].T + M[:3, 3]
        rel = world - pos
        u = np.clip(rel @ right, -hu, hu)     # ink is clipped to the camera frame
        w = np.clip(rel @ up, -hw, hw)
        umin = min(umin, float(u.min())); umax = max(umax, float(u.max()))
        wmin = min(wmin, float(w.min())); wmax = max(wmax, float(w.max()))
        found = True
    if not found:
        return None
    return (umin, umax, wmin, wmax, ortho_w, frame_h)


def _transform_d(d, fn):
    """Rewrite a path 'd' string: parse to absolute subpaths, map each point through
    fn, re-emit as M/L(/Z). Line Art paths are closed filled outlines."""
    from .svg_to_pdf import _subpaths
    segs = []
    for sub in _subpaths(d):
        if len(sub) < 1:
            continue
        closed = len(sub) > 2 and sub[-1] == sub[0]
        raw = sub[:-1] if closed else sub
        pts = [fn(x, y) for (x, y) in raw]
        if not pts:
            continue
        seg = "M %.3f %.3f" % pts[0] + "".join(" L %.3f %.3f" % p for p in pts[1:])
        if closed:
            seg += " Z"
        segs.append(seg)
    return " ".join(segs)


def _set_svg_page(svg_text, w_mm, h_mm):
    m = re.search(r"<svg\b[^>]*>", svg_text)
    if not m:
        return svg_text
    tag = re.sub(r'\s(?:width|height|viewBox)="[^"]*"', "", m.group(0))
    tag = tag[:-1].rstrip() + (' width="%gmm" height="%gmm" viewBox="0 0 %g %g">'
                               % (w_mm, h_mm, w_mm, h_mm))
    return svg_text[:m.start()] + tag + svg_text[m.end():]


def _rect_d(x, y, w, h):
    return "M %.3f %.3f L %.3f %.3f L %.3f %.3f L %.3f %.3f Z" % (
        x, y, x + w, y, x + w, y + h, x, y + h)


def _nice_total(D):
    """A round real-world length whose bar is closest to ~60 mm on the page."""
    nice = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000]
    return min(nice, key=lambda n: abs(n * 1000.0 / D - 60.0))


def _scale_bar_svg(pw, ph, D):
    """A graphical scale bar (4 alternating segments + labels + '1:D') at the sheet's
    bottom-left, in paper mm. Fills-only (black bar with inset white segments) so it
    survives the SVG->PDF path converter; labels are <text>."""
    if D <= 0:
        return ""
    total = _nice_total(D)
    barw = total * 1000.0 / D          # mm on the page
    segs, bt, h, mx = 4, 0.3, 3.0, 15.0
    seg = barw / segs
    x0 = mx
    y0 = ph - 12.0 - h                 # 12 mm up from the bottom edge
    out = ['<g fill="#000000" font-family="sans-serif">']
    out.append('<path d="%s" fill="#000000"/>' % _rect_d(x0, y0, barw, h))
    for i in range(segs):
        if i % 2 == 1:                 # white insets leave a black frame + dividers
            out.append('<path d="%s" fill="#ffffff"/>'
                       % _rect_d(x0 + i * seg + bt, y0 + bt, seg - 2 * bt, h - 2 * bt))
    lbl = 'font-size="3" text-anchor="middle"'
    out.append('<text x="%.2f" y="%.2f" %s>0</text>' % (x0, y0 - 1.5, lbl))
    out.append('<text x="%.2f" y="%.2f" %s>%g</text>'
               % (x0 + barw / 2.0, y0 - 1.5, lbl, total / 2.0))
    out.append('<text x="%.2f" y="%.2f" %s>%g m</text>'
               % (x0 + barw, y0 - 1.5, lbl, total))
    out.append('<text x="%.2f" y="%.2f" font-size="3.2">1:%g</text>'
               % (x0, y0 + h + 4.0, round(D)))
    out.append("</g>")
    return "".join(out)


def _reframe_svg_to_paper(svg_text, scene, camera, paper_w_mm, paper_h_mm,
                          scalebar=False):
    """Remap a GP-exported SVG onto a true-scale, paper-sized page. Returns the
    rewritten SVG (or the original, unchanged, if anything is missing)."""
    from .svg_to_pdf import _paths, _subpaths
    pts = []
    for d, _fill in _paths(svg_text):
        for sub in _subpaths(d):
            pts.extend(sub)
    if len(pts) < 2:
        return svg_text
    sxs = [p[0] for p in pts]
    sys_ = [p[1] for p in pts]
    sxmin, sxmax = min(sxs), max(sxs)
    symin, symax = min(sys_), max(sys_)
    if sxmax - sxmin < 1e-6 or symax - symin < 1e-6:
        return svg_text
    cal = _calibrate_axes(scene, camera)
    if cal is None:
        return svg_text
    umin, umax, wmin, wmax, ortho_w, frame_h = cal
    if umax - umin < 1e-9 or wmax - wmin < 1e-9:
        return svg_text
    # per-axis world->SVG affine (captures the exporter's anisotropic scale)
    ax = (sxmax - sxmin) / (umax - umin)
    bx = sxmin - ax * umin
    ay = (symax - symin) / (wmax - wmin)
    by = symin - ay * wmin
    # camera frame edges in SVG space (extrapolated), then -> paper rectangle
    fxmin, fxmax = sorted((ax * (-ortho_w / 2.0) + bx, ax * (ortho_w / 2.0) + bx))
    fymin, fymax = sorted((ay * (-frame_h / 2.0) + by, ay * (frame_h / 2.0) + by))
    if fxmax - fxmin < 1e-6 or fymax - fymin < 1e-6:
        return svg_text

    def fn(sx, sy):
        return ((sx - fxmin) / (fxmax - fxmin) * paper_w_mm,
                (sy - fymin) / (fymax - fymin) * paper_h_mm)

    def _repl_path(m):                         # scope the rewrite to <path> elements
        tag = m.group(0)
        dm = re.search(r'd="([^"]*)"', tag)
        if not dm:
            return tag
        return tag[:dm.start(1)] + _transform_d(dm.group(1), fn) + tag[dm.end(1):]

    body = re.sub(r"<path\b[^>]*?/?>", _repl_path, svg_text, flags=re.DOTALL)
    body = _set_svg_page(body, paper_w_mm, paper_h_mm)
    # Poche is scene geometry (excluded from Line Art), so add its filled cut faces
    # to the vector directly - projected through the same calibration, UNDER the lines.
    poche_svg = _poche_paths(camera, ax, bx, ay, by, fn)
    if poche_svg:
        m = re.search(r"<svg\b[^>]*>", body)
        if m:
            body = body[:m.end()] + poche_svg + body[m.end():]
    if scalebar:
        # effective scale of THIS export: frame width / paper width
        d_eff = ortho_w / (paper_w_mm / 1000.0) if paper_w_mm else 0.0
        bar = _scale_bar_svg(paper_w_mm, paper_h_mm, d_eff)
        if bar:
            body = body.replace("</svg>", bar + "</svg>", 1)   # on top of everything
    return body


def _poche_fill():
    obj = bpy.data.objects.get("BIR_Poche")
    if obj is None or not obj.data.materials:
        return "#222222"
    try:
        for n in obj.data.materials[0].node_tree.nodes:
            if n.type == "EMISSION":
                c = n.inputs["Color"].default_value
                return "#%02x%02x%02x" % (int(c[0] * 255), int(c[1] * 255),
                                          int(c[2] * 255))
    except Exception:
        pass
    return "#222222"


def _poche_paths(camera, ax, bx, ay, by, fn):
    """Filled <path> elements for the BIR_Poche caps, projected onto the paper via
    the same world->SVG affine (ax/bx/ay/by) + SVG->paper map (fn). '' if no poche."""
    obj = bpy.data.objects.get("BIR_Poche")
    if obj is None or obj.type != "MESH":
        return ""
    import mathutils
    q = camera.matrix_world.to_quaternion()
    right = (q @ mathutils.Vector((1.0, 0.0, 0.0))).normalized()
    up = (q @ mathutils.Vector((0.0, 1.0, 0.0))).normalized()
    pos = camera.matrix_world.translation
    mw = obj.matrix_world
    me = obj.data
    fill = _poche_fill()
    segs = []
    for poly in me.polygons:
        pts = []
        for vi in poly.vertices:
            v = mw @ me.vertices[vi].co
            u = (v - pos).dot(right)
            w = (v - pos).dot(up)
            pts.append(fn(ax * u + bx, ay * w + by))
        if len(pts) < 3:
            continue
        d = ("M %.3f %.3f" % pts[0]
             + "".join(" L %.3f %.3f" % p for p in pts[1:]) + " Z")
        segs.append('<path d="%s" fill="%s" stroke="none"/>' % (d, fill))
    return "".join(segs)


def _reframe_file(path, paper):
    """Reframe an SVG file in place to the paper size; leave it untouched on error."""
    try:
        f = open(path, "r", encoding="utf-8")
        try:
            txt = f.read()
        finally:
            f.close()
        new = _reframe_svg_to_paper(txt, bpy.context.scene, bpy.context.scene.camera,
                                    float(paper["w_mm"]), float(paper["h_mm"]),
                                    scalebar=bool(paper.get("scalebar")))
        f = open(path, "w", encoding="utf-8")
        try:
            f.write(new)
        finally:
            f.close()
    except Exception as ex:
        print("Blendit: paper reframe skipped (%s)" % ex)


def export_vector(out_path, fmt="svg", use_fill=True, paper=None):
    """Write the Line Art GP to out_path as 'svg' or 'pdf'. Returns the written
    path. Raises RuntimeError if there's nothing to export (a lit mode), no camera,
    or the exporter isn't available. When `paper` = {'w_mm', 'h_mm'} is given, the
    output is remapped onto a true-scale, paper-sized page."""
    fmt = (fmt or "svg").lower()
    if fmt not in VALID_FORMATS:
        raise RuntimeError("Unknown vector format %r (use svg or pdf)." % fmt)
    if not has_line_art():
        raise RuntimeError("No line work to export - switch to one of the "
                           "line modes first (Linework, Pen, Sketch, ...).")
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
        _export_svg(out_path, use_fill)
        if paper:
            _reframe_file(out_path, paper)
        return out_path

    # PDF: export SVG to a temp sibling, convert, write the PDF, drop the temp.
    tmp_svg = out_path + ".tmp.svg"
    try:
        _export_svg(tmp_svg, use_fill)
        if paper:
            _reframe_file(tmp_svg, paper)
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
