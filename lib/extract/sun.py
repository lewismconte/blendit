"""Active 3D view sun -> contract `sun` dict.

Revit's SunAndShadowSettings exposes Altitude + Azimuth at the active frame
directly, so we emit `direct` mode (no solar calc needed). Lat/long from the site
location are carried along for reference / future geographic mode.
"""
import math

from extract import _compat

DB = _compat.DB


def extract_sun(doc, view3d):
    sun = {"mode": "geographic", "latitude": None, "longitude": None,
           "timezone": None, "azimuth_degrees": None, "altitude_degrees": None,
           "strength": 1.0, "angle_degrees": 0.526}

    try:
        sass = view3d.SunAndShadowSettings
        if sass is not None:
            frame = sass.ActiveFrame
            az = sass.GetFrameAzimuth(frame)    # radians
            alt = sass.GetFrameAltitude(frame)  # radians
            sun["mode"] = "direct"
            sun["azimuth_degrees"] = math.degrees(az)
            sun["altitude_degrees"] = math.degrees(alt)
    except Exception:
        pass

    try:
        site = doc.SiteLocation
        sun["latitude"] = math.degrees(site.Latitude)    # stored in radians
        sun["longitude"] = math.degrees(site.Longitude)
        try:
            sun["timezone"] = float(site.TimeZone)       # hours from UTC
        except Exception:
            pass
    except Exception:
        pass

    return sun
