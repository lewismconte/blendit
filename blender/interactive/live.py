"""Interactive Blender session for Blendit live navigation.

Launched (NOT --background) by the Revit 'Open Model' button:

    blender.exe --python blender/interactive/live.py -- --bundle "<bundle ref>" \
        [--engine EEVEE|CYCLES] [--mode realistic|white|shadow|linework|specular]

Two modes, toggled with F10:
  * FLY    - stripped review: viewport maximized (no outliner / properties /
             timeline / header / toolbar), overlays + gizmos off, rendered, FREE
             perspective nav. The N-panel stays so the Look sliders are reachable.
  * BUILD  - the regular Blender interface, for working in the scene / assets.

The N-panel (press N) has a 'Blendit' tab: Mode + Engine + live Look
sliders (exposure, sky, sun, sun angle), per-mode Line controls + a Regenerate
Lines button, and a View box (Perspective/Ortho, gizmos & nav tools, near/far
clip). Heavy actions (mode switch, line regen) show a 'WORKING...' banner so you
can tell it's busy, not broken.

Line Art is camera-relative and too heavy to retrace every orbit frame on a big
model, so you orbit freely (lines hold) then press Regenerate Lines (L) to retrace
for the new angle + current crease / intersection / hidden-line settings.

Navigation: Auto-Depth + Zoom-to-Mouse are enabled for the session (pivot follows
the surface under the cursor; real dolly zoom). Session-only - the user's saved
Blender preferences are not modified.

    Capture  Enter / Numpad-Enter    Regen lines  L    Fly / Build  F10
"""
import argparse
import os
import sys

import bpy

try:
    import blf
except Exception:
    blf = None

_CAPTURE_DIR = None
_STATUS = "Navigate to compose your shot, then press Enter to capture."
_HUD_HANDLE = None
_SETUP_TRIES = 0
_KEYMAP_BOUND = False
_FLY_MODE = True
_SYNCING = False
_BUSY = False          # a heavy op (regen lines / mode switch / capture) is running
_BUSY_LABEL = ""       # what the busy banner shows

_LOADED = None   # LoadedScene from build_scene
_SPEC = None     # the SceneSpec dict
_SCALE = 1.0
_MODEL_NAME = ""  # friendly model label for the HUD readout
_BUILD_ARGS = None  # parsed args, handed from main() to the deferred build
_OVERRIDE_DIR = None  # where material_overrides.json lives (the bundle dir)

_TITLE = "BLENDIT  -  LIVE"
_CONTROLS = [
    "Orbit  MMB drag      Pan  Shift+MMB      Zoom  scroll (to cursor)",
    "Walk / Fly  Shift + `   then  W A S D ,  mouse ,  E / Q",
    "Capture  Enter      Regen lines  L      Regular UI  F10      N  panel",
]


def _repo_root():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", ".."))


def _parse_args():
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser(prog="blendit-live")
    p.add_argument("--bundle", required=True)
    # Cached prepared scene: open it instead of re-importing if it exists, and/or
    # write it after a fresh import for next time.
    p.add_argument("--blend")
    p.add_argument("--save-blend", dest="save_blend")
    # Where Enter-captures go (the user's render folder); the bundle now lives in
    # the cache, so this is passed explicitly rather than derived from --bundle.
    p.add_argument("--capture-dir", dest="capture_dir")
    p.add_argument("--engine", choices=["CYCLES", "EEVEE"])
    p.add_argument("--mode",
                   choices=["realistic", "white", "shadow", "specular",
                            "linework", "pen", "sketch", "cel", "hatch"])
    return p.parse_args(args)


# --- viewport / context helpers --------------------------------------------
def _iter_view3d():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                yield win, area


def _first_view3d():
    for win, area in _iter_view3d():
        return win, area
    return None, None


def _region(area, rtype="WINDOW"):
    for region in area.regions:
        if region.type == rtype:
            return region
    return None


def _run_in_view3d(op):
    win, area = _first_view3d()
    if area is None:
        return
    region = _region(area)
    try:
        if hasattr(bpy.context, "temp_override"):
            with bpy.context.temp_override(window=win, area=area, region=region):
                op()
        else:
            op({"window": win, "area": area, "region": region})
    except Exception:
        pass


def _redraw_all():
    for win, area in _iter_view3d():
        area.tag_redraw()
    try:                       # force the headers/cursor to flush too
        bpy.context.window.cursor_set("WAIT" if _BUSY else "DEFAULT")
    except Exception:
        pass


def _run_busy(label, fn):
    """Show a 'working' banner + wait cursor, then run the (blocking) fn on the
    next timer tick so the banner actually paints before the UI freezes. This is
    the closest Blender gets to a loading bar for a single opaque operation - it
    can't show a % for one Line-Art recompute, but it makes 'is it working or did
    I break it?' obvious."""
    global _BUSY, _BUSY_LABEL
    _BUSY = True
    _BUSY_LABEL = label
    _redraw_all()

    def _later():
        global _BUSY, _BUSY_LABEL
        try:
            fn()
        except Exception as ex:
            print("Blendit: '%s' failed: %s" % (label, ex))
        finally:
            _BUSY = False
            _BUSY_LABEL = ""
            _redraw_all()
        return None

    try:
        bpy.app.timers.register(_later, first_interval=0.03)
    except Exception:
        _later()


def _export_path(subdir, prefix, ext):
    """<output>/<subdir>/<prefix>_<stamp>.<ext> - the SAME dated naming the Revit
    render uses (via bir_contract.transport.stamped_name), with a counter suffix only if
    a file already exists in the same second."""
    from bir_contract.transport import stamped_name
    base = _CAPTURE_DIR or os.path.expanduser("~")
    d = os.path.join(base, subdir)
    if not os.path.isdir(d):
        try:
            os.makedirs(d)
        except Exception:
            d = base
    path = os.path.join(d, stamped_name(prefix, ext))
    if not os.path.exists(path):
        return path
    root, dot_ext = os.path.splitext(path)
    i = 2
    while os.path.exists("%s_%d%s" % (root, i, dot_ext)):
        i += 1
    return "%s_%d%s" % (root, i, dot_ext)


def _next_capture_path():
    return _export_path("captures", "capture", "png")


def _next_final_path():
    return _export_path("finals", "final", "png")


def _next_vector_path(ext):
    return _export_path("vectors", "drawing", ext)


def _model_center():
    try:
        from blender.pipeline.camera import _scene_bbox
        bb = _scene_bbox()
        if bb:
            mn, mx = bb
            return (mn + mx) * 0.5
    except Exception:
        pass
    return None


# --- navigation feel (session-only preferences) ----------------------------
def _set_nav_prefs():
    try:
        prefs = bpy.context.preferences
        prefs.use_preferences_save = False          # session-only; saved prefs untouched
        inp = prefs.inputs
        # Auto Depth OFF. With lock-camera framing it takes the pan/orbit pivot from
        # the depth UNDER THE CURSOR; the model is small and ringed by empty space, so
        # the cursor is usually over the (far-clip) background and a single pan drags
        # the camera clear across the scene - and it inflates view_distance after each
        # orbit, compounding it. A fixed pivot, anchored to the model on frame-entry
        # (see _anchor_view_pivot), pans predictably.
        inp.use_mouse_depth_navigate = False
        inp.use_zoom_to_mouse = True
        inp.view_rotate_method = "TURNTABLE"
        inp.use_auto_perspective = False
    except Exception:
        pass


# --- live look settings (the sliders) --------------------------------------
def _helpers():
    from blender.pipeline.presets import _helpers as h
    return h


def _update_exposure(self, context):
    if _SYNCING:
        return
    context.scene.view_settings.exposure = self.exposure


def _update_sky(self, context):
    if _SYNCING:
        return
    _helpers().set_world_strength(self.sky_strength)


def _update_sun(self, context):
    if _SYNCING:
        return
    _helpers().set_sun_energy(self.sun_strength)


def _update_sun_dir(self, context):
    if _SYNCING:
        return
    _apply_sun_direction(self.sun_azimuth, self.sun_altitude)


def _update_mode(self, context):
    if _SYNCING:
        return
    mode = self.mode
    _run_busy("Switching to %s" % mode, lambda: _apply_mode(mode))


def _reapply_camera():
    """Apply the View panel's Projection / Focal / Lens-Shift to the real scene
    camera IN PLACE, preserving the user's composition. This is what makes
    Orthographic and Two-Point reach the capture / render camera (not just the
    viewport nav), and converts without the auto-fit jump."""
    from blender.pipeline import camera as cam
    st = getattr(bpy.context.scene, "bir", None)
    co = bpy.context.scene.camera
    if st is None or co is None:
        return
    cam.convert_projection(
        co, st.projection,
        focal_mm=(st.focal_length if st.focal_length > 0.0 else None),
        extra_shift=st.lens_shift)
    for win, area in _iter_view3d():
        area.tag_redraw()


def _update_camera(self, context):
    if _SYNCING:
        return
    _reapply_camera()


def _snap_camera_to_view():
    """Snap the export camera to the current view, then re-assert the chosen
    Projection so Two-Point / Ortho actually land in the capture / render / export.
    camera_to_view() copies the raw viewport orientation onto the camera, which would
    otherwise undo the levelling when composing outside Frame View."""
    _run_in_view3d(lambda: bpy.ops.view3d.camera_to_view())
    _reapply_camera()


def _update_gizmos(self, context):
    if _SYNCING:
        return
    for win, area in _iter_view3d():
        for space in area.spaces:
            if space.type != "VIEW_3D":
                continue
            try:
                space.show_gizmo = self.show_gizmos              # transform "gumball"
                space.show_gizmo_navigate = self.show_gizmos     # axis ball / nav
            except Exception:
                pass
        area.tag_redraw()


def _update_clip(self, context):
    if _SYNCING:
        return
    for win, area in _iter_view3d():
        for space in area.spaces:
            if space.type != "VIEW_3D":
                continue
            try:
                space.clip_start = self.clip_near
                space.clip_end = self.clip_far
            except Exception:
                pass
        area.tag_redraw()


def _update_frame_view(self, context):
    if _SYNCING:
        return
    _set_frame_view(self.frame_view)


def _update_line_crease(self, context):
    if _SYNCING:
        return
    from blender.pipeline import npr
    npr.set_line_art_crease(self.line_crease)


def _update_line_intersection(self, context):
    if _SYNCING:
        return
    from blender.pipeline import npr
    npr.set_line_art_intersection(self.line_intersection)


def _update_line_occlusion(self, context):
    if _SYNCING:
        return
    from blender.pipeline import npr
    npr.set_line_art_occlusion(self.line_occlusion)


def _update_line_color(self, context):
    if _SYNCING:
        return
    from blender.pipeline import npr
    npr.set_line_art_color(tuple(self.line_color))


def _update_sun_softness(self, context):
    if _SYNCING:
        return
    from blender.pipeline.presets import _helpers
    _helpers.set_sun_softness(self.sun_softness)


def _update_gloss(self, context):
    if _SYNCING or _LOADED is None:
        return
    from blender.pipeline.presets import _helpers
    _helpers.set_glossiness(_LOADED, 1.0 - self.gloss)   # gloss 1.0 = mirror


_ASPECTS = {"16:9": (16, 9), "3:2": (3, 2), "4:3": (4, 3),
            "1:1": (1, 1), "9:16": (9, 16)}


def _apply_aspect(aspect):
    """Set the render resolution (== the camera frame shape == what's exported) to
    `aspect`, preserving the current long edge for quality."""
    r = _ASPECTS.get(aspect)
    if not r:
        return
    sc = bpy.context.scene
    long_edge = max(sc.render.resolution_x, sc.render.resolution_y, 1)
    aw, ah = r
    if aw >= ah:
        sc.render.resolution_x = long_edge
        sc.render.resolution_y = int(round(long_edge * ah / float(aw)))
    else:
        sc.render.resolution_y = long_edge
        sc.render.resolution_x = int(round(long_edge * aw / float(ah)))


def _update_aspect(self, context):
    if _SYNCING:
        return
    _apply_aspect(self.aspect)
    _reapply_camera()                    # the frame shape changed -> refit framing
    for win, area in _iter_view3d():     # refresh the passepartout frame
        area.tag_redraw()


def _update_line_thickness(self, context):
    if _SYNCING:
        return
    from blender.pipeline import npr
    npr.set_line_art_radius(self.line_thickness)


def _update_sketch(self, context):
    if _SYNCING:
        return
    from blender.pipeline import npr
    npr.set_sketchiness(self.sketch_amount)


def _update_cel_shades(self, context):
    if _SYNCING or _LOADED is None:
        return
    from blender.pipeline import npr
    npr.set_toon_shades(_LOADED, int(self.cel_shades))


def _update_hatch(self, context):
    if _SYNCING or _LOADED is None:
        return
    from blender.pipeline import npr
    npr.set_hatch(_LOADED, self.hatch_density, self.hatch_cross, self.hatch_weight,
                  self.hatch_angle, self.hatch_cross_angle)


def _update_depth_cue(self, context):
    if _SYNCING:
        return
    from blender.pipeline import npr
    if self.depth_cue:
        if npr.is_line_art_baked():
            _run_busy("Depth cueing lines", npr.apply_depth_cue)
        # else: it'll apply after the next Regenerate (which bakes first)
    else:
        _run_busy("Resetting line weight", _do_regenerate_lines)   # re-bake = uniform


def _update_engine(self, context):
    if _SYNCING:
        return
    if _SPEC is None:
        return
    _SPEC.setdefault("render", {})["engine"] = self.engine
    from blender.pipeline.engine import setup_engine
    setup_engine(_SPEC)
    # Rebuild the materials for the new engine when they're visible: EEVEE glass
    # needs per-material raytraced-refraction flags that only
    # build_material(engine="EEVEE") sets, so a CYCLES-built scene switched to
    # EEVEE would otherwise render its glass opaque.
    if self.mode in _TEXTURED_MODES and _LOADED is not None:
        from blender.pipeline.materials import apply_materials
        apply_materials(_LOADED, engine=self.engine)
        if self.mode == "specular":     # re-assert the gloss slider on the rebuild
            _helpers().set_glossiness(_LOADED, 1.0 - self.gloss)
    # If clouds are in the scene, re-apply their volume step / sample settings for the
    # engine we just switched to (Cycles wants step-rate; EEVEE wants sample counts).
    from blender.interactive import clouds
    if clouds.DOMAIN_NAME in bpy.data.objects:
        cl = getattr(context.scene, "bir_clouds", None)
        if cl is not None:
            clouds.apply_render_settings(context, cl.quality)


def _apply_sun_direction(az, alt):
    import math
    from blender.pipeline.world import _to_sun_vector
    h = _helpers()
    s = h.sun_object()
    if s is not None:
        to_sun = _to_sun_vector(alt, az)
        s.rotation_euler = (-to_sun).to_track_quat("-Z", "Y").to_euler()
    w = bpy.context.scene.world
    if w and w.use_nodes:
        for n in w.node_tree.nodes:
            if n.type == "TEX_SKY":
                if hasattr(n, "sun_elevation"):
                    n.sun_elevation = math.radians(alt)
                if hasattr(n, "sun_rotation"):
                    n.sun_rotation = math.radians(az)


def _recompute_sun():
    """Revit-style sun: date + time + location -> azimuth/altitude -> lamp + sky."""
    global _SYNCING
    st = getattr(bpy.context.scene, "bir", None)
    if st is None:
        return
    from blender.pipeline import sun_calc
    doy = sun_calc.day_of_year(st.sun_month, st.sun_day)
    az, alt = sun_calc.solar_position(st.sun_lat, st.sun_lon, doy,
                                      st.sun_time, st.sun_tz)
    _SYNCING = True
    try:                                    # reflect into the manual sliders, no recursion
        st.sun_azimuth = az % 360.0
        st.sun_altitude = max(0.0, min(90.0, alt))
    finally:
        _SYNCING = False
    _apply_sun_direction(az, alt)


def _apply_user_sun(st):
    """Re-apply whichever sun the user set (date/time or manual) - called after a
    mode rebuild so switching modes never resets the sun."""
    if st is None:
        return
    if st.sun_use_datetime:
        _recompute_sun()
    else:
        _apply_sun_direction(st.sun_azimuth, st.sun_altitude)


def _update_sun_datetime(self, context):
    if _SYNCING:
        return
    _apply_user_sun(self)


def _update_sun_time(self, context):
    if _SYNCING:
        return
    _recompute_sun()


def _apply_mode(mode):
    if _LOADED is None or _SPEC is None:
        return
    _SPEC.setdefault("render", {})["mode"] = mode
    # Rebuild the base look so switching OUT of an NPR / flat-world mode restores
    # the sun + sky; the preset then layers its specifics on top.
    from blender.pipeline.look import apply_look
    from blender.pipeline.world import setup_world
    from blender.pipeline.presets import get_preset
    from blender.pipeline.engine import setup_engine
    apply_look(_SPEC)
    setup_world(_SPEC, _SCALE)
    get_preset(mode)(_LOADED, _SPEC)
    setup_engine(_SPEC)
    _sync_settings_from_scene()
    _apply_user_sun(getattr(bpy.context.scene, "bir", None))  # keep the user's sun
    if mode in _LINE_MODES:
        # The preset built a fresh procedural Line Art; let it trace once, then
        # freeze it so export / render / capture reuse it instead of recomputing.
        from blender.pipeline import npr
        try:
            bpy.context.view_layer.update()
            npr.bake_line_art()
        except Exception:
            pass


def _sync_settings_from_scene():
    """Pull the current scene look back into the sliders (after build / mode)."""
    global _SYNCING
    st = getattr(bpy.context.scene, "bir", None)
    if st is None:
        return
    _SYNCING = True
    try:
        sc = bpy.context.scene
        h = _helpers()
        st.exposure = sc.view_settings.exposure
        bg = h.world_background()
        if bg is not None:
            st.sky_strength = bg.inputs["Strength"].default_value
        s = h.sun_object()
        if s is not None:
            import math
            st.sun_strength = s.data.energy
            st.sun_softness = math.degrees(s.data.angle)
        from blender.pipeline import npr
        r = npr.get_line_art_radius()
        if r is not None:
            st.line_thickness = r
        cr = npr.get_line_art_crease_deg()
        if cr is not None:
            st.line_crease = cr
        lc = npr.get_line_art_color()
        if lc is not None:
            st.line_color = lc
        st.engine = "CYCLES" if sc.render.engine == "CYCLES" else "EEVEE"
        if _SPEC is not None:
            st.mode = str(_SPEC.get("render", {}).get("mode", "realistic"))
            # sun direction is user-owned via the Sun panel (_init_sun seeds it once),
            # so it is NOT re-synced from the spec here - that would reset it on every
            # mode switch.
    except Exception:
        pass
    finally:
        _SYNCING = False


def _sync_view_toggles():
    """Reflect the current viewport projection / gizmo / clip state into the View
    panel props without re-triggering their update callbacks."""
    global _SYNCING
    st = getattr(bpy.context.scene, "bir", None)
    if st is None:
        return
    win, area = _first_view3d()
    if area is None:
        return
    space = None
    for sp in area.spaces:
        if sp.type == "VIEW_3D":
            space = sp
            break
    if space is None:
        return
    _SYNCING = True
    try:
        r3d = getattr(space, "region_3d", None)
        if r3d is not None:
            st.frame_view = (r3d.view_perspective == "CAMERA")
            # NB: projection now reflects the CAMERA (set via the dropdown), not the
            # viewport-nav projection, so it is not synced from r3d here.
        st.show_gizmos = bool(getattr(space, "show_gizmo", False))
        st.clip_near = space.clip_start
        st.clip_far = space.clip_end
    except Exception:
        pass
    finally:
        _SYNCING = False


_MODE_ITEMS = [
    ("realistic", "Realistic", "Full PBR (the photoreal default)"),
    ("white", "White / Clay", "White matte massing"),
    ("shadow", "Shadow study", "Sun-accurate clay, shadows emphasized"),
    ("specular", "Specular", "Lookdev / reflectivity"),
    ("linework", "Linework", "Line Art over clay"),
    ("pen", "Pen", "Rhino-style technical pen: white fill, black lines"),
    ("sketch", "Sketch", "Hand-drawn wobbly lines on paper"),
    ("cel", "Cel / Anime", "Toon shading + outline"),
    ("hatch", "Hatch", "Tonal shadow hatching (perspective-correct lines)"),
]

_LIT_MODES = ("realistic", "white", "shadow", "specular")
_LINE_MODES = ("linework", "pen", "sketch", "cel", "hatch")
# Modes where real materials (and therefore textures) are visible. White/Shadow are
# clay overrides; the NPR modes are line / flat. Kept in sync with material_library.
_TEXTURED_MODES = ("realistic", "specular")
_SURFACE_ITEMS = [
    ("auto", "Auto (by name)", "Match a surface from the Revit material name"),
    ("plain", "Plain colour", "Flat Revit colour, no texture"),
    ("brick", "Brick", "Brick coursing (triplanar)"),
    ("wood", "Wood", "Wood grain"),
    ("concrete", "Concrete", "Cast concrete"),
    ("stone", "Stone / Tile", "Stone / marble / tile veining"),
    ("metal", "Metal", "Brushed metal"),
    ("fabric", "Fabric / Carpet", "Woven fabric / carpet"),
    ("grass", "Grass", "Grass / turf"),
]


def _update_material_surface(self, context):
    if _SYNCING:
        return
    _apply_material_override(self)


class BIR_MaterialItem(bpy.types.PropertyGroup):
    """One row in the Materials list: a Revit material + its surface override.
    `name` (from the PropertyGroup base) holds the Revit material name for display."""
    mat_id: bpy.props.StringProperty()
    surface: bpy.props.EnumProperty(name="Surface", items=_SURFACE_ITEMS,
                                    default="auto", update=_update_material_surface)


class BIR_Settings(bpy.types.PropertyGroup):
    mode: bpy.props.EnumProperty(name="Mode", items=_MODE_ITEMS,
                                 default="realistic", update=_update_mode)
    engine: bpy.props.EnumProperty(
        name="Engine",
        items=[("EEVEE", "EEVEE", "Fast / realtime"),
               ("CYCLES", "Cycles", "Accurate")],
        default="EEVEE", update=_update_engine)
    exposure: bpy.props.FloatProperty(name="Exposure", default=-1.3,
                                      min=-6.0, max=6.0, update=_update_exposure)
    sky_strength: bpy.props.FloatProperty(name="Sky", default=0.4,
                                          min=0.0, max=5.0, update=_update_sky)
    sun_strength: bpy.props.FloatProperty(name="Sun", default=5.0,
                                          min=0.0, max=40.0, update=_update_sun)
    sun_azimuth: bpy.props.FloatProperty(name="Sun Azimuth", default=150.0,
                                         min=0.0, max=360.0, update=_update_sun_dir)
    sun_altitude: bpy.props.FloatProperty(name="Sun Altitude", default=45.0,
                                          min=0.0, max=90.0, update=_update_sun_dir)
    # Revit-style sun: place it by date + time at the project location.
    sun_use_datetime: bpy.props.BoolProperty(
        name="By Date & Time", default=True,
        description="Place the sun by date + time at the project location (like "
                    "Revit), instead of raw azimuth/altitude",
        update=_update_sun_datetime)
    sun_time: bpy.props.FloatProperty(
        name="Time of Day", default=14.0, min=0.0, max=24.0, precision=2,
        description="24-hour clock, e.g. 14.5 = 2:30 PM", update=_update_sun_time)
    sun_month: bpy.props.IntProperty(name="Month", default=6, min=1, max=12,
                                     update=_update_sun_time)
    sun_day: bpy.props.IntProperty(name="Day", default=21, min=1, max=31,
                                   update=_update_sun_time)
    sun_lat: bpy.props.FloatProperty(name="Latitude", default=40.0, min=-90.0,
                                     max=90.0, precision=4, update=_update_sun_time)
    sun_lon: bpy.props.FloatProperty(name="Longitude", default=0.0, min=-180.0,
                                     max=180.0, precision=4, update=_update_sun_time)
    sun_tz: bpy.props.FloatProperty(name="UTC Offset", default=0.0, min=-13.0,
                                    max=14.0, update=_update_sun_time)
    sun_softness: bpy.props.FloatProperty(
        name="Shadow Softness", default=1.0, min=0.0, max=20.0,
        description="Sun angular size: 0 = crisp shadows, higher = soft / diffuse",
        update=_update_sun_softness)
    gloss: bpy.props.FloatProperty(
        name="Glossiness", default=0.9, min=0.0, max=1.0,
        description="Specular mode surface shine: 1 = mirror, 0 = matte",
        update=_update_gloss)
    # NPR (line / sketch / cel)
    line_thickness: bpy.props.FloatProperty(name="Line Thickness", default=0.05,
                                            min=0.001, max=3.0, precision=3,
                                            update=_update_line_thickness)
    line_crease: bpy.props.FloatProperty(
        name="Crease Angle", default=70.0, min=0.0, max=180.0,
        description="Edges sharper than this get an interior line "
                    "(higher = cleaner, fewer lines). Apply with Regenerate",
        update=_update_line_crease)
    line_intersection: bpy.props.BoolProperty(
        name="Intersections", default=False,
        description="Draw lines where meshes intersect. Apply with Regenerate",
        update=_update_line_intersection)
    line_occlusion: bpy.props.BoolProperty(
        name="Hidden Lines", default=False,
        description="Also draw occluded edges (x-ray look). Apply with Regenerate",
        update=_update_line_occlusion)
    line_color: bpy.props.FloatVectorProperty(
        name="Line Color", subtype="COLOR", size=3, min=0.0, max=1.0,
        default=(0.0, 0.0, 0.0), description="Stroke colour (try a deep blue ink)",
        update=_update_line_color)
    sketch_amount: bpy.props.FloatProperty(name="Sketchiness", default=0.3,
                                           min=0.0, max=2.0,
                                           update=_update_sketch)
    cel_shades: bpy.props.IntProperty(name="Shades", default=3, min=2, max=6,
                                      update=_update_cel_shades)
    hatch_density: bpy.props.FloatProperty(
        name="Density", default=10.0, min=1.0, max=400.0, soft_max=60.0,
        description="Hatch lines per metre on the surface (more = finer, denser)",
        update=_update_hatch)
    hatch_weight: bpy.props.FloatProperty(
        name="Line Weight", default=1.0, min=0.05, max=2.0,
        description="Thickness of each hatch line (lower = thinner; pair a low "
                    "weight with high density for fine hatching)",
        update=_update_hatch)
    hatch_cross: bpy.props.BoolProperty(
        name="Cross-hatch", default=False,
        description="Add a second, crossing set of lines in the darker tones "
                    "(its direction is the Cross Angle below)", update=_update_hatch)
    hatch_angle: bpy.props.FloatProperty(
        name="Hatch Angle", default=0.0, min=0.0, max=360.0,
        description="Rotate the hatch line direction, 0-360 deg (within each surface "
                    "plane)", update=_update_hatch)
    hatch_cross_angle: bpy.props.FloatProperty(
        name="Cross Angle", default=90.0, min=0.0, max=360.0,
        description="Direction of the cross-hatch set, 0-360 deg (90 = perpendicular "
                    "to the hatch)", update=_update_hatch)
    depth_cue: bpy.props.BoolProperty(
        name="Depth Cue", default=False,
        description="Tier line weight by distance: near edges thick + dark, far "
                    "edges thin + pale (survives SVG / PDF export). Applies on "
                    "Regenerate", update=_update_depth_cue)
    final_samples: bpy.props.IntProperty(
        name="Final Samples", default=200, min=16, max=4096,
        description="Render samples for Render Final (higher = cleaner, slower)")
    # Per-material surface overrides (the Materials list).
    material_overrides: bpy.props.CollectionProperty(type=BIR_MaterialItem)
    material_index: bpy.props.IntProperty(default=0)
    # View (always available)
    frame_view: bpy.props.BoolProperty(
        name="Frame View", default=False,
        description="Look through the export-frame camera and lock it to the view: "
                    "orbit / pan / zoom / walk now move the camera so you compose the "
                    "exact shot. Off = free explore (camera stays put)",
        update=_update_frame_view)
    projection: bpy.props.EnumProperty(
        name="Projection",
        items=[("PERSP", "Perspective", "Standard perspective"),
               ("TWO_POINT", "Two-Point",
                "Level the camera so verticals stay vertical (architectural "
                "tilt-shift) - keeps your position, shifts the lens to recompose"),
               ("ORTHO", "Orthographic",
                "Parallel projection (elevations / plans)")],
        default="PERSP", update=_update_camera)
    show_gizmos: bpy.props.BoolProperty(
        name="Gizmos & Nav Tools", default=False,
        description="Show Blender's transform gizmo + navigation axis-ball",
        update=_update_gizmos)
    clip_near: bpy.props.FloatProperty(name="Clip Near", default=0.05,
                                       min=0.001, max=50.0, precision=3,
                                       update=_update_clip)
    clip_far: bpy.props.FloatProperty(name="Clip Far", default=100000.0,
                                      min=1.0, max=1000000.0,
                                      update=_update_clip)
    aspect: bpy.props.EnumProperty(
        name="Frame", default="16:9",
        description="Shape of the export frame (the camera frame you compose in)",
        items=[("16:9", "16:9 Wide", "Landscape"),
               ("3:2", "3:2", "Classic photo"),
               ("4:3", "4:3", "Standard"),
               ("1:1", "1:1 Square", "Square"),
               ("9:16", "9:16 Tall", "Portrait")],
        update=_update_aspect)
    focal_length: bpy.props.FloatProperty(
        name="Focal (mm)", default=0.0, min=0.0, max=300.0, step=50, precision=1,
        description="Override the lens focal length in millimetres "
                    "(0 = use the view's field of view)",
        update=_update_camera)
    lens_shift: bpy.props.FloatProperty(
        name="Lens Shift", default=0.0, min=-1.0, max=1.0, step=2, precision=3,
        description="Slide the frame up / down without tilting the camera "
                    "(raises the vantage while keeping verticals vertical)",
        update=_update_camera)


# --- materials list (surface overrides) ------------------------------------
class BIR_UL_materials(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        row = layout.row(align=True)
        row.label(text=(item.name or item.mat_id), icon="MATERIAL")
        sub = row.row(align=True)
        sub.scale_x = 1.25
        sub.prop(item, "surface", text="")


def _load_material_overrides():
    from blender.pipeline import materials as M
    return M.load_overrides(_OVERRIDE_DIR)


def _save_material_overrides():
    st = getattr(bpy.context.scene, "bir", None)
    if st is None:
        return
    mapping = {it.mat_id: it.surface for it in st.material_overrides
               if it.mat_id and it.surface and it.surface != "auto"}
    from blender.pipeline import materials as M
    M.save_overrides(_OVERRIDE_DIR, mapping)


def _apply_material_override(item):
    """Persist the choice, then (only in a textured mode) rebuild that one material
    and reassign it to its merged object so the change shows immediately. In clay /
    NPR modes nothing is shown, so we just save - apply_materials will honour the
    sidecar when the user switches back to a lit mode."""
    _save_material_overrides()
    st = getattr(bpy.context.scene, "bir", None)
    if st is None or _SPEC is None or st.mode not in _TEXTURED_MODES:
        return
    rec = next((r for r in _SPEC.get("materials", [])
                if r.get("id") == item.mat_id), None)
    if rec is None:
        return
    from blender.pipeline import materials as M
    from blender.pipeline.merge import MERGED_PREFIX
    mat = M.build_material(rec, engine=st.engine, surface=item.surface)
    obj = bpy.data.objects.get(MERGED_PREFIX + str(item.mat_id))
    if obj is not None:
        obj.data.materials.clear()
        obj.data.materials.append(mat)
        for win, area in _iter_view3d():
            area.tag_redraw()


def _init_materials():
    """Populate the Materials list from the materials actually present in the scene
    (post-merge), seed each row from the saved sidecar, and realise any persisted
    overrides on the live objects."""
    global _SYNCING
    st = getattr(bpy.context.scene, "bir", None)
    if st is None or _SPEC is None:
        return
    recs = {r.get("id"): r for r in _SPEC.get("materials", [])}
    ids, seen = [], set()
    for el in _SPEC.get("geometry", {}).get("elements", []):
        mid = el.get("material_id")
        if mid and mid not in seen:
            seen.add(mid)
            ids.append(mid)
    if not ids:                       # fallback: every material in the spec
        ids = [r.get("id") for r in _SPEC.get("materials", []) if r.get("id")]
    persisted = _load_material_overrides()
    _SYNCING = True
    try:
        st.material_overrides.clear()
        for mid in ids:
            it = st.material_overrides.add()
            it.mat_id = mid
            it.name = recs.get(mid, {}).get("name") or mid
            it.surface = persisted.get(mid, "auto")
    finally:
        _SYNCING = False
    for it in st.material_overrides:  # realise persisted overrides (self-guards by mode)
        if it.surface != "auto":
            _apply_material_override(it)


# --- operators --------------------------------------------------------------
def _do_capture():
    global _STATUS
    _snap_camera_to_view()
    out = _next_capture_path()
    sc = bpy.context.scene
    sc.render.image_settings.file_format = "PNG"
    sc.render.filepath = out
    bpy.ops.render.render(write_still=True)
    _enter_frame()                 # show exactly what was captured (navigable)
    _STATUS = "Saved: %s" % os.path.basename(out)


class BIR_OT_render_image(bpy.types.Operator):
    bl_idname = "bir.render_image"
    bl_label = "Capture"
    bl_description = "Snap the camera to your current view and render a PNG"

    def execute(self, context):
        # Deferred via _run_busy so the WORKING banner paints before the
        # (blocking) render - same treatment as Render Final / Regenerate.
        _run_busy("Rendering capture", _do_capture)
        return {"FINISHED"}


class BIR_OT_toggle_mode(bpy.types.Operator):
    bl_idname = "bir.toggle_mode"
    bl_label = "Fly / Build"
    bl_description = "Switch between Fly review and the regular Blender interface"

    def execute(self, context):
        if _FLY_MODE:
            _enter_build()
        else:
            _enter_fly()
        return {"FINISHED"}


def _do_regenerate_lines():
    from blender.pipeline import npr
    if npr._active_lineart_mod() is None:
        return                      # not a line mode - don't move the camera
    # Thaw any frozen bake so the new settings + camera take effect on a fresh trace.
    npr.unbake_line_art()
    # Line Art is camera-relative, so first snap the camera to what you're looking
    # at; then push the current settings onto the modifier and force a re-trace.
    _snap_camera_to_view()
    st = getattr(bpy.context.scene, "bir", None)
    if st is not None:
        npr.set_line_art_crease(st.line_crease)
        npr.set_line_art_intersection(st.line_intersection)
        npr.set_line_art_occlusion(st.line_occlusion)
        npr.set_line_art_radius(st.line_thickness)
    npr.refresh_line_art()
    npr.bake_line_art()         # freeze: export / render / capture now reuse it (fast)
    st = getattr(bpy.context.scene, "bir", None)
    if st is not None and st.depth_cue:
        npr.apply_depth_cue()   # tier weight by distance (on the fresh bake)
    _enter_frame()              # show the export frame so the lines fill it (WYSIWYG)


class BIR_OT_regenerate_lines(bpy.types.Operator):
    bl_idname = "bir.regenerate_lines"
    bl_label = "Regenerate Lines"
    bl_description = ("Re-trace the Line Art for your current view and settings "
                     "(orbit freely, then regenerate to refresh the lines)")

    def execute(self, context):
        _run_busy("Regenerating lines", _do_regenerate_lines)
        return {"FINISHED"}


def _do_render_final():
    # Render the CURRENT composed view at high quality, so a shot framed in Live
    # View can be finalized in-session (no round-trip to Revit). Lit modes go to
    # Cycles; NPR (Line Art / toon) stays EEVEE since that's where it renders.
    sc = bpy.context.scene
    st = getattr(sc, "bir", None)
    _snap_camera_to_view()
    _enter_frame()
    samples = int(st.final_samples) if st is not None else 200
    npr_mode = bool(st is not None and st.mode in _LINE_MODES)
    prev_engine = sc.render.engine
    try:                                    # final samples are final-only: remember
        prev_eevee_samples = sc.eevee.taa_render_samples
        prev_cycles_samples = sc.cycles.samples
    except Exception:
        prev_eevee_samples = prev_cycles_samples = None
    from blender.pipeline.engine import _eevee_engine_id
    if npr_mode:
        sc.render.engine = _eevee_engine_id()
        sc.eevee.taa_render_samples = samples
    else:
        sc.render.engine = "CYCLES"
        sc.cycles.samples = samples
        sc.cycles.use_denoising = True
    out = _next_final_path()
    sc.render.image_settings.file_format = "PNG"
    sc.render.filepath = out
    bpy.ops.render.render(write_still=True)
    sc.render.engine = prev_engine          # restore the fast viewport engine
    try:                                    # ...and the configured sample counts
        if prev_eevee_samples is not None:
            sc.eevee.taa_render_samples = prev_eevee_samples
        if prev_cycles_samples is not None:
            sc.cycles.samples = prev_cycles_samples
    except Exception:
        pass
    global _STATUS
    _STATUS = "Final saved: %s" % os.path.basename(out)
    try:
        os.startfile(out)                   # Windows shell-open; harmless if it fails
    except Exception:
        pass


class BIR_OT_render_final(bpy.types.Operator):
    bl_idname = "bir.render_final"
    bl_label = "Render Final"
    bl_description = ("High-quality render of your CURRENT view (Cycles for lit "
                     "modes, EEVEE for line modes), saved to /finals and opened")

    def execute(self, context):
        _run_busy("Rendering final", _do_render_final)
        return {"FINISHED"}


class BIR_OT_open_captures(bpy.types.Operator):
    bl_idname = "bir.open_captures"
    bl_label = "Open Captures"
    bl_description = "Open the output folder (captures + final renders)"

    def execute(self, context):
        target = _CAPTURE_DIR or os.path.expanduser("~")
        try:
            os.startfile(target)
        except Exception:
            self.report({"WARNING"}, "Could not open %s" % target)
        return {"FINISHED"}


def _do_export_vector(fmt):
    """Export the current line work as a scalable vector. Snap the camera to the
    view first so the drawing matches what you see (Line Art is camera-relative),
    then write to <output>/vectors and open it."""
    global _STATUS
    from blender.pipeline import vector_export
    if not vector_export.has_line_art():
        _STATUS = ("Vector export needs a line mode "
                   "(Linework / Pen / Sketch / Cel / Hatch).")
        return
    _snap_camera_to_view()
    _enter_frame()                       # WYSIWYG: the export frame == what you see
    out = _next_vector_path(fmt)
    try:
        path = vector_export.export_vector(out, fmt)
    except Exception as ex:
        _STATUS = "Vector export failed: %s" % ex
        print("Blendit: vector export failed: %s" % ex)
        return
    _STATUS = "Saved %s: %s" % (fmt.upper(), os.path.basename(path))
    try:
        os.startfile(path)               # open in browser / Illustrator / PDF viewer
    except Exception:
        pass


class BIR_OT_export_vector(bpy.types.Operator):
    bl_idname = "bir.export_vector"
    bl_label = "Export Vector"
    bl_description = ("Export the line work as a scalable vector file (SVG or PDF) "
                     "- true paths you can edit in Illustrator / Inkscape / CAD")
    fmt: bpy.props.StringProperty(default="svg", options={"HIDDEN"})

    def execute(self, context):
        fmt = (self.fmt or "svg").lower()
        _run_busy("Exporting %s" % fmt.upper(), lambda: _do_export_vector(fmt))
        return {"FINISHED"}


def _bir(context):
    return getattr(context.scene, "bir", None)


# Collapsible sub-panels keep the (growing) toolset compact: each section gets a
# native expand/collapse arrow and Blender remembers its state. Less-used sections
# (Sun, Re-trace, View) start collapsed via DEFAULT_CLOSED.
class _Sub:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Blendit"


class BIR_PT_main(bpy.types.Panel):
    bl_label = "Blendit"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Blendit"

    def draw(self, context):
        layout = self.layout
        st = _bir(context)
        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator("bir.render_image", text="Capture", icon="RENDER_STILL")
        col.operator("bir.render_final", text="Render Final", icon="RENDER_STILL")
        col.scale_y = 1.0
        row = col.row(align=True)
        row.operator("bir.open_captures", text="Open Captures", icon="FILE_FOLDER")
        row.operator("bir.toggle_mode",
                     text="Regular UI" if _FLY_MODE else "Fly Mode",
                     icon="SCREEN_BACK")
        if st is None:
            return
        layout.separator()
        box = layout.box()
        box.label(text="View Mode", icon="SHADING_RENDERED")
        box.prop(st, "mode", text="")
        if st.mode in _LIT_MODES:
            box.prop(st, "engine", text="")
        else:
            box.label(text="Engine: EEVEE")
        box.prop(st, "final_samples")          # Render Final quality (all modes)


class BIR_PT_materials(_Sub, bpy.types.Panel):
    bl_parent_id = "BIR_PT_main"
    bl_label = "Materials"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 0

    @classmethod
    def poll(cls, context):
        st = _bir(context)
        return (st is not None and st.mode in _TEXTURED_MODES
                and len(st.material_overrides))

    def draw(self, context):
        st = _bir(context)
        layout = self.layout
        layout.template_list("BIR_UL_materials", "", st, "material_overrides",
                             st, "material_index", rows=6)
        layout.label(text="Auto = match by name; pick a surface to override.")


class BIR_PT_light(_Sub, bpy.types.Panel):
    bl_parent_id = "BIR_PT_main"
    bl_label = "Light"
    bl_order = 1

    @classmethod
    def poll(cls, context):
        st = _bir(context)
        return st is not None and (st.mode in _LIT_MODES
                                   or st.mode in ("linework", "cel", "hatch"))

    def draw(self, context):
        st = _bir(context)
        layout = self.layout
        if st.mode in _LIT_MODES or st.mode == "linework":
            layout.prop(st, "exposure", slider=True)
            layout.prop(st, "sky_strength", slider=True)
            layout.prop(st, "sun_strength", slider=True)
        layout.prop(st, "sun_softness", slider=True)
        if st.mode == "specular":
            layout.prop(st, "gloss", slider=True)


class BIR_PT_sun(_Sub, bpy.types.Panel):
    bl_parent_id = "BIR_PT_light"
    bl_label = "Sun"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return BIR_PT_light.poll(context)

    def draw(self, context):
        st = _bir(context)
        layout = self.layout
        layout.prop(st, "sun_use_datetime", toggle=True, icon="LIGHT_SUN")
        if st.sun_use_datetime:
            layout.prop(st, "sun_time", slider=True)
            r = layout.row(align=True)
            r.prop(st, "sun_month")
            r.prop(st, "sun_day")
            r = layout.row(align=True)
            r.prop(st, "sun_lat")
            r.prop(st, "sun_lon")
            layout.prop(st, "sun_tz")
        else:
            layout.prop(st, "sun_azimuth", slider=True)
            layout.prop(st, "sun_altitude", slider=True)


class BIR_PT_lines(_Sub, bpy.types.Panel):
    bl_parent_id = "BIR_PT_main"
    bl_label = "Lines"
    bl_order = 2

    @classmethod
    def poll(cls, context):
        st = _bir(context)
        return st is not None and st.mode in _LINE_MODES

    def draw(self, context):
        st = _bir(context)
        layout = self.layout
        layout.prop(st, "line_thickness", slider=True)   # outline weight (live)
        layout.prop(st, "line_color", text="")           # live colour
        if st.mode == "sketch":
            layout.prop(st, "sketch_amount", slider=True)
        if st.mode == "cel":
            layout.prop(st, "cel_shades", slider=True)
        if st.mode == "hatch":
            hb = layout.column(align=True)
            hb.prop(st, "hatch_density", slider=True)
            hb.prop(st, "hatch_weight", slider=True)
            hb.prop(st, "hatch_angle", slider=True)
            hb.prop(st, "hatch_cross", toggle=True)
            if st.hatch_cross:
                hb.prop(st, "hatch_cross_angle", slider=True)
        big = layout.column(align=True)
        big.scale_y = 1.3
        big.operator("bir.regenerate_lines", icon="FILE_REFRESH")
        exp = layout.row(align=True)
        exp.scale_y = 1.2
        o = exp.operator("bir.export_vector", text="Export SVG", icon="EXPORT")
        o.fmt = "svg"
        o = exp.operator("bir.export_vector", text="PDF", icon="EXPORT")
        o.fmt = "pdf"


class BIR_PT_lines_adv(_Sub, bpy.types.Panel):
    bl_parent_id = "BIR_PT_lines"
    bl_label = "Re-trace & Depth"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        st = _bir(context)
        return st is not None and st.mode in _LINE_MODES

    def draw(self, context):
        st = _bir(context)
        layout = self.layout
        layout.prop(st, "line_crease", slider=True)
        r = layout.row(align=True)
        r.prop(st, "line_intersection", toggle=True)
        r.prop(st, "line_occlusion", toggle=True)
        layout.prop(st, "depth_cue", toggle=True, icon="MOD_THICKNESS")
        layout.label(text="Apply with Regenerate.", icon="INFO")


class BIR_PT_view(_Sub, bpy.types.Panel):
    bl_parent_id = "BIR_PT_main"
    bl_label = "View"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 3

    def draw(self, context):
        st = _bir(context)
        if st is None:
            return
        layout = self.layout
        fr = layout.column(align=True)
        fr.scale_y = 1.2
        fr.prop(st, "frame_view", toggle=True, icon="CAMERA_DATA")   # navigable frame
        layout.prop(st, "aspect", text="")        # export frame shape == render aspect
        layout.prop(st, "projection", text="")    # Perspective / Two-Point / Ortho
        layout.prop(st, "show_gizmos", toggle=True)
        clip = layout.column(align=True)
        clip.prop(st, "clip_near", slider=True)
        clip.prop(st, "clip_far")


class BIR_PT_framing(_Sub, bpy.types.Panel):
    bl_parent_id = "BIR_PT_view"
    bl_label = "Framing"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        st = _bir(context)
        if st is None:
            return
        col = self.layout.column(align=True)
        col.prop(st, "focal_length")
        shift = self.layout.column(align=True)
        shift.enabled = (st.projection != "ORTHO")   # lens shift is for perspective
        shift.prop(st, "lens_shift", slider=True)


# --- Atmosphere / Weather (vendored volumetric clouds; see clouds.py) -------
def _clouds(context):
    return getattr(context.scene, "bir_clouds", None)


class BIR_PT_atmosphere(_Sub, bpy.types.Panel):
    bl_parent_id = "BIR_PT_main"
    bl_label = "Atmosphere / Weather"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 4

    def draw(self, context):
        s = _clouds(context)
        if s is None:
            return
        layout = self.layout
        st = _bir(context)
        if st is not None:
            row = layout.row(align=True)         # same engine prop as View Mode
            row.prop(st, "engine", expand=True)   # clouds need Cycles to look right
        col = layout.column(align=True)
        col.prop(s, "preset")
        row = col.row(align=True)
        row.scale_y = 1.3
        row.operator("bir.clouds_generate", icon="OUTLINER_OB_VOLUME")
        col.prop(s, "live_update")
        layout.operator("bir.clouds_add_sky", icon="LIGHT_SUN")
        if st is not None and st.engine != "CYCLES":
            layout.label(text="Switch to Cycles for real clouds.", icon="INFO")


class BIR_PT_atmo_shape(_Sub, bpy.types.Panel):
    bl_parent_id = "BIR_PT_atmosphere"
    bl_label = "Cloud Shape"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        s = _clouds(context)
        if s is None:
            return
        c = self.layout.column(align=True)
        c.prop(s, "coverage", slider=True)
        c.prop(s, "density")
        c.prop(s, "shape_scale")
        c.prop(s, "billow", slider=True)
        c.prop(s, "erosion", slider=True)
        r = c.row(align=True)
        r.prop(s, "height_base", slider=True)
        r.prop(s, "height_top", slider=True)


class BIR_PT_atmo_detail(_Sub, bpy.types.Panel):
    bl_parent_id = "BIR_PT_atmosphere"
    bl_label = "Detail & Light"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        s = _clouds(context)
        if s is None:
            return
        c = self.layout.column(align=True)
        c.prop(s, "detail")
        c.prop(s, "roughness", slider=True)
        c.prop(s, "anisotropy", slider=True)
        c.prop(s, "stretch")
        c.prop(s, "shear")


class BIR_PT_atmo_domain(_Sub, bpy.types.Panel):
    bl_parent_id = "BIR_PT_atmosphere"
    bl_label = "Domain"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        s = _clouds(context)
        if s is None:
            return
        layout = self.layout
        layout.prop(s, "domain_shape", expand=True)
        if s.domain_shape == "TORUS":
            layout.prop(s, "ring_radius")
            layout.prop(s, "ring_tube")
            layout.prop(s, "ring_height")
            layout.prop(s, "ring_center_cam")
        else:
            layout.prop(s, "size")
        layout.prop(s, "altitude")


class BIR_PT_atmo_sky(_Sub, bpy.types.Panel):
    bl_parent_id = "BIR_PT_atmosphere"
    bl_label = "Sky & Sun"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        s = _clouds(context)
        if s is None:
            return
        layout = self.layout
        col = layout.column(align=True)
        col.prop(s, "sun_elevation")
        col.prop(s, "sun_azimuth")
        col = layout.column(align=True)
        col.prop(s, "sun_strength")
        col.prop(s, "sun_warmth", slider=True)
        col = layout.column(align=True)
        col.prop(s, "sky_strength")
        col.prop(s, "haze")
        col.prop(s, "dust")
        layout.prop(s, "exposure")


class BIR_PT_atmo_anim(_Sub, bpy.types.Panel):
    bl_parent_id = "BIR_PT_atmosphere"
    bl_label = "Animation"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        s = _clouds(context)
        if s is None:
            return
        layout = self.layout
        layout.prop(s, "animate")
        sub = layout.column(align=True)
        sub.active = s.animate
        sub.prop(s, "wind")
        sub.prop(s, "evolve")


class BIR_PT_atmo_render(_Sub, bpy.types.Panel):
    bl_parent_id = "BIR_PT_atmosphere"
    bl_label = "Render Quality"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        s = _clouds(context)
        if s is None:
            return
        layout = self.layout
        layout.prop(s, "quality")
        layout.operator("bir.clouds_quality", icon="MODIFIER")


_ATMO_CLASSES = (BIR_PT_atmosphere, BIR_PT_atmo_shape, BIR_PT_atmo_detail,
                 BIR_PT_atmo_domain, BIR_PT_atmo_sky, BIR_PT_atmo_anim,
                 BIR_PT_atmo_render)

_CLASSES = (BIR_MaterialItem, BIR_Settings, BIR_UL_materials,
            BIR_OT_render_image, BIR_OT_render_final, BIR_OT_open_captures,
            BIR_OT_export_vector, BIR_OT_toggle_mode, BIR_OT_regenerate_lines,
            BIR_PT_main, BIR_PT_materials, BIR_PT_light, BIR_PT_sun,
            BIR_PT_lines, BIR_PT_lines_adv, BIR_PT_view, BIR_PT_framing) + _ATMO_CLASSES


def _register_ui():
    from blender.interactive import clouds
    for cls in clouds.CLOUD_CLASSES:      # settings + operators (before the panels)
        try:
            bpy.utils.register_class(cls)
        except Exception:
            pass
    for cls in _CLASSES:
        try:
            bpy.utils.register_class(cls)
        except Exception:
            pass
    try:
        bpy.types.Scene.bir = bpy.props.PointerProperty(type=BIR_Settings)
    except Exception:
        pass
    try:
        bpy.types.Scene.bir_clouds = bpy.props.PointerProperty(type=clouds.BIR_CloudSettings)
    except Exception:
        pass


# --- modes (Fly / Build) ----------------------------------------------------
def _is_maximized():
    for win in bpy.context.window_manager.windows:
        areas = win.screen.areas
        if len(areas) == 1 and areas[0].type == "VIEW_3D":
            return True
    return False


def _maximize_toggle():
    win, area = _first_view3d()
    if area is None:
        return
    region = _region(area)
    try:
        if hasattr(bpy.context, "temp_override"):
            with bpy.context.temp_override(window=win, area=area, region=region):
                bpy.ops.screen.screen_full_area(use_hide_panels=False)
        else:
            bpy.ops.screen.screen_full_area(
                {"window": win, "area": area, "region": region},
                use_hide_panels=False)
    except Exception:
        pass


def _enter_fly():
    global _FLY_MODE
    _FLY_MODE = True
    if not _is_maximized():
        _maximize_toggle()              # hide outliner / properties / timeline
    for win, area in _iter_view3d():
        for space in area.spaces:
            if space.type != "VIEW_3D":
                continue
            space.shading.type = "RENDERED"
            space.clip_start = 0.05
            space.clip_end = max(space.clip_end, 100000.0)
            try:
                space.overlay.show_overlays = False
                space.show_gizmo = False             # transform gizmo + nav off...
                space.show_gizmo_navigate = False    # (toggle back on in the panel)
                space.show_region_header = False     # hide header + toolbar...
                space.show_region_toolbar = False
                space.show_region_ui = True          # ...but keep the N-panel (sliders)
            except Exception:
                pass
            space.lock_camera = False
            r3d = getattr(space, "region_3d", None)
            if r3d is not None and r3d.view_perspective == "CAMERA":
                r3d.view_perspective = "PERSP"
        area.tag_redraw()
    _set_keymap_fly(True)
    _sync_view_toggles()


def _enter_build():
    global _FLY_MODE
    _FLY_MODE = False
    if _is_maximized():
        _maximize_toggle()              # bring the full interface back
    for win, area in _iter_view3d():
        for space in area.spaces:
            if space.type != "VIEW_3D":
                continue
            try:
                space.overlay.show_overlays = True
                space.show_gizmo = True
                space.show_gizmo_navigate = True
                space.show_region_header = True
                space.show_region_toolbar = True
            except Exception:
                pass
            space.lock_camera = False
        area.tag_redraw()
    _set_keymap_fly(False)
    _sync_view_toggles()


def _set_frame_view(on):
    """Frame View toggle. ON = look THROUGH the export-frame camera (WYSIWYG, with
    passepartout) AND lock the camera to the view, so orbit / pan / zoom / walk move
    the CAMERA and you stay in-frame while composing. OFF = free perspective nav
    (camera stays put, explore freely)."""
    sc = bpy.context.scene
    cam = sc.camera
    if on and cam is not None:
        try:
            cam.data.show_passepartout = True
            cam.data.passepartout_alpha = 0.9
        except Exception:
            pass
    for win, area in _iter_view3d():
        for space in area.spaces:
            if space.type != "VIEW_3D":
                continue
            try:
                space.lock_camera = bool(on)      # navigate the camera while framed
            except Exception:
                pass
            r3d = getattr(space, "region_3d", None)
            if r3d is not None:
                if on:
                    r3d.view_perspective = "CAMERA"
                    _anchor_view_pivot(r3d)       # model-scaled pan / orbit
                elif r3d.view_perspective == "CAMERA":
                    r3d.view_perspective = "PERSP"
        area.tag_redraw()


def _anchor_view_pivot(r3d):
    """Anchor orbit / pan to the model so navigation is model-scaled, not driven by
    the far background. Sets the view pivot to the model centre and the orbit radius
    to the camera->centre distance (with Auto Depth off, this is what governs how far
    a pan moves)."""
    cam = bpy.context.scene.camera
    center = _model_center()
    if cam is None or center is None:
        return
    try:
        r3d.view_location = center
        r3d.view_distance = max(0.1, (cam.matrix_world.translation - center).length)
    except Exception:
        pass


def _enter_frame():
    """Turn Frame View on and keep the panel toggle in sync (used by Capture /
    Regenerate so they show the framed result, navigable)."""
    global _SYNCING
    st = getattr(bpy.context.scene, "bir", None)
    if st is not None:
        _SYNCING = True
        try:
            st.frame_view = True
        finally:
            _SYNCING = False
    _set_frame_view(True)


def _frame_free_view():
    win, area = _first_view3d()
    if area is None:
        return
    cam = bpy.context.scene.camera
    center = _model_center()
    if cam is None or center is None:
        _run_in_view3d(lambda: bpy.ops.view3d.view_all())
        return
    for space in area.spaces:
        if space.type != "VIEW_3D":
            continue
        r3d = getattr(space, "region_3d", None)
        if r3d is None:
            continue
        try:
            r3d.view_perspective = "PERSP"
            r3d.view_rotation = cam.matrix_world.to_quaternion()
            eye = cam.matrix_world.translation
            r3d.view_location = center
            r3d.view_distance = max(0.1, (eye - center).length)
        except Exception:
            pass
    area.tag_redraw()


# --- keymap -----------------------------------------------------------------
_KEYMAP_ITEMS = []   # (keymap_item, fly_only)


def _bind_keymap():
    global _KEYMAP_BOUND
    if _KEYMAP_BOUND:
        return
    try:
        kc = bpy.context.window_manager.keyconfigs.addon
        if kc is None:
            return
        km = kc.keymaps.new(name="3D View", space_type="VIEW_3D")
        for key in ("RET", "NUMPAD_ENTER"):
            _KEYMAP_ITEMS.append(
                (km.keymap_items.new("bir.render_image", key, "PRESS"), True))
        _KEYMAP_ITEMS.append(
            (km.keymap_items.new("bir.toggle_mode", "F10", "PRESS"), False))
        _KEYMAP_ITEMS.append(
            (km.keymap_items.new("bir.regenerate_lines", "L", "PRESS"), True))
        _KEYMAP_BOUND = True
    except Exception:
        pass


def _set_keymap_fly(fly):
    """Fly-only shortcuts (Enter = capture, L = regen) shadow Blender's own keys
    (select-linked etc.), so they are active only in Fly mode. F10 stays live in
    both modes - it is the way back."""
    for kmi, fly_only in _KEYMAP_ITEMS:
        if fly_only:
            try:
                kmi.active = bool(fly)
            except Exception:
                pass


# --- on-screen overlay (HUD) -----------------------------------------------
def _blf_size(fid, size):
    try:
        blf.size(fid, size)
    except Exception:
        try:
            blf.size(fid, size, 72)
        except Exception:
            pass


def _draw_busy(fid, w, h):
    label = ("WORKING  -  %s ..." % _BUSY_LABEL) if _BUSY_LABEL else "WORKING ..."
    _blf_size(fid, 22)
    blf.color(fid, 1.0, 0.85, 0.25, 1.0)
    try:
        tw = blf.dimensions(fid, label)[0]
    except Exception:
        tw = 0.0
    blf.position(fid, max(26.0, (w - tw) * 0.5), h * 0.5, 0)
    blf.draw(fid, label)


def _draw_hud():
    if blf is None:
        return
    try:
        region = bpy.context.region
        w = region.width if region else 1200
        h = region.height if region else 900
        fid = 0
        if _BUSY:
            _draw_busy(fid, w, h)      # show even in Build mode (mode switches)
        if not _FLY_MODE:
            return
        _blf_size(fid, 16)
        blf.color(fid, 0.75, 0.9, 1.0, 0.9)
        blf.position(fid, 26, h - 34, 0)
        blf.draw(fid, _TITLE)
        # model / engine / mode readout (the requested status HUD)
        st = getattr(bpy.context.scene, "bir", None)
        info = "MODEL  %s        ENGINE  %s        MODE  %s" % (
            _MODEL_NAME or "-", (st.engine if st else "-"), (st.mode if st else "-"))
        _blf_size(fid, 12)
        blf.color(fid, 0.6, 0.85, 1.0, 0.85)
        blf.position(fid, 26, h - 54, 0)
        blf.draw(fid, info)
        _blf_size(fid, 12)
        blf.color(fid, 1.0, 1.0, 1.0, 0.55)
        y = h - 80
        for line in _CONTROLS:
            blf.position(fid, 26, y, 0)
            blf.draw(fid, line)
            y -= 19
        if _STATUS:
            _blf_size(fid, 14)
            blf.color(fid, 0.7, 0.95, 1.0, 0.9)
            blf.position(fid, 26, 24, 0)
            blf.draw(fid, _STATUS)
    except Exception:
        pass


def _register_hud():
    global _HUD_HANDLE
    if _HUD_HANDLE is not None:          # idempotent: never stack two handlers
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_HUD_HANDLE, "WINDOW")
        except Exception:
            pass
        _HUD_HANDLE = None
    try:
        _HUD_HANDLE = bpy.types.SpaceView3D.draw_handler_add(
            _draw_hud, (), "WINDOW", "POST_PIXEL")
    except Exception:
        _HUD_HANDLE = None


def _deferred_setup():
    """Establish the clean Fly interface once the window is ready. Retries until it
    actually takes (the viewport context isn't reliably ready on the first ticks,
    which caused the intermittent 'full Blender UI / no N-panel' startup)."""
    global _SETUP_TRIES
    _SETUP_TRIES += 1
    win, area = _first_view3d()
    if area is None:
        return 0.3 if _SETUP_TRIES < 40 else None
    _bind_keymap()
    _sync_settings_from_scene()
    _enter_fly()
    _frame_free_view()
    # Verify the stripped Fly state (single maximized viewport) actually stuck;
    # if not, try again shortly. The N-panel is force-opened inside _enter_fly.
    if not _is_maximized() and _SETUP_TRIES < 40:
        return 0.3
    return None


def _model_label(bundle_ref):
    """A friendly model name for the HUD, from the cache folder (drops the hash)."""
    try:
        folder = os.path.basename(os.path.dirname(bundle_ref))
        base, sep, tail = folder.rpartition("_")
        if sep and len(tail) == 8 and all(c in "0123456789abcdef" for c in tail.lower()):
            return base
        return folder or "model"
    except Exception:
        return "model"


def _init_camera_panel():
    """One-time: reflect the camera the scene was built with into the View panel, so
    the Projection / Framing controls start in sync with what's on screen (the camera
    was already configured by setup_camera from the same spec values)."""
    global _SYNCING
    st = getattr(bpy.context.scene, "bir", None)
    if st is None or _SPEC is None:
        return
    c = _SPEC.get("camera", {})
    if str(c.get("type")) == "orthographic":
        proj = "ORTHO"
    elif bool(c.get("two_point_perspective", False)):
        proj = "TWO_POINT"
    else:
        proj = "PERSP"
    _SYNCING = True
    try:
        st.projection = proj
        st.focal_length = float(c.get("focal_length_mm") or 0.0)
        st.lens_shift = float(c.get("shift_y", 0.0))
    except Exception:
        pass
    finally:
        _SYNCING = False


def _init_sun():
    """One-time: seed the Sun panel from the Revit-extracted location + sun, then
    apply. Defaults to By-Date-Time (a usable, draggable sun) when a location is
    known; otherwise Manual seeded from the extracted Revit azimuth/altitude."""
    global _SYNCING
    st = getattr(bpy.context.scene, "bir", None)
    if st is None or _SPEC is None:
        return
    sun = _SPEC.get("sun", {})
    lat = sun.get("latitude")
    lon = sun.get("longitude")
    _SYNCING = True
    try:
        if lat is not None:
            st.sun_lat = float(lat)
        if lon is not None:
            st.sun_lon = float(lon)
            st.sun_tz = round(float(lon) / 15.0)     # natural tz unless Revit gives one
        if sun.get("timezone") is not None:
            st.sun_tz = float(sun["timezone"])
        d = sun.get("date")
        if d:
            try:
                p = str(d).split("-")
                st.sun_month = int(p[1])
                st.sun_day = int(p[2])
            except Exception:
                pass
        t = sun.get("time")
        if t:
            try:
                p = str(t).split(":")
                st.sun_time = int(p[0]) + (int(p[1]) / 60.0 if len(p) > 1 else 0.0)
            except Exception:
                pass
        if lat is None or lon is None:
            st.sun_use_datetime = False              # no location -> manual sun
            if sun.get("azimuth_degrees") is not None:
                st.sun_azimuth = float(sun["azimuth_degrees"]) % 360.0
            if sun.get("altitude_degrees") is not None:
                st.sun_altitude = max(0.0, min(90.0, float(sun["altitude_degrees"])))
    finally:
        _SYNCING = False
    _apply_user_sun(st)


def main():
    global _MODEL_NAME, _BUILD_ARGS, _BUSY, _BUSY_LABEL
    root = _repo_root()
    if root not in sys.path:
        sys.path.insert(0, root)
    ns = _parse_args()
    _set_nav_prefs()
    _MODEL_NAME = _model_label(ns.bundle)
    _BUILD_ARGS = ns

    # Register UI + HUD FIRST so the N-panel + overlay always exist, even if the
    # build hiccups. Then show a "Building model..." banner and run the heavy build
    # on a timer so the window paints the banner before it blocks - otherwise a
    # fresh import just looks like a frozen default Blender for ~20-30s.
    _register_ui()
    _register_hud()
    _BUSY = True
    _BUSY_LABEL = "Building model"
    try:
        # persistent=True is LOAD-BEARING: the build stages themselves load files
        # (open_mainfile on the cached path, read_factory_settings inside
        # reset_scene on the fresh path), and a file load removes non-persistent
        # timers - the chain would die right after that stage, freezing the
        # banner on the next label with the build never finishing.
        bpy.app.timers.register(_deferred_build, first_interval=0.1,
                                persistent=True)
    except Exception:
        while _deferred_build() is not None:   # no timers: run the stages inline
            pass
    print("Blendit: live session starting (building scene)...")


def _build_steps():
    """The heavy scene build as a generator: it yields a banner label BEFORE each
    blocking stage, and the driver (_deferred_build) repaints between yields - so
    the user watches real stages tick by instead of one frozen 'Building model'."""
    global _CAPTURE_DIR, _LOADED, _SPEC, _SCALE, _STATUS, _OVERRIDE_DIR
    ns = _BUILD_ARGS
    overrides = {"camera_type": "perspective"}
    if ns.engine:
        overrides["engine"] = ns.engine
    if ns.mode:
        overrides["mode"] = ns.mode

    from bir_contract.transport import bundle_dir_of
    from blender.pipeline.run import import_scene, prepare_scene, _apply_overrides
    from blender.pipeline import cache as bir_cache

    if ns.blend and os.path.isfile(ns.blend):
        # FAST PATH: open the cached prepared scene (no re-import).
        yield "Opening cached scene"
        print("Blendit: opening cached scene (%s)" % ns.blend)
        bir_cache.open_blend(ns.blend)
        _set_nav_prefs()                 # reassert session prefs after load
        _LOADED, _SPEC = bir_cache.loaded_from_blend(ns.bundle)
        _SPEC["_override_dir"] = bundle_dir_of(ns.bundle)  # honour the saved overrides
        _apply_overrides(_SPEC, overrides)
    else:
        # FRESH IMPORT: bring geometry in, cache the clean scene, then prepare.
        yield "Importing geometry"
        _LOADED, _SPEC = import_scene(ns.bundle, overrides=overrides or None)
        if ns.save_blend:
            yield "Caching scene for fast reopen"
            try:
                bir_cache.save_clean_blend(ns.save_blend)
                print("Blendit: cached scene -> %s" % ns.save_blend)
            except Exception as ex:
                print("Blendit: could not cache .blend (%s)" % ex)

    yield "Applying materials, light & camera"
    prepare_scene(_LOADED, _SPEC)

    yield "Preparing panels"
    if _SPEC is not None:
        _SCALE = float(_SPEC.get("units", {}).get("scale_to_meters", 1.0))
    _CAPTURE_DIR = ns.capture_dir or bundle_dir_of(ns.bundle)
    _OVERRIDE_DIR = bundle_dir_of(ns.bundle)
    if _SPEC is not None:
        _SPEC["_override_dir"] = _OVERRIDE_DIR
    _init_sun()                              # seed + apply the Revit-style sun once
    _init_camera_panel()                     # reflect the built camera into the View panel
    _init_materials()                        # build the Materials list + apply saved overrides
    _register_hud()                          # ensure the HUD survived open_mainfile


_BUILD_GEN = None


def _finish_build():
    """Common tail for success AND failure: drop the busy banner and bring up the
    Fly interface (the panels are registered, so the session stays usable)."""
    global _BUSY, _BUSY_LABEL
    _BUSY = False
    _BUSY_LABEL = ""
    _redraw_all()
    try:
        bpy.app.timers.register(_deferred_setup, first_interval=0.1)
    except Exception:
        _deferred_setup()


def _deferred_build():
    """Timer driver for _build_steps: runs ONE stage per tick and repaints the
    banner with the next stage's name in between, so progress is visible."""
    global _BUILD_GEN, _BUSY_LABEL, _STATUS
    if _BUILD_GEN is None:
        _BUILD_GEN = _build_steps()
    try:
        label = next(_BUILD_GEN)
    except StopIteration:
        _BUILD_GEN = None
        _finish_build()
        print("Blendit: live session ready (Fly mode). N for the panel, "
              "Enter to capture, Render Final for a high-quality shot, "
              "F10 for full UI.")
        return None
    except Exception as ex:
        _BUILD_GEN = None
        _STATUS = "Load error: %s (see console)" % ex
        print("Blendit: scene build FAILED: %s" % ex)
        import traceback
        traceback.print_exc()
        _finish_build()
        return None
    _BUSY_LABEL = label
    _redraw_all()
    return 0.05                # let the banner paint, then run the next stage


# Blender runs this with --python (so __name__ == "__main__"); tests can import the
# module to validate class registration without launching a full session.
if __name__ == "__main__":
    main()
