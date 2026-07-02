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

print("SUN GEO OK")
