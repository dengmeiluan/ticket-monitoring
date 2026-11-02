# -*- coding: utf-8 -*-
"""r725 智行「营销活动全屏页」要当可关闭广告，别让明细通路等到超时。

真机（2026-10-31，智行 App，SHA→HAK 2027-01-29）：点「机票查询」后，
前台变成一个**独立的 React Native 全屏 Activity**
（`ctrip.android.reactnative.preloadv2.CRNBaseActivityV2`），内容是
「全网招募：智行机票体验官 / 免费得以下权益机会 / 权益一…四 / 一键报名」。

后果链：
1. dump 只拿得到活动页自己（14 行文案、0 航班、0 价格）；
2. 文案数 14 > 阈值 12，旧逻辑判不成广告；也不含验证码/登录标记；
   `detect_block` 返回空 → 不算拦截；
3. `_one_date_detail` 一直等 `detect_state(xml) == 'ok'`，等到 30s 超时，
   最后记「明细页没解析出带价航班」，回退成日历价；
4. 而截图上**列表页就压在这层下面**——点右上角的 `\\ue706` 字形关闭钮
   之后立刻露出 8 行带价航班（CA8573 ¥1734 等）。

两处判据修正：
- 营销词 + 无数据即算广告，不再受「文案 ≤12」限制（全屏活动页文案更多）；
- 关闭钮认**图标字形**：私用区字符或 ✕ 类符号，且落在页面右侧 2/3。
  只按横向判右侧、不限纵向——该 ✕ 在 y=1092，而「一键报名」在 y=1527，
  按页高一半卡会把它排除掉（实测限定上半部时仍关不掉）。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers.app_blockers import (  # noqa: E402
    detect_block, has_payload, _close_button, _texts, BLOCK_AD,
)

# 取自真机 dump 的文案与坐标（900×1600 屏）
ACTIVITY_TEXTS = [
    ("全网招募：智行机票体验官", 455, 1103),
    ("免费得以下权益机会", 424, 1201),
    ("活动规则", 824, 1201),
    ("惊喜航班", 114, 1269),
    ("权益一", 89, 1306),
    ("飞行体验价", 556, 1269),
    ("权益二", 518, 1306),
    ("立减权益", 114, 1370),
    ("权益三", 89, 1407),
    ("特价机票", 543, 1370),
    ("权益四", 518, 1407),
    ("一键报名", 450, 1527),
    ("一秒审核", 849, 1496),
    ("\ue706", 865, 1092),      # 右上角 ✕ 图标
]


def _xml_from(texts, extra=""):
    # 上面的坐标是真机 dump 里的**节点中心**，这里按 40×24 的盒子反推 bounds，
    # 免得 _center() 算出来偏 +20/+12。
    out = ["<hierarchy>"]
    for t, x, y in texts:
        out.append(
            '<node text="%s" resource-id="" class="android.widget.TextView" '
            'clickable="false" bounds="[%d,%d][%d,%d]" />'
            % (t.replace('"', "&quot;"), x - 20, y - 12, x + 20, y + 12))
    out.append(extra)
    out.append("</hierarchy>")
    return "".join(out)


ACTIVITY_XML = _xml_from(ACTIVITY_TEXTS)

FLIGHT_LIST_TEXTS = [
    ("上海", 40, 200), ("01-29 周五", 300, 260),
    ("￥1734", 700, 300), ("CA8573", 120, 340),
    ("￥2085", 700, 500), ("FM9253", 120, 540),
]
FLIGHT_LIST_XML = _xml_from(FLIGHT_LIST_TEXTS)


def test_activity_page_has_no_payload():
    """前提：活动页里既没有航班号也没有价格。否则它本来就该按数据页处理。"""
    assert has_payload(ACTIVITY_XML) is False


def test_activity_page_detected_as_closable_ad():
    b = detect_block(ACTIVITY_XML)
    assert b.kind == BLOCK_AD, (b.kind, b.detail)
    assert b.close_xy is not None, "没找到关闭按钮，活动层会一直挡着列表"
    # 关闭钮必须落在右上那个字形上
    assert abs(b.close_xy[0] - 865) <= 6, b.close_xy
    assert abs(b.close_xy[1] - 1092) <= 6, b.close_xy


def test_glyph_close_button_not_confused_by_body_glyphs():
    """正文里的装饰字形不能被当成关闭钮（必须在右侧 2/3）。"""
    texts = [("机票", 100, 300), ("\ue600", 120, 900), ("¥1734", 700, 950)]
    assert _close_button(texts) is None


def test_data_page_is_not_treated_as_ad():
    """负控：有航班/价格的列表页不能被判成广告 —— 那会把好数据丢掉。"""
    b = detect_block(FLIGHT_LIST_XML)
    assert b.kind != BLOCK_AD, (b.kind, b.detail)


def test_text_close_button_still_wins():
    """文字型「关闭」按钮继续优先（别被图标分支抢走）。"""
    texts = [("跳过", 500, 200), ("\ue706", 865, 1092)]
    assert _close_button(texts) == (500, 200)
