#!/usr/bin/env python3
"""Generate the Blendit ribbon icon set - one cohesive, distinct glyph per
Render.panel button.

The hand-assembled icons had five duplicated glyphs (Load==Open, Render==Open
Renders, Quality==Resolution==Settings), one missing (Views), and four clashing
styles. This regenerates all of them as line glyphs in the Blendit palette
(blue primary + orange accent), consistent stroke weight, drawn 4x super-
sampled for clean anti-aliasing.

    python tools/build_ribbon_icons.py            # write into the pushbuttons
    python tools/build_ribbon_icons.py --sheet    # also write out/_ribbon_icons.png

Re-run after tweaking a glyph. Icons are 96x96 RGBA, transparent background so
they sit on Revit's ribbon in either theme.
"""
import math
import os
import sys

from PIL import Image, ImageDraw

SS = 4                      # supersample factor
S = 96                      # final icon size
N = S * SS                  # working canvas

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANEL = os.path.join(REPO, "Blendit.tab", "Render.panel")

BLUE = (37, 110, 210, 255)      # primary stroke
ORANGE = (233, 123, 40, 255)    # accent
W = 7.0                         # stroke width in 96-space


def _c(v):
    return int(round(v * SS))


def _w(px=W):
    return max(1, int(round(px * SS)))


class G(object):
    """A tiny drawing helper in 96-unit space (scaled up by SS)."""
    def __init__(self):
        self.img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)

    def line(self, pts, color=BLUE, w=W, cap=True):
        p = [(_c(x), _c(y)) for x, y in pts]
        self.d.line(p, fill=color, width=_w(w), joint="curve")
        if cap:                          # round caps at both ends
            r = _w(w) / 2.0
            for x, y in (p[0], p[-1]):
                self.d.ellipse([x - r, y - r, x + r, y + r], fill=color)

    def rrect(self, x0, y0, x1, y1, rad, color=BLUE, w=W, fill=None):
        self.d.rounded_rectangle([_c(x0), _c(y0), _c(x1), _c(y1)],
                                 radius=_c(rad), outline=color, width=_w(w),
                                 fill=fill)

    def circle(self, cx, cy, r, color=BLUE, w=W, fill=None):
        self.d.ellipse([_c(cx - r), _c(cy - r), _c(cx + r), _c(cy + r)],
                       outline=color if w else None, width=_w(w), fill=fill)

    def dot(self, cx, cy, r, color=ORANGE):
        self.d.ellipse([_c(cx - r), _c(cy - r), _c(cx + r), _c(cy + r)],
                       fill=color)

    def arc(self, x0, y0, x1, y1, a0, a1, color=BLUE, w=W):
        self.d.arc([_c(x0), _c(y0), _c(x1), _c(y1)], a0, a1,
                   fill=color, width=_w(w))

    def arrowhead(self, tip, ang_deg, size=13, color=BLUE):
        """Filled triangle arrowhead at `tip`, pointing along ang_deg."""
        a = math.radians(ang_deg)
        back = (tip[0] - size * math.cos(a), tip[1] - size * math.sin(a))
        left = (back[0] + size * 0.55 * math.cos(a + math.pi / 2),
                back[1] + size * 0.55 * math.sin(a + math.pi / 2))
        right = (back[0] + size * 0.55 * math.cos(a - math.pi / 2),
                 back[1] + size * 0.55 * math.sin(a - math.pi / 2))
        self.d.polygon([(_c(tip[0]), _c(tip[1])), (_c(left[0]), _c(left[1])),
                        (_c(right[0]), _c(right[1]))], fill=color)

    def out(self):
        return self.img.resize((S, S), Image.LANCZOS)


# --- the eleven glyphs ------------------------------------------------------
def load_view():
    """Extract the Revit view INTO Blendit: a tray with a down arrow entering."""
    g = G()
    # open tray (bottom)
    g.line([(24, 58), (24, 74), (72, 74), (72, 58)], BLUE, W)
    # down arrow (the view being pulled in) - orange accent
    g.line([(48, 20), (48, 52)], ORANGE, W)
    g.arrowhead((48, 56), 90, 15, ORANGE)
    return g.out()


def open_view():
    """Open the loaded view in interactive Blender: launch-out of a frame."""
    g = G()
    g.rrect(22, 34, 58, 74, 7, BLUE, W)            # window/frame
    # arrow leaving up-right (open externally) - orange
    g.line([(50, 46), (74, 22)], ORANGE, W)
    g.arrowhead((76, 20), -45, 15, ORANGE)
    g.line([(60, 20), (76, 20)], ORANGE, W, cap=False)
    g.line([(76, 20), (76, 36)], ORANGE, W, cap=False)
    return g.out()


def render_view():
    """Headless render -> a framed image with a sun over hills."""
    g = G()
    g.rrect(20, 26, 76, 70, 7, BLUE, W)
    g.dot(58, 41, 6)                                # sun (orange)
    # hills (two joined strokes) inside the frame
    g.line([(26, 64), (40, 50), (52, 62), (62, 52), (70, 60)], BLUE, W)
    return g.out()


def views_list():
    """The loaded-views LIST: bulleted rows."""
    g = G()
    for y in (32, 48, 64):
        g.dot(26, y, 4.2)
        g.line([(38, y), (74, y)], BLUE, W)
    return g.out()


def mode_looks():
    """Render LOOKS: a deck of style cards, the top one accented."""
    g = G()
    g.rrect(24, 24, 58, 58, 6, BLUE, W)             # back card
    g.rrect(38, 38, 74, 74, 6, BLUE, W,
            fill=(37, 110, 210, 38))                # front card, faint blue tint
    g.rrect(38, 38, 74, 74, 6, BLUE, W)             # front card edge
    g.line([(38, 46), (74, 46)], ORANGE, W, cap=False)  # accent header
    return g.out()


def quality_gauge():
    """Effort preset: a speedometer dial with an orange needle."""
    g = G()
    g.arc(22, 30, 74, 82, 180, 360, BLUE, W)        # top-half dial
    g.line([(48, 56), (64, 38)], ORANGE, W)         # needle
    g.dot(48, 56, 5, ORANGE)                        # hub
    return g.out()


def resolution_size():
    """Output size: a frame with a diagonal resize arrow."""
    g = G()
    g.rrect(22, 28, 74, 68, 6, BLUE, W)
    g.line([(34, 40), (62, 56)], ORANGE, W)         # diagonal
    g.arrowhead((64, 57), 30, 12, ORANGE)
    g.arrowhead((32, 39), 210, 12, ORANGE)
    return g.out()


def engine_toggle():
    """Cycles / EEVEE toggle: a pill switch, knob to the right (orange)."""
    g = G()
    g.rrect(22, 40, 74, 66, 13, BLUE, W)            # stadium
    g.dot(61, 53, 9)                                # knob (orange, on the right)
    return g.out()


def open_renders():
    """Open the output FOLDER (an open folder, orange inner leaf)."""
    g = G()
    # back panel with tab
    g.line([(22, 38), (36, 38), (42, 44), (74, 44), (74, 68)], BLUE, W)
    g.line([(22, 38), (22, 68), (74, 68)], BLUE, W)
    # open front leaf (orange accent), splayed slightly forward
    g.line([(28, 68), (36, 50), (80, 50), (72, 68)], ORANGE, W)
    return g.out()


def settings_gear():
    """Settings: a gear."""
    g = G()
    cx, cy, r = 48, 50, 17
    for k in range(8):                              # teeth
        a = math.radians(k * 45)
        x0 = cx + (r + 1) * math.cos(a)
        y0 = cy + (r + 1) * math.sin(a)
        x1 = cx + (r + 9) * math.cos(a)
        y1 = cy + (r + 9) * math.sin(a)
        g.line([(x0, y0), (x1, y1)], BLUE, W)
    g.circle(cx, cy, r, BLUE, W)
    g.dot(cx, cy, 5)                                # orange hub
    return g.out()


def about_info():
    """About: an i in a ring."""
    g = G()
    g.circle(48, 50, 24, BLUE, W)
    g.dot(48, 38, 4.2)                              # the dot of the i (orange)
    g.line([(48, 47), (48, 63)], BLUE, W)           # the stem
    return g.out()


def sync_cycle():
    """Live sync: two arrows chasing around a circle (the delta link)."""
    g = G()
    # two arcs of one ring (PIL angles: 0 = 3 o'clock, clockwise, y-down)
    g.arc(26, 26, 70, 70, 180, 315, BLUE, W)        # top arc, 9:00 -> 1:30
    g.arc(26, 26, 70, 70, 0, 135, BLUE, W)          # bottom arc, 3:00 -> 7:30
    # arrowheads continue each arc's clockwise travel - orange accent
    g.arrowhead((64.4, 32.4), 45, 13, ORANGE)       # tip of the top arc
    g.arrowhead((31.6, 63.6), -135, 13, ORANGE)     # tip of the bottom arc
    return g.out()


ICONS = [
    ("LoadModel.pushbutton", load_view),
    ("OpenModel.pushbutton", open_view),
    ("RenderLoadedModel.pushbutton", render_view),
    ("Views.pushbutton", views_list),
    ("Sync.pulldown", sync_cycle),
    ("Mode.pulldown", mode_looks),
    ("Quality.pushbutton", quality_gauge),
    ("Resolution.pushbutton", resolution_size),
    ("Engine.pushbutton", engine_toggle),
    ("OpenRenders.pushbutton", open_renders),
    ("Settings.pushbutton", settings_gear),
    ("About.pushbutton", about_info),
]


def main():
    write_sheet = "--sheet" in sys.argv
    imgs = []
    for folder, fn in ICONS:
        im = fn()
        dst_dir = os.path.join(PANEL, folder)
        if os.path.isdir(dst_dir):
            im.save(os.path.join(dst_dir, "icon.png"))
        imgs.append((folder, im))
    print("wrote %d icons into %s" % (len(imgs), PANEL))

    if write_sheet:
        cell, pad = 100, 8
        bg = (44, 48, 56, 255)
        sheet = Image.new("RGBA", (len(imgs) * (cell + pad) + pad,
                                   cell + pad * 2 + 16), bg)
        d = ImageDraw.Draw(sheet)
        x = pad
        for name, im in imgs:
            im2 = im.resize((cell, cell))
            sheet.paste(im2, (x, pad), im2)
            d.text((x + 2, pad + cell + 2), name.split(".")[0][:13],
                   fill=(210, 210, 210, 255))
            x += cell + pad
        out = os.path.join(REPO, "out")
        if not os.path.isdir(out):
            os.makedirs(out)
        sheet.convert("RGB").save(os.path.join(out, "_ribbon_icons.png"))
        print("wrote sheet -> out/_ribbon_icons.png")


if __name__ == "__main__":
    main()
