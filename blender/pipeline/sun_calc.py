"""Solar position: latitude / longitude / date / time -> azimuth + altitude.

Recreates the useful half of Revit's Sun Settings (place the sun by date + time at
the project location) so the live session can offer a time-of-day slider instead of
raw azimuth/altitude. Standard NOAA-style approximation - accurate to a degree or so,
which is plenty for architectural sun visualisation.

Azimuth is returned in the world.py convention: degrees from North (+Y), clockwise
toward East (+X)  ->  0 = N, 90 = E, 180 = S, 270 = W. Works in both hemispheres
(southern-hemisphere solar noon comes out near North, as it should).

Pure Python (no bpy) so it's unit-testable without Blender.
"""
import math

_DAYS_BEFORE_MONTH = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]


def day_of_year(month, day):
    m = max(1, min(12, int(month)))
    return _DAYS_BEFORE_MONTH[m - 1] + max(1, min(31, int(day)))


def solar_position(latitude_deg, longitude_deg, doy, hour, tz_offset=0.0):
    """-> (azimuth_deg [0..360 from N, CW], altitude_deg). `hour` is local clock
    time (e.g. 14.5 = 14:30); `tz_offset` is hours from UTC (for the longitude
    correction). When tz_offset is unknown, passing longitude/15 cancels the
    correction and `hour` is treated as local solar time."""
    lat = math.radians(latitude_deg)

    # Declination of the sun for the day of year.
    decl = math.radians(23.45) * math.sin(math.radians(360.0 / 365.0 * (doy - 81)))

    # Equation of time (minutes) + longitude/timezone correction -> solar time.
    b = math.radians(360.0 / 365.0 * (doy - 81))
    eot = 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)
    lstm = 15.0 * tz_offset                      # local standard time meridian
    time_corr = 4.0 * (longitude_deg - lstm) + eot
    solar_time = hour + time_corr / 60.0
    ha = math.radians(15.0 * (solar_time - 12.0))   # hour angle (afternoon > 0)

    sin_alt = (math.sin(lat) * math.sin(decl)
               + math.cos(lat) * math.cos(decl) * math.cos(ha))
    sin_alt = max(-1.0, min(1.0, sin_alt))
    alt = math.asin(sin_alt)

    cos_alt = math.cos(alt)
    denom_a = math.cos(lat) * cos_alt
    if abs(denom_a) < 1e-6 or abs(cos_alt) < 1e-6:
        return 0.0, math.degrees(alt)
    sin_az = -math.sin(ha) * math.cos(decl) / cos_alt
    cos_az = (math.sin(decl) - math.sin(lat) * sin_alt) / denom_a
    az = math.degrees(math.atan2(sin_az, cos_az))
    return (az + 360.0) % 360.0, math.degrees(alt)


if __name__ == "__main__":
    # quick sanity: London midsummer, sun should sweep E -> S -> W, peak ~62 deg
    for h in (6, 9, 12, 15, 18):
        az, alt = solar_position(51.5, -0.13, day_of_year(6, 21), h, tz_offset=1.0)
        print("%2dh  az=%6.1f  alt=%6.1f" % (h, az, alt))
