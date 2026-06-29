"""Headless check: NPR Line Art exports to true vector SVG + PDF.

    blender --background --python tests/headless_vector_export.py

Builds the fixture in pen mode, exports SVG + PDF, and asserts each is a real
vector file that actually carries the Line Art stroke geometry (not an empty
page). Needs Blender (uses bpy + the Grease Pencil exporter).
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main():
    from blender.pipeline.run import build_scene
    from blender.pipeline import vector_export

    bundle = os.path.join(_ROOT, "tests", "fixtures")
    out_dir = os.path.join(_ROOT, "out")
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    build_scene(bundle, overrides={"mode": "pen", "engine": "EEVEE",
                                   "camera_type": "perspective"})
    assert vector_export.has_line_art(), "pen mode built no Line Art GP"

    svg = vector_export.export_vector(os.path.join(out_dir, "vector_test.svg"), "svg")
    pdf = vector_export.export_vector(os.path.join(out_dir, "vector_test.pdf"), "pdf")

    svg_bytes = open(svg, "rb").read()
    pdf_bytes = open(pdf, "rb").read()
    print("svg %d bytes, pdf %d bytes" % (len(svg_bytes), len(pdf_bytes)))

    assert b"<svg" in svg_bytes, "not an SVG document"
    assert (b"<path" in svg_bytes or b"<polyline" in svg_bytes
            or b"<line" in svg_bytes or b"<polygon" in svg_bytes), \
        "SVG has no stroke geometry (Line Art didn't export)"
    assert pdf_bytes.startswith(b"%PDF"), "not a PDF document"
    assert len(pdf_bytes) > 600, "PDF suspiciously small (no strokes?)"

    print("VECTOR OK (svg + pdf with stroke geometry)")


if __name__ == "__main__":
    main()
