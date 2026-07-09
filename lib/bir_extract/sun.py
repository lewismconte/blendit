"""Active 3D view sun -> contract `sun` dict.

WHAT ARCHITECTS NEED: shadows that match the model's real place and time.
Extraction rules (user-specified):
  * The site location (SiteLocation Latitude/Longitude/TimeZone) is ALWAYS
    carried - Melbourne in Revit is Melbourne in Blender.
  * StillImage sun setting: the exact date + time of the view, plus Revit's
    own computed world-space azimuth/altitude when available.
  * One-day / multi-day solar studies (a time RANGE, no single truth): the
    study's start date at MIDDAY.
  * The 'Lighting' preset (Revit's default; usually RELATIVE TO VIEW, so its
    angles mean nothing in world space): keep the location, default to
    MIDDAY - a plausible, location-accurate sun instead of a hardcoded one.

The Blender side (pipeline/world.py) computes azimuth/altitude from
lat/long + date/time (pipeline/sun_calc.py) and cross-checks any direct
angles against that, so a bad angle extraction can never silently produce
wrong shadows.
"""
import datetime
import math

from bir_extract import _compat

DB = _compat.DB


def extract_sun(doc, view3d):
    sun = {"mode": "geographic", "latitude": None, "longitude": None,
           "timezone": None, "date": None, "time": None,
           "azimuth_degrees": None, "altitude_degrees": None,
           "strength": 1.0, "angle_degrees": 0.526}
    _site_location(doc, sun)
    _sun_settings(view3d, sun)
    if sun["azimuth_degrees"] is not None and sun["altitude_degrees"] is not None:
        sun["mode"] = "direct"
    return sun


def _site_location(doc, sun):
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


def _fmt_date(dt):
    return "%04d-%02d-%02d" % (dt.Year, dt.Month, dt.Day)


def _fmt_time(dt):
    return "%02d:%02d" % (dt.Hour, dt.Minute)


def _sun_settings(view3d, sun):
    try:
        sst = view3d.SunAndShadowSettings
    except Exception:
        sst = None
    if sst is None:
        # No sun settings at all: location-accurate midday, today.
        today = datetime.date.today()
        sun["date"] = "%04d-%02d-%02d" % (today.year, today.month, today.day)
        sun["time"] = "12:00"
        return

    stype = None
    try:
        stype = sst.SunAndShadowType
    except Exception:
        pass
    still = (DB is not None and stype == DB.SunAndShadowType.StillImage)

    # Date + time: exact for a still; MIDDAY of the start date for studies and
    # anything else (a range has no single truth - the agreed default).
    try:
        start = sst.StartDateAndTime
        # StartDateAndTime comes back in UTC (verified live: Revit showed 12:00,
        # the API gave 02:00 on a UTC+10 machine). Recover the SITE's wall clock by
        # adding the site's UTC offset (sun["timezone"], read from SiteLocation) -
        # machine-independent, so it stays correct when the render PC's timezone
        # differs from the project site's. (ToLocalTime() would use the machine's
        # zone and skew in that case.) The Blender side pairs this wall clock with
        # the same site timezone in the location+time sun calc; without a correct
        # moment that cross-check reads the wrong time, can overrule Revit's own sun
        # angles, and a noon render comes out black. Falls back to ToLocalTime() only
        # when the site timezone is unknown.
        tz = sun.get("timezone")
        try:
            if tz is not None:
                start = start.AddHours(float(tz))
            else:
                start = start.ToLocalTime()
        except Exception:
            pass
        sun["date"] = _fmt_date(start)
        sun["time"] = _fmt_time(start) if still else "12:00"
    except Exception:
        today = datetime.date.today()
        sun["date"] = "%04d-%02d-%02d" % (today.year, today.month, today.day)
        sun["time"] = "12:00"

    # Revit's own angles, ONLY when they are world space. The default
    # 'Lighting' preset is usually relative-to-view - those angles are
    # meaningless for shadows, so skip them and let location + time drive.
    try:
        if still:
            frame = sst.ActiveFrame
            sun["azimuth_degrees"] = math.degrees(sst.GetFrameAzimuth(frame))
            sun["altitude_degrees"] = math.degrees(sst.GetFrameAltitude(frame))
        elif (DB is not None and stype == DB.SunAndShadowType.Lighting
                and not getattr(sst, "RelativeToView", True)):
            sun["azimuth_degrees"] = math.degrees(sst.Azimuth)
            sun["altitude_degrees"] = math.degrees(sst.Altitude)
    except Exception:
        pass
