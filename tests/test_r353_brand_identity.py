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
_AM = re.search(r"const SRX_BRAND_ALIAS=\{(.*?)\};", SRC, re.S)
ALIAS = dict(re.findall(r"(\w+):'(\w+)'", _AM.group(1) if _AM else ""))


def _brand_uri(p):
    return BRAND.get(p) or BRAND.get(ALIAS.get(p, ""))


def _png_ok(uri):
    assert uri.startswith("data:image/png;base64,"), uri[:40]
    raw = base64.b64decode(uri.split(",", 1)[1])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    return len(raw)


def test_every_channel_is_embedded_official_mark():
    """每个渠道（含两个 App 渠道）都必须有内嵌官方图标。

    只断言 5 家浏览器渠道时，新增的 app_zhixing/app_qunar 会静默没有
    图标（`srxPlatIcon` 取不到就返回空串、行里直接少一块）。
    """
    from core.channels import APP_CHANNELS, BROWSER_CHANNELS
    need = set(BROWSER_CHANNELS) | set(APP_CHANNELS)
    missing = [p for p in need if not _brand_uri(p)]
    assert not missing, "缺图标：%s" % sorted(missing)
    for p in need:
        assert _png_ok(_brand_uri(p)) > 1500, p
    for key, uri in BRAND.items():
        assert _png_ok(uri) > 1500, key
        assert not re.search(r"https?://", uri), key


def test_app_zhixing_icon_has_no_promo_banner():
    """智行 App 图标只保留官方「智行」字标，不能再带「酒店真低价」促销条。

    旧图底部是橙色营销横幅，缩到 16–22px 读成广告/噪点，渠道身份不成立。
    """
    import base64
    import io
    from PIL import Image
    raw = base64.b64decode(BRAND["app_zhixing"].split(",", 1)[1])
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    assert im.size == (256, 256), im.size
    w, h = im.size
    for y in range(h - 50, h):
        for x in range(w):
            r, g, b = im.getpixel((x, y))
            assert not (r > 170 and g < 160 and b < 130), (
                "智行图标底部仍有促销横幅像素 @%s,%s" % (x, y))
    # 蓝色底：底部应整体偏蓝，不能是白色/黑色横条
    px = [im.getpixel((x, h - 20)) for x in range(0, w, 8)]
    assert sum(1 for r, g, b in px if b > r + 40) >= len(px) * 0.9


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
    # 渠道筛选 chip 的图标必须经 srxPlatKey 解析：本轮之前的写法是
    # `srxPlatIcon(PK[p]||'')`，而 `PK` 是只列 5 家浏览器渠道的写死表，
    # 两个 App 渠道查不到 → chip 没有官方图标。判据守「走单一解析入口」，
    # 不守那张表的字面写法。
    assert "srxPlatIcon(srxPlatKey(p))" in SRC, (
        "渠道筛选 chip 没有走 srxPlatKey（App 渠道会丢官方图标）")
    assert "srxPlatIcon(srxPlatKey(m[0]))" in SRC, (
        "「全线最低」渠道胶囊没有走 srxPlatKey（App 渠道会丢官方图标）")
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
