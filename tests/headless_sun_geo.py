"""Geographic sun accuracy checks (run under Blender - world.py needs bpy).

Locks the architect-facing promise: Melbourne in Revit is Melbourne in Blender,
at the same time of day. Verifies _sun_angles' priority + cross-check and that
the built Sun lamp actually points the right way.

Run: blender --background --python tests/headless_sun_geo.py
"""
import math
import os
import sys

import bpy
import mathutils

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
# bir_extract is the Revit-side package; it imports headless (guarded RevitAPI)
# and its azimuth conversion is the other half of the true-north story.
_LIB = os.path.join(_ROOT, "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from blender.pipeline import world  # noqa: E402

MELBOURNE = {"latitude": -37.81, "longitude": 144.96, "timezone": 10.0}
LONDON = {"latitude": 51.5, "longitude": -0.13, "timezone": 1.0}


def _sun(base, **kw):
    s = {"mode": "geographic", "strength": 1.0, "angle_degrees": 0.526}
    s.update(base)
    s.update(kw)
    return s


def _check(name, sun, want_alt, want_az, tol_alt=3.0, tol_az=15.0):
    alt, az = world._sun_angles(sun)
    d_az = world._az_delta(az, want_az)
    assert abs(alt - want_alt) <= tol_alt and d_az <= tol_az, (
        "%s: got alt=%.1f az=%.1f, wanted ~alt=%.1f az=%.1f"
        % (name, alt, az, want_alt, want_az))
    print("%-38s alt=%6.1f  az=%6.1f  OK" % (name, alt, az))


# 1. Southern hemisphere: Melbourne summer noon = HIGH sun from the NORTH.
_check("Melbourne Dec 21 noon (summer)",
       _sun(MELBOURNE, date="2026-12-21", time="12:00"), 75.1, 17.0)

# 2. Melbourne winter noon = LOW sun, still from the north.
_check("Melbourne Jun 21 noon (winter)",
       _sun(MELBOURNE, date="2026-06-21", time="12:00"), 28.5, 5.6)

# 3. Time of day carries: late afternoon sun swings to the WEST.
_check("Melbourne Dec 21 17:00 (west)",
       _sun(MELBOURNE, date="2026-12-21", time="17:00"), 29.2, 261.8)

# 4. Northern hemisphere sanity: London summer noon from the SOUTH.
_check("London Jun 21 noon (south)",
       _sun(LONDON, date="2026-06-21", time="12:00"), 59.5, 151.1)

# 5. Cross-check: bogus direct angles (a view-relative extraction) must LOSE
#    to the location + time when they disagree wildly.
_check("bogus direct angles overridden",
       _sun(MELBOURNE, date="2026-12-21", time="12:00",
            azimuth_degrees=150.0, altitude_degrees=10.0), 75.1, 17.0)

# 6. Direct angles that AGREE with location + time are kept verbatim.
alt, az = world._sun_angles(
    _sun(MELBOURNE, date="2026-12-21", time="12:00",
         azimuth_degrees=20.0, altitude_degrees=73.0))
assert (alt, az) == (73.0, 20.0), "agreeing direct angles must win: %s" % ((alt, az),)
print("%-38s alt=%6.1f  az=%6.1f  OK" % ("agreeing direct angles kept", alt, az))

# 7. No location at all -> the pleasant default, unchanged.
alt, az = world._sun_angles(_sun({}))
assert (alt, az) == (world._DEFAULT_ALT, world._DEFAULT_AZ), (alt, az)
print("%-38s alt=%6.1f  az=%6.1f  OK" % ("no data -> default", alt, az))

# 8. End to end: setup_world builds a Sun lamp actually pointing the right way.
bpy.ops.wm.read_factory_settings(use_empty=True)
spec = {"sun": _sun(MELBOURNE, date="2026-12-21", time="12:00"),
        "world": {"sky_type": "nishita", "strength": 1.0}}
world.setup_world(spec, 1.0)
sun_obj = bpy.data.objects.get("Sun")
assert sun_obj is not None, "setup_world built no Sun lamp"
bpy.context.view_layer.update()
to_sun = -(sun_obj.matrix_world.to_quaternion() @ mathutils.Vector((0, 0, -1)))
alt = math.degrees(math.asin(max(-1.0, min(1.0, to_sun.z))))
az = math.degrees(math.atan2(to_sun.x, to_sun.y)) % 360.0
assert abs(alt - 75.1) <= 3.0 and world._az_delta(az, 17.0) <= 15.0, (
    "Sun lamp points wrong: alt=%.1f az=%.1f" % (alt, az))
print("%-38s alt=%6.1f  az=%6.1f  OK" % ("Sun lamp orientation (end to end)", alt, az))

# 9. TRUE NORTH. Revit exports geometry on PROJECT north (+Y), while every
#    compass angle - Revit's own and the astronomical one - is measured from
#    TRUE north. Without coordinate_system.true_north_degrees the two are
#    silently out by exactly the project's north angle, which is a building
#    with its shadows in the wrong place and nothing on screen to say why.
assert world.north_offset({}) == 0.0, "a spec with no coordinate system is 0"
assert world.north_offset(
    {"coordinate_system": {"true_north_degrees": 30.0}}) == 30.0
assert world.north_offset(
    {"coordinate_system": {"true_north_degrees": None}}) == 0.0, "None is 0"

# True north 30 deg CCW of +Y means a compass bearing lands 30 deg lower in
# scene axes: due north (0) sits at 330 on the model's own compass.
assert abs(world.scene_azimuth(0.0, 30.0) - 330.0) < 1e-9, world.scene_azimuth(0.0, 30.0)
assert abs(world.scene_azimuth(90.0, 30.0) - 60.0) < 1e-9
assert abs(world.scene_azimuth(20.0, -45.0) - 65.0) < 1e-9   # the other way
assert abs(world.scene_azimuth(17.0, 0.0) - 17.0) < 1e-9     # no rotation, no change
print("%-38s OK" % "north offset maths")

# 10. End to end with a rotated north: the SAME sun must land 30 deg round.
bpy.ops.wm.read_factory_settings(use_empty=True)
spec = {"sun": _sun(MELBOURNE, date="2026-12-21", time="12:00"),
        "world": {"sky_type": "nishita", "strength": 1.0},
        "coordinate_system": {"true_north_degrees": 30.0}}
world.setup_world(spec, 1.0)
sun_obj = bpy.data.objects.get("Sun")
assert sun_obj is not None, "setup_world built no Sun lamp"
bpy.context.view_layer.update()
to_sun = -(sun_obj.matrix_world.to_quaternion() @ mathutils.Vector((0, 0, -1)))
rot_alt = math.degrees(math.asin(max(-1.0, min(1.0, to_sun.z))))
rot_az = math.degrees(math.atan2(to_sun.x, to_sun.y)) % 360.0
# Melbourne midsummer noon is az ~17 from true north; on a north turned 30 deg
# CCW that is ~347 in model axes. Altitude is untouched by a rotation.
assert abs(rot_alt - 75.1) <= 3.0, "altitude must not move: %.1f" % rot_alt
assert world._az_delta(rot_az, 347.0) <= 15.0, (
    "rotated north not applied to the Sun lamp: az=%.1f" % rot_az)
print("%-38s alt=%6.1f  az=%6.1f  OK"
      % ("Sun lamp follows true north", rot_alt, rot_az))

# 11. Revit's own frame azimuth is ALREADY clockwise from north - it just
#     arrives unnormalised, and can be negative. This was got wrong once, by
#     believing the API remark that it "differs from Revit's standard Lighting
#     Study Azimuth value" and reading it as counter-clockwise-from-east.
#     tools/calibrate_sun.py settles it against real solar geometry.
import bir_extract.sun as bir_sun                    # noqa: E402
import bir_extract.revit_extract as bir_extract_mod  # noqa: E402
for raw_deg, want in ((0.0, 0.0), (90.0, 90.0), (251.782, 251.782),
                      (-108.218, 251.782), (-176.922, 183.078)):
    got = bir_sun.compass_azimuth(math.radians(raw_deg))
    assert abs(got - want) < 1e-6, (
        "frame azimuth %.3f should read as %.3f clockwise from north, got %.3f"
        % (raw_deg, want, got))
print("%-38s OK" % "Revit frame azimuth -> compass")

# 12. The SIGN of the north angle. ProjectPosition.Angle turns PROJECT into
#     SURVEY, so true north is that far CLOCKWISE of project north, and the
#     contract wants it counter-clockwise. Backwards does not halve the error,
#     it doubles it: the real Woolfactory site reads -98.04 from the API, and
#     the wrong sign put its sun 196 deg out - which looks like "180 out".
assert abs(bir_extract_mod.true_north_from_project_angle(
    math.radians(-98.04)) - 98.04) < 1e-9
assert abs(bir_extract_mod.true_north_from_project_angle(
    math.radians(30.0)) + 30.0) < 1e-9
assert bir_extract_mod.true_north_from_project_angle(0.0) == 0.0

# ...and end to end: a site whose API angle is -98.04 must move its sun by
# +98.04, not -98.04. The two differ by 196 deg, so a sign slip can never hide.
tn = bir_extract_mod.true_north_from_project_angle(math.radians(-98.04))
assert abs(world.scene_azimuth(0.0, tn) - 261.96) < 1e-6, world.scene_azimuth(0.0, tn)
print("%-38s OK" % "true north sign (Woolfactory -98.04)")

print("SUN GEO OK")
