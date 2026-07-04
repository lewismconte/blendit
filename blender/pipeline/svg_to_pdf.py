"""Pure-Python SVG -> PDF for the Grease Pencil line export (no deps, no bpy).

Blender's native Grease Pencil PDF exporter is broken in the 5.0 build we target
(the HARU backend returns 'Unable to export PDF' and segfaults on repeat calls),
but its SVG export is solid. So Blendit exports SVG via Blender, then converts it
here into a true vector PDF (selectable paths, infinite zoom - not a raster).

The GP SVG uses only straight-segment paths (M / L / H / V / Z) with flat fills -
exactly what this minimal converter handles. Anything fancier is out of scope (the
exporter never emits curves for Line Art strokes).

Tested standalone under CPython: tests/test_svg_to_pdf.py.
"""
import re

# path data tokens: a command letter OR a (signed, decimal, exponent) number.
_TOKEN = re.compile(r"([MmLlHhVvZz])|(-?\d*\.?\d+(?:[eE][-+]?\d+)?)")
_VIEWBOX = re.compile(r'viewBox="\s*(-?[\d.]+)[\s,]+(-?[\d.]+)[\s,]+'
                      r'(-?[\d.]+)[\s,]+(-?[\d.]+)"')
_PATH = re.compile(r"<path\b([^>]*?)/?>", re.DOTALL)
_DATTR = re.compile(r'\bd="([^"]*)"', re.DOTALL)
_FILLATTR = re.compile(r'\bfill="([^"]*)"')


def _paths(svg):
    """[(d_string, fill_string), ...] for every <path> in the SVG."""
    out = []
    for m in _PATH.finditer(svg):
        attrs = m.group(1)
        dm = _DATTR.search(attrs)
        if not dm:
            continue
        fm = _FILLATTR.search(attrs)
        out.append((dm.group(1), fm.group(1) if fm else "#000000"))
    return out


def _subpaths(d):
    """Parse SVG path data into a list of subpaths, each a list of (x, y) points.
    Handles M/L/H/V/Z (absolute + relative); ignores anything else (Line Art emits
    only these)."""
    toks = [t for pair in _TOKEN.findall(d) for t in pair if t]
    subs, cur = [], []
    cx = cy = 0.0
    start = (0.0, 0.0)
    cmd = None
    i, n = 0, len(toks)

    def nextf():
        return float(toks[i])

    while i < n:
        t = toks[i]
        if t.isalpha():
            cmd = t
            i += 1
            if cmd in ("Z", "z"):
                if cur:
                    cur.append(cur[0])      # close the loop
                    subs.append(cur)
                    cur = []
                cx, cy = start
            continue
        if cmd in ("M", "m"):
            if i + 1 >= n:                     # trailing/partial pair: stop cleanly
                break
            x, y = nextf(), float(toks[i + 1]); i += 2
            if cmd == "m":
                x += cx; y += cy
            if cur:
                subs.append(cur)
            cur = [(x, y)]
            cx, cy, start = x, y, (x, y)
            cmd = "l" if cmd == "m" else "L"   # implicit lineto after moveto
        elif cmd in ("L", "l"):
            if i + 1 >= n:
                break
            x, y = nextf(), float(toks[i + 1]); i += 2
            if cmd == "l":
                x += cx; y += cy
            cur.append((x, y)); cx, cy = x, y
        elif cmd in ("H", "h"):
            x = nextf(); i += 1
            if cmd == "h":
                x += cx
            cur.append((x, cy)); cx = x
        elif cmd in ("V", "v"):
            y = nextf(); i += 1
            if cmd == "v":
                y += cy
            cur.append((cx, y)); cy = y
        else:
            i += 1                            # unknown token: skip, don't loop forever
    if cur:
        subs.append(cur)
    return subs


def _rgb(fill):
    h = fill.lstrip("#")
    if len(h) != 6:
        return 0.0, 0.0, 0.0
    return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0,
            int(h[4:6], 16) / 255.0)


def _viewbox(svg):
    m = _VIEWBOX.search(svg)
    if m:
        return [float(m.group(k)) for k in range(1, 5)]
    wm = re.search(r'\bwidth="([\d.]+)', svg)
    hm = re.search(r'\bheight="([\d.]+)', svg)
    return [0.0, 0.0, float(wm.group(1)) if wm else 800.0,
            float(hm.group(1)) if hm else 600.0]


def _unit_scale(svg):
    """PDF units are points (1/72"). If the SVG page is declared in mm (our
    paper-reframed export), scale coordinates + page mm->points; otherwise 1:1."""
    m = re.search(r'\bwidth="[\d.]+(mm|cm|in)"', svg)
    if not m:
        return 1.0
    return {"mm": 72.0 / 25.4, "cm": 72.0 / 2.54, "in": 72.0}[m.group(1)]


def _content(svg, minx, miny, h, s=1.0):
    """PDF content stream: fill each path's subpaths. SVG y is top-down, PDF y is
    bottom-up, so flip; translate by the viewBox origin; scale by `s` (unit->points)."""
    out = []
    for d, fill in _paths(svg):
        if fill == "none":
            continue
        subs = _subpaths(d)
        if not subs:
            continue
        r, g, b = _rgb(fill)
        out.append("%.4f %.4f %.4f rg" % (r, g, b))
        for sub in subs:
            x0, y0 = sub[0]
            out.append("%.3f %.3f m" % ((x0 - minx) * s, (h - (y0 - miny)) * s))
            for x, y in sub[1:]:
                out.append("%.3f %.3f l" % ((x - minx) * s, (h - (y - miny)) * s))
            out.append("h")
        out.append("f")                       # nonzero fill (matches SVG default)
    return "\n".join(out)


def svg_to_pdf(svg_text):
    """Convert a Grease-Pencil-exported SVG string to PDF bytes."""
    minx, miny, w, h = _viewbox(svg_text)
    s = _unit_scale(svg_text)
    content = _content(svg_text, minx, miny, h, s).encode("ascii")

    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.3f %.3f] "
         "/Contents 4 0 R >>" % (w * s, h * s)).encode("ascii"),
        b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n"
        + content + b"\nendstream",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += ("%d 0 obj\n" % i).encode("ascii") + body + b"\nendobj\n"
    xref_pos = len(out)
    count = len(objs) + 1
    out += ("xref\n0 %d\n" % count).encode("ascii")
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode("ascii")
    out += ("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (count, xref_pos)).encode("ascii")
    return bytes(out)
