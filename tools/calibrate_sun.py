#!/usr/bin/env python3
"""Settle Revit's sun-azimuth convention against real solar geometry.

Sun conventions are the kind of thing you can argue about forever from docs.
This measures instead. Every cached extraction that carries Revit's OWN azimuth
AND altitude is a free calibration point: the site, the date and the two angles
are all recorded, so for each candidate reading of the azimuth we can sweep the
whole day and ask "is there any moment when the sun was actually there?". The
right convention fits some real moment on both axes at once. The wrong ones
cannot fit either, no matter what hour you allow them.

    python tools/calibrate_sun.py

Verdict as of 2026-09-02, over 11 views from five sample models (Melbourne,
Los Angeles, Pennsylvania, Boston x2):

    raw            (already CW from N)    median  0.24   worst  1.02
    90 - raw       (CCW from E)           median 23.23   worst 43.59
    -raw           (CCW from N)           median  0.25   worst  1.02
    raw + 180                             median 54.90   worst 75.55

so GetFrameAzimuth is already clockwise from north and only needs normalising -
which is what bir_extract.sun.compass_azimuth does. `raw` and `-raw` score alike
because a day is mirror-symmetric about solar noon: an azimuth and its
reflection share an altitude. The three views nearest solar noon break the tie,
where the two readings are furthest apart and `raw` wins outright:

    AXO Copy 1 (Melbourne, 21 Dec)    raw off by 0.64,  -raw off by 40.37
    Residential Lobby (PA, 21 Dec)    raw off by 1.08,  -raw off by  7.82
    Kitchen (Boston, 20 Dec)          raw off by 0.05,  -raw off by 21.12

Re-run this before changing compass_azimuth. It needs no Revit and no Blender.
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "blender", "pipeline"))
import sun_calc  # noqa: E402

CONVENTIONS = [
    ("raw            (already CW from N)", lambda r: r % 360.0),
    ("90 - raw       (CCW from E)", lambda r: (90.0 - r) % 360.0),
    ("-raw           (CCW from N)", lambda r: (-r) % 360.0),
    ("raw + 180", lambda r: (r + 180.0) % 360.0),
]


def cache_root():
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or "."
    return os.path.join(base, "blendit", "cache")


def bearing_delta(a, b):
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def best_fit(lat, lon, tz, doy, want_alt, want_az):
    """Worst-axis error at the minute of the day that fits both angles best."""
    best = None
    for step in range(0, 24 * 60):
        hour = step / 60.0
        az, alt = sun_calc.solar_position(lat, lon, doy, hour, tz)
        err = max(abs(alt - want_alt), bearing_delta(az, want_az))
        if best is None or err < best[0]:
            best = (err, hour)
    return best


def calibration_points(root):
    for path in sorted(glob.glob(os.path.join(root, "*", "**",
                                              "scene_spec.json"),
                                 recursive=True)):
        try:
            spec = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        sun = spec.get("sun") or {}
        if (sun.get("azimuth_degrees") is None
                or sun.get("altitude_degrees") is None
                or not sun.get("date")):
            continue                      # geographic-only view: nothing to check
        yield path, spec, sun


def main():
    root = cache_root()
    scores = dict((name, []) for name, _ in CONVENTIONS)
    seen = 0

    for path, spec, sun in calibration_points(root):
        raw = float(sun["azimuth_degrees"])
        alt = float(sun["altitude_degrees"])
        lat, lon = float(sun["latitude"]), float(sun["longitude"])
        tz = float(sun["timezone"]) if sun.get("timezone") is not None else lon / 15.0
        _y, month, day = [int(x) for x in sun["date"].split("-")]
        doy = sun_calc.day_of_year(month, day)
        model = os.path.relpath(path, root).split(os.sep)[0]
        seen += 1

        print("\n%s  |  %s  |  %s"
              % (model[:38], (spec.get("camera") or {}).get("name"), sun["date"]))
        print("   Revit raw azimuth %8.3f   altitude %7.3f" % (raw, alt))
        for name, convert in CONVENTIONS:
            az = convert(raw)
            err, hour = best_fit(lat, lon, tz, doy, alt, az)
            scores[name].append(err)
            print("     %-36s az %7.3f -> best fit %5.2fh, error %6.2f deg"
                  % (name, az, hour, err))

    if not seen:
        print("No cached extraction carries Revit's own sun angles yet.")
        print("Load a view whose Sun Setting is a Still (not the default")
        print("Lighting preset) and run this again.   Cache: %s" % root)
        return 1

    print("\n\n=============== VERDICT over %d cached views ===============" % seen)
    for name, _ in CONVENTIONS:
        errs = sorted(scores[name])
        print("  %-36s  median %6.2f   worst %6.2f"
              % (name, errs[len(errs) // 2], errs[-1]))
    print("\nLowest median wins. `raw` and `-raw` tie when every sample sits")
    print("far from solar noon - a day is mirror-symmetric about it - so break")
    print("ties on the views whose best-fit hour is nearest 12:00.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
