# -*- coding: utf-8 -*-
"""r360 search legibility floor + compact five-source strip + latest brand marks."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
STYLE = re.search(r"<style>(.*?)</style>", SRC, re.S).group(1)


def test_search_meta_text_has_an_11px_floor_and_darker_ink():
    for needle in (
        "#searchview .srx-src-sub{font-size:11px;color:var(--tx2)",
        "#searchview .srx-kpi .k{font-size:11px;color:var(--tx2)",
        "#searchview .srx-kpi .s{font-size:11px;color:var(--tx2)",
        "#searchview .srx-band-note{font-size:11px;color:var(--tx2)",
        "#searchview .srx-fl .sub{font-size:11px;color:var(--tx2)",
        "#searchview .srx-thead{font-size:11px;color:var(--tx2)",
        "#searchview .srx-b{font-size:11px;height:19px",
        "#searchview .srx-mtools button{font-size:11px}",
        "#searchview .srx-times .xday{font-size:11px",
    ):
        assert needle in STYLE, needle
    assert "@media(max-width:900px){#searchview .srx-hero-act .srx-btn{font-size:12px}}" in STYLE


def test_five_source_strip_is_compact_and_brand_tiles_are_larger():
    for needle in (
        'grid-template-areas:"h big a" "sub sub bar"',
        "#searchview .srx-src-h .p{width:22px;height:22px",
        "#searchview .srx-fl .sub{flex-wrap:nowrap;overflow:hidden}",
        "#searchview .srx-fl .srx-fieldmeter{display:none}",
    ):
        assert needle in STYLE, needle
    # The compact strip is desktop-only; mobile keeps the 148px stacked cards.
    assert "#searchview .srx-brief .srx-src{flex:0 0 148px}" in SRC


def test_brand_marks_are_current_official_tiles():
    m = re.search(r"const SRX_BRAND_IMG=(\{.*?\});\n", SRC, re.S)
    assert m
    import base64, io, json
    from PIL import Image, ImageChops
    obj = json.loads(m.group(1))
    for key in ("ctrip", "fliggy"):
        im = Image.open(io.BytesIO(base64.b64decode(
            obj[key].split(",", 1)[1]))).convert("RGBA")
        assert im.size == (256, 256), (key, im.size)
    # Ctrip's official tile keeps padding around the dolphin (no clip ring).
    im = Image.open(io.BytesIO(base64.b64decode(
        obj["ctrip"].split(",", 1)[1]))).convert("RGB")
    r, g, b = im.split()
    darkest = ImageChops.darker(ImageChops.darker(r, g), b)
    box = darkest.point(lambda v: 255 if v > 235 else 0, mode="1").getbbox()
    assert box
    x0, y0, x1, y1 = box
    assert min(x0, y0, 256 - x1, 256 - y1) >= 8


def test_available_channels_sort_first_and_zero_channels_sink():
    for needle in (
        "const score=real?3:(rs.some(f=>!srxIsStale(f))?2:(rs.length?1:0))",
        ".sort((a,b)=>b.score-a.score||b.real-a.real||a.idx-b.idx)",
        "function srxAvailChans(){",
        "real[b]-real[a]||cnt[b]-cnt[a]",
        "(rs.length?'':' zero')",
        "#searchview .srx-src.zero{",
    ):
        assert needle in SRC, needle
