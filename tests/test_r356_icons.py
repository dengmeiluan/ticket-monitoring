# -*- coding: utf-8 -*-
"""r356 icon architecture: complete official marks, real aircraft families, parity."""
import base64
import hashlib
import io
import json
import os
import re

from PIL import Image, ImageChops

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
STYLE = re.search(r"<style>(.*?)</style>", SRC, re.S).group(1)


def _const(name):
    m = re.search(r"const %s=(\{.*?\});\n" % re.escape(name), SRC, re.S)
    assert m, name
    return json.loads(m.group(1))


BRAND = _const("SRX_BRAND_IMG")
AIR = _const("SRX_AIR_IMG")
META = _const("SRX_AIR_META")
SPRITE = re.search(r'<svg id="plSprite".*?</svg>', SRC, re.S).group(0)
PLANE_MODEL_SRC = re.search(r"const SRX_PLANE_MODEL=(\{.*?\});\n", SRC, re.S).group(1)
PLANE_CODE_SRC = re.search(r"const SRX_PLANE_CODE=(\{.*?\});\n", SRC, re.S).group(1)
PLANE_MODEL_KEYS = re.findall(r"\b([a-z][a-z0-9]*)\s*:\{maker:", PLANE_MODEL_SRC)
PLANE_CODES = dict(re.findall(r"'([A-Z0-9]+)'\s*:\s*'([a-z0-9]+)'", PLANE_CODE_SRC))
SPRITE_IDS = set(re.findall(r'<symbol id="pl-([a-z0-9]+)"', SPRITE))


def _png(uri):
    assert uri.startswith("data:image/png;base64,"), uri[:32]
    raw = base64.b64decode(uri.split(",", 1)[1])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    return Image.open(io.BytesIO(raw)).convert("RGBA"), raw


def _nonwhite_bbox(im):
    r, g, b = im.convert("RGB").split()
    darkest = ImageChops.darker(ImageChops.darker(r, g), b)
    box = darkest.point(lambda v: 0 if v > 245 else 255, mode="1").getbbox()
    assert box, "blank icon"
    x0, y0, x1, y1 = box
    return x0, y0, x1 - 1, y1 - 1


DATA_CODES = set(
    "MU CZ FM CA MF HO 9C 3U ZH HU SC GS SQ Y8 OZ JL UQ QR HX AQ KE NX G5 NH MH TG "
    "PN VN CX VJ D7 GA AY EY BK UA LH PR TK GF PG AA OD 9H AC KY DL LX RY JD IJ BR "
    "EK KL FU NZ EU ET KN NS BA GK AF DZ GJ QW 9G CI VZ".split()
)


def test_five_ota_marks_are_full_bleed_complete_official_pngs():
    assert set(BRAND) == {"qunar", "ctrip", "tuniu", "fliggy", "tongcheng"}
    for key, uri in BRAND.items():
        im, _ = _png(uri)
        assert im.size == (256, 256), (key, im.size)
        # Full-bleed tiles: the official field reaches every corner, so no white crop ring.
        for xy in ((0, 0), (255, 0), (0, 255), (255, 255)):
            r, g, b, _ = im.getpixel(xy)
            assert max(r, g, b) - min(r, g, b) > 8 or max(r, g, b) < 240, (key, xy)
        # Ctrip's dolphin tail must not touch the tile edge (the old crop was clipped).
        if key == "ctrip":
            r, g, b = im.convert("RGB").split()
            darkest = ImageChops.darker(ImageChops.darker(r, g), b)
            box = darkest.point(lambda v: 255 if v > 235 else 0, mode="1").getbbox()
            assert box
            x0, y0, x1, y1 = box
            assert min(x0, y0, 256 - x1, 256 - y1) >= 8


def test_airline_catalog_matches_meta_and_covers_all_real_codes():
    assert len(AIR) == 87 and len(META) == 89
    # W1 (World Ticket) and LT (Longjiang) have no verified official icon:
    # they fall back to an honest IATA tile instead of a fabricated mark.
    assert set(META) - set(AIR) == {"W1", "LT"}
    assert set(AIR) <= set(META)
    assert DATA_CODES <= set(AIR)
    for code in ("JD", "UQ", "RY", "FU", "9H", "9D", "GY"):
        assert code in AIR and code in META
    seen = {}
    for code, uri in AIR.items():
        im, raw = _png(uri)
        assert len(raw) > 1000, code
        assert im.size == (192, 192), (code, im.size)
        digest = hashlib.sha1(raw).hexdigest()
        assert digest not in seen, (code, seen.get(digest))
        seen[digest] = code
        name, color = META[code]
        assert name and re.fullmatch(r"#[0-9a-f]{6}", color), code
        _nonwhite_bbox(im)
    # 9H was a clipped source; the replacement must have breathing room on all sides.
    im, _ = _png(AIR["9H"])
    x0, y0, x1, y1 = _nonwhite_bbox(im)
    assert min(x0, y0, 191 - x1, 191 - y1) >= 5


def test_airline_name_resolver_precedes_false_embedded_codes():
    for name in ("东航", "国航", "南航", "海航", "春秋", "吉祥", "山航", "上航", "天津", "阿联酋", "国泰", "英航", "亚航X"):
        assert "'%s':'" % name in SRC
    assert "'亚航X':'D7'" in SRC
    fn = re.search(r"function srxAirCode\(v\)\{(.*?)\n\}", SRC, re.S).group(1)
    assert fn.index("SRX_AIR_NAME") < fn.index("const emb=")
    assert 'class="bic bic-air' in SRC and "style=\"--ac:'+m.color+'\"" in SRC


def test_real_aircraft_codes_map_to_model_families():
    expected = {
        "738": "b737", "73H": "b737", "7M8": "b737max", "32Q": "a321",
        "359": "a350", "77W": "b777", "388": "a380", "919": "c919",
        "C909": "arj21", "290": "ejet", "333": "a330", "789": "b787",
    }
    for code, key in expected.items():
        assert PLANE_CODES.get(code) == key, (code, PLANE_CODES.get(code))
    assert set(PLANE_CODES.values()) <= set(PLANE_MODEL_KEYS)
    assert "unknown" in PLANE_MODEL_KEYS
    # Every model family has a sprite symbol, including the honest unknown fallback.
    assert set(PLANE_MODEL_KEYS) == SPRITE_IDS
    assert len(PLANE_MODEL_KEYS) == 22
    assert PLANE_CODES.get("32S") == "a320"
    assert PLANE_CODES.get("DH8D") == "turboprop"
    assert "SRX_PLANE_RANGE" in SRC and "range=true" in SRC
    for key in ("a320", "a321", "a330", "a350", "a380", "b737", "b737max",
                "b747", "b767", "b777", "b787", "c919", "arj21", "ejet", "atr",
                "turboprop", "unknown"):
        assert "pl-" + key in SPRITE


def test_aircraft_icons_are_textured_and_honest():
    assert "SRX_PLANE_BODY" not in SRC
    assert "制造商识别色" in SRC and "体量口径" in SRC and "不冒充" in SRC
    assert "function srxPlaneIcon(" in SRC and '<use href="#pl-\'+m.key+\'"/>' in SRC
    for needle in ("--pl-w1:", "--pl-w2:", "--pl-w3:", "drop-shadow(0 0 .55px"):
        assert needle in STYLE
    assert ".bic-plane svg{width:100%;height:100%" in STYLE
    # unknown must render a symbol rather than a blank <use>
    assert 'id="pl-unknown"' in SPRITE and 'stroke-dasharray="1.1 1"' in SPRITE


def test_icons_wired_into_all_identity_surfaces():
    for needle in (
        "srxAirIcon(a[0])", "srxPlaneIcon(a)",
        "srxAirIcon(f.code)", "srxPlaneIcon(f.plane||f.planeSize)",
        "const planeMark=!cal&&(f.plane||f.planeSize)?srxPlaneIcon(f.plane||f.planeSize):''",
        "planeMark", "const airCode=srxAirCode(f.code);",
        "srxPlatIcon(srxPlatKey(x.plat)||x.plat)",
        "(f.plane||f.planeSize)?'<span class=\"nw nw-keep\"",
    ):
        assert needle in SRC, needle
    # Filters, detail grid, list rows and matrix all share the same helpers.
    assert SRC.count("srxPlaneIcon(") >= 8
    assert SRC.count("srxAirIcon(") >= 12


def test_control_icons_are_svg_not_emoji():
    label = re.search(r"function _fltCatLabel\(k\)\{(.*?)\}\n", SRC, re.S).group(1)
    for emoji in ("✈", "🔁", "🔥", "🧳"):
        assert emoji not in label
    assert "#i-sliders" in SRC and "#i-chart" in SRC and "#i-scale" in SRC
    assert "#i-flame" in SRC and "#i-bag" in SRC
    page = SRC[SRC.index('PAGE = r"""'):SRC.index('NOTIFY_PAGE = r"""')]
    assert "🚨" not in page and "✈️" not in page
    assert ".fire .ic{" in STYLE


def test_brand_css_keeps_semantic_shapes_and_texture():
    assert re.search(r"\.bic-ota\{[^}]*border-radius", STYLE)
    assert re.search(r"\.bic-air\{[^}]*border-radius:50%", STYLE)
    assert "color-mix(in srgb,var(--ac" in STYLE
    assert "radial-gradient(circle at 32% 22%" in STYLE
    assert ".bic-air>img{object-fit:contain;padding:7%}" in STYLE
