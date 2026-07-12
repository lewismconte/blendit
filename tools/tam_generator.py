#!/usr/bin/env python3
"""Tonal Art Map (TAM) generator with style presets.

Implements the automatic line-art TAM construction algorithm from
Praun, Hoppe, Webb & Finkelstein, "Real-Time Hatching", SIGGRAPH 2001,
Section 4, plus the stylistic variation axes the paper names: "variation
in angle, cross-hatching schedule, range of lengths, and choice of stroke".

Key properties implemented:
  * Grid of images (mip level l x tone column t), finest 256x256, toroidal.
  * Stroke nesting: images filled left-to-right (light->dark) and
    top-to-bottom (coarse->fine); every stroke added to an image is also
    added to all finer images of the column, and each column starts as a
    copy of the previous (lighter) column.
  * Strokes keep constant *pixel* width at every mip level, so coarser
    levels reach the target tone with fewer strokes.
  * Candidate strokes: N random candidates (1000 for light columns,
    reduced to 100 for dark ones); the "best-fitting" candidate maximizes
    summed tone progress over all levels p of an image pyramid of every
    unfilled image in the column, normalized by stroke length.

Usage:  python tam_generator.py [--style ink|brush|sketchy|charcoal]
"""

import argparse
import math
import os
import random
import time

import numpy as np
from PIL import Image, ImageDraw

SEED = 7
LEVELS = 4                     # 0 = coarsest
RES = [32, 64, 128, 256]
TONES = 6
TARGET = [(c + 1) / 7.0 for c in range(TONES)]   # mean darkness per column
NCAND = [1000, 820, 640, 460, 280, 100]          # candidates per column
SS = 4                         # supersample factor for final AA rasters
BASE = os.path.dirname(os.path.abspath(__file__))

STYLES = {
    # the paper's main line-art style (unchanged from the first version)
    'ink': dict(
        width=2.0, dark=(0.85, 1.0), jitter=4.0, length=(0.3, 1.0),
        sag=0.006, taper=0.0, grain=0.0,
        schedule=[0, 0, 0, 90, 90, None],   # None = randomly 0 or 90
        cross_angle=90.0,
    ),
    # thick tapered wavy strokes, paint-brush feel (Fig 3 middle-ish)
    'brush': dict(
        width=4.6, dark=(0.72, 0.95), jitter=6.0, length=(0.35, 0.8),
        sag=0.02, taper=0.75, grain=0.0,
        schedule=[0, 0, 0, 0, 90, None],
        cross_angle=90.0,
    ),
    # thin translucent jittery strokes that build tone by layering
    'sketchy': dict(
        width=1.4, dark=(0.45, 0.7), jitter=14.0, length=(0.5, 1.1),
        sag=0.015, taper=0.3, grain=0.15,
        schedule=[0, 0, 65, 65, None, None],
        cross_angle=65.0,
    ),
    # broad grainy strokes, charcoal/crayon on paper
    'charcoal': dict(
        width=3.4, dark=(0.55, 0.9), jitter=7.0, length=(0.25, 0.7),
        sag=0.01, taper=0.4, grain=0.55,
        schedule=[0, 0, 0, 90, 90, None],
        cross_angle=90.0,
    ),
}


class TamBuilder:
    def __init__(self, style_name):
        self.style = STYLES[style_name]
        self.name = style_name
        self.rng = random.Random(SEED)
        # style-wide paper grain, sampled consistently in UV space
        nrng = np.random.default_rng(SEED + 1)
        g = nrng.random((64, 64)).astype(np.float32)
        g = np.asarray(Image.fromarray((g * 255).astype(np.uint8), 'L')
                       .resize((512, 512), Image.BICUBIC),
                       dtype=np.float32) / 255.0
        amp = self.style['grain']
        self.grain_img = 1.0 - amp * g          # multiplier in [1-amp, 1]

    # ---------------- stroke model ----------------

    def make_candidate(self, col):
        st = self.style
        base = st['schedule'][col]
        if base is None:
            base = 0.0 if self.rng.random() < 0.5 else st['cross_angle']
        ang = math.radians(base + self.rng.uniform(-st['jitter'], st['jitter']))
        return {
            "x": self.rng.random(), "y": self.rng.random(),
            "len": self.rng.uniform(*st['length']),
            "ang": ang,
            "sag": self.rng.uniform(-st['sag'], st['sag']),
            "dark": self.rng.uniform(*st['dark']),
        }

    def stroke_points(self, s, n=10):
        dx, dy = math.cos(s["ang"]), math.sin(s["ang"])
        px, py = -dy, dx
        pts = []
        for i in range(n + 1):
            t = i / n
            bow = s["sag"] * math.sin(math.pi * t)
            pts.append((s["x"] + dx * s["len"] * t + px * bow,
                        s["y"] + dy * s["len"] * t + py * bow))
        return pts

    def rasterize_fast(self, s, res):
        """Constant-width aliased raster for candidate scoring."""
        r = res
        img = Image.new("L", (r, r), 0)
        d = ImageDraw.Draw(img)
        w = max(1, round(self.style['width']))
        pts = self.stroke_points(s)
        for ox in (-1, 0, 1):
            for oy in (-1, 0, 1):
                poly = [((x + ox) * r, (y + oy) * r) for x, y in pts]
                xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
                if max(xs) < 0 or min(xs) > r or max(ys) < 0 or min(ys) > r:
                    continue
                d.line(poly, fill=255, width=w, joint="curve")
        return (np.asarray(img, dtype=np.float32) / 255.0) * s["dark"]

    def rasterize_final(self, s, res):
        """Supersampled raster with taper, grain, round caps."""
        st = self.style
        r = res * SS
        img = Image.new("L", (r, r), 0)
        d = ImageDraw.Draw(img)
        pts = self.stroke_points(s, n=12)
        n = len(pts) - 1
        for ox in (-1, 0, 1):
            for oy in (-1, 0, 1):
                poly = [((x + ox) * r, (y + oy) * r) for x, y in pts]
                xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
                if max(xs) < -r * 0.1 or min(xs) > r * 1.1 or \
                   max(ys) < -r * 0.1 or min(ys) > r * 1.1:
                    continue
                for i in range(n):
                    t = (i + 0.5) / n
                    prof = 1.0 - st['taper'] * (1.0 - math.sin(math.pi * t) ** 0.7)
                    w = max(1, round(st['width'] * SS * prof))
                    d.line([poly[i], poly[i + 1]], fill=255, width=w)
                    if w > 2:  # round joints
                        cx, cy = poly[i + 1]
                        d.ellipse([cx - w / 2, cy - w / 2, cx + w / 2, cy + w / 2],
                                  fill=255)
        a = np.asarray(img, dtype=np.float32) / 255.0
        a = a.reshape(res, SS, res, SS).mean(axis=(1, 3))
        if st['grain'] > 0:
            g = np.asarray(Image.fromarray(
                (self.grain_img * 255).astype(np.uint8), 'L')
                .resize((res, res), Image.BILINEAR), dtype=np.float32) / 255.0
            a = a * g
        return a * s["dark"]

    # ---------------- goodness (paper Section 4) ----------------

    @staticmethod
    def max_pyramid(a, min_size=4):
        pyr = [a]
        while a.shape[0] > min_size:
            n2 = a.shape[0] // 2
            a = a.reshape(n2, 2, n2, 2).max(axis=(1, 3))
            pyr.append(a)
        return pyr

    @staticmethod
    def composite(dst, stroke):
        return dst + stroke * (1.0 - dst)

    def goodness(self, cand_rasters, images, old_pyr_means, length):
        total = 0.0
        for lv, S in cand_rasters.items():
            new = self.composite(images[lv], S)
            for p_new, p_old_mean in zip(self.max_pyramid(new),
                                         old_pyr_means[lv]):
                total += float(p_new.mean()) - p_old_mean
        return total / length

    # ---------------- main fill loop ----------------

    def generate(self, out_dir):
        os.makedirs(out_dir, exist_ok=True)
        D = [[np.zeros((RES[l], RES[l]), np.float32) for _ in range(TONES)]
             for l in range(LEVELS)]
        t0 = time.time()
        for col in range(TONES):
            if col > 0:
                for lv in range(LEVELS):
                    D[lv][col] = D[lv][col - 1].copy()
            for lv in range(LEVELS):
                n_added = 0
                while float(D[lv][col].mean()) < TARGET[col]:
                    receiving = list(range(lv, LEVELS))
                    images = {r: D[r][col] for r in receiving}
                    old = {r: [float(p.mean())
                               for p in self.max_pyramid(images[r])]
                           for r in receiving}
                    best, best_g = None, -1.0
                    for _ in range(NCAND[col]):
                        s = self.make_candidate(col)
                        rasters = {r: self.rasterize_fast(s, RES[r])
                                   for r in receiving}
                        g = self.goodness(rasters, images, old, s["len"])
                        if g > best_g:
                            best, best_g = s, g
                    for r in receiving:
                        D[r][col] = self.composite(
                            D[r][col], self.rasterize_final(best, RES[r]))
                    n_added += 1
                    if n_added > 2000:  # safety valve
                        break
                print(f"[{self.name}] col {col} level {lv}: +{n_added:4d} "
                      f"strokes, tone {D[lv][col].mean():.3f} / "
                      f"{TARGET[col]:.3f}  [{time.time() - t0:7.1f}s]",
                      flush=True)
        for lv in range(LEVELS):
            for col in range(TONES):
                a = np.clip((1.0 - D[lv][col]) * 255.0, 0, 255).astype(np.uint8)
                Image.fromarray(a, "L").save(
                    os.path.join(out_dir, f"tam_l{lv}_t{col}.png"))
        pad = 6
        sheet = Image.new("L", (TONES * (RES[-1] + pad) + pad,
                                sum(r + pad for r in RES) + pad), 255)
        y = pad
        for lv in range(LEVELS):
            for col in range(TONES):
                a = np.clip((1.0 - D[lv][col]) * 255.0, 0, 255).astype(np.uint8)
                x = pad + col * (RES[-1] + pad) + (RES[-1] - RES[lv]) // 2
                sheet.paste(Image.fromarray(a, "L"), (x, y))
            y += RES[lv] + pad
        sheet.save(os.path.join(out_dir, "tam_contact_sheet.png"))
        print(f"[{self.name}] done in {time.time() - t0:.1f}s -> {out_dir}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--style", default="ink", choices=sorted(STYLES))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    out = args.out or os.path.join(
        BASE, "tam" if args.style == "ink" else f"tam_{args.style}")
    TamBuilder(args.style).generate(out)
