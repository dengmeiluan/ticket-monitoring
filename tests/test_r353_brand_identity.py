# -*- coding: utf-8 -*-
"""r353 品牌语义层：官方渠道/航司图标内嵌、方形/圆形语义、到达上标零漂移。"""
import base64
import json
import os
import re

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


def _png_ok(uri):
    assert uri.startswith("data:image/png;base64,"), uri[:40]
    raw = base64.b64decode(uri.split(",", 1)[1])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    return len(raw)


def test_five_channels_are_embedded_official_marks():
    assert set(BRAND) == {"qunar", "ctrip", "tuniu", "fliggy", "tongcheng"}
    for key, uri in BRAND.items():
        assert _png_ok(uri) > 1500, key
        assert not re.search(r"https?://", uri), key


def test_airline_official_icons_cover_major_carriers():
    for code in ("MU", "CA", "CZ", "MF", "9C", "HO", "HU", "3U", "ZH", "SC"):
        assert code in AIR and _png_ok(AIR[code]) > 1500
        assert code in META and META[code][0]
    for code, (name, color) in META.items():
        assert re.fullmatch(r"[0-9A-Z]{2}", code), code
        assert name and re.fullmatch(r"#[0-9a-f]{6}", color), code


def test_icon_helpers_distinguish_channel_and_airline_semantics():
    assert "function srxPlatIcon(" in SRC
    assert "function srxAirIcon(" in SRC
    assert "bic bic-ota " in SRC and "bic bic-air " in SRC
    assert re.search(r"\.bic-ota\{[^}]*border-radius", STYLE)
    assert re.search(r"\.bic-air\{[^}]*border-radius:50%", STYLE)
    assert "官方图标" in SRC
    assert "官方航司图标" in SRC


def test_search_mirror_watch_and_config_use_brand_icons():
    assert "srxPlatIcon(f.platKey)" in SRC
    assert "srxAirIcon(f.code)" in SRC
    assert "srxPlatIcon(ch)" in SRC and "srxPlatIcon(c)" in SRC
    assert "srxPlatIcon(p)" in SRC and "srxPlatIcon(x.platKey)" in SRC
    assert "function wsBrandMark(" in SRC
    assert "srxPlatIcon(q.platform)" in SRC
    assert "srxPlatIcon(info.plat)" in SRC
    assert "srxAirIcon(w.code)" in SRC
    assert "srxFillStaticChips" in SRC
    assert "srxPlatIcon(srxPlatKey(f.platKey||f.plat))" in SRC
    assert "srxPlatIcon(PK[p]||'')" in SRC
    assert "srxPlatIcon(PKEY[m[0]]||'')" in SRC
    assert "srxPlatIcon(p)}${CN[p]||p}" in SRC
    assert "srxPlatIcon(p)}${PLATS[p]}" in SRC
    assert 'id="monWatchCard"' in SRC and 'id="monWatchList"' in SRC
    assert "const airCode=srxAirCode(f.code);" in SRC
    assert "const airOfficial=!cal&&!!airCode;" in SRC
    assert "function srxPlatKey(" in SRC
    assert 'data-plat="${srxPlatKey(f.platKey||f.plat)}"' in SRC
    assert ".ws-fident .mark.has-air" in STYLE
    assert "font-size:max(8px,calc(var(--bic) * .34))" in STYLE
    assert "${srxPlatIcon(p)}<span class=\"lgnm\">" in SRC
    assert "srx-wchip .bic" in STYLE


def test_arrival_superscript_cannot_shift_baseline():
    # +1 已移出到达时刻 <b>，成为独立网格列：不再参与任一文本行盒。
    m = re.search(re.escape("#searchview .srx-times .xday") + r"\{([^}]*)\}", STYLE)
    assert m
    body = m.group(1)
    assert "align-self:start" in body
    assert "vertical-align:3px" not in body
    assert re.search(r"#searchview \.srx-times b\{[^}]*line-height:18px", STYLE)
    assert re.search(r"#searchview \.srx-times\{[^}]*grid-template-columns:auto auto auto auto", STYLE)


def test_watch_tab_refresh_after_state_load():
    # 静默恢复深链时 S 未到，首拍 wsLoad 无用户；状态到达后必须补拉。
    assert "MONTAB==='watch'&&typeof wsLoad==='function')wsLoad(false)" in SRC
