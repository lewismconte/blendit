"""SVG -> PDF converter checks (PLAIN CPYTHON -- no Blender).

Run standalone:   python tests/test_svg_to_pdf.py
Or under pytest:  pytest tests/test_svg_to_pdf.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from blender.pipeline.svg_to_pdf import svg_to_pdf, _subpaths, _paths

_SYNTH = (
    '<?xml version="1.0"?>\n'
    '<svg version="1.1" xmlns="http://www.w3.org/2000/svg" '
    'width="200px" height="100px" viewBox="0 0 200 100">'
    '<g><path d="M10,10L190,10L100,90z" fill="#1133cc" stroke="none" '
    'fill-opacity="1" />'
    '<path d="M20,20L40,20L40,40L20,40z" fill="#000000" stroke="none" /></g>'
    '</svg>')


def test_parse_paths_and_subpaths():
    paths = _paths(_SYNTH)
    assert len(paths) == 2, "should find two <path> elements"
    assert paths[0][1] == "#1133cc"
    subs = _subpaths(paths[0][0])
    assert len(subs) == 1
    # M + 2 L + Z(close) -> 4 points (last == first)
    assert subs[0][0] == (10.0, 10.0)
    assert subs[0][-1] == subs[0][0], "Z should close the loop"


def test_pdf_structure():
    pdf = svg_to_pdf(_SYNTH)
    assert pdf.startswith(b"%PDF-1."), "missing PDF header"
    for marker in (b"/MediaBox [0 0 200.000 100.000]", b"/Catalog", b"/Pages",
                   b"stream", b"endstream", b"xref", b"trailer",
                   b"startxref", b"%%EOF"):
        assert marker in pdf, "missing %r" % marker
    # content ops: colour, moveto, lineto, fill
    assert b" rg" in pdf and b" m" in pdf and b" l" in pdf and b"\nf" in pdf
    # y is flipped: SVG (10,10) -> PDF (10, 100-10=90)
    assert b"10.000 90.000 m" in pdf, "y-flip / translate wrong"
    # startxref offset actually points at the xref table
    tail = pdf.rsplit(b"startxref", 1)[1]
    off = int(tail.strip().split(b"\n")[0])
    assert pdf[off:off + 4] == b"xref", "startxref offset is wrong"


def test_real_export_if_present():
    """If a Blender-produced SVG is sitting in out/, convert it too (belt + braces
    against real exporter output, not just the synthetic one)."""
    real = os.path.join(_ROOT, "out", "vector_test.svg")
    if not os.path.isfile(real):
        return
    with open(real, "r", encoding="utf-8") as f:
        pdf = svg_to_pdf(f.read())
    assert pdf.startswith(b"%PDF-1."), "real SVG produced no PDF header"
    assert b" f\n" in pdf or pdf.rstrip().endswith(b"%%EOF")
    assert len(pdf) > 800, "real PDF suspiciously small"


if __name__ == "__main__":
    test_parse_paths_and_subpaths()
    test_pdf_structure()
    test_real_export_if_present()
    print("SVG2PDF OK")
