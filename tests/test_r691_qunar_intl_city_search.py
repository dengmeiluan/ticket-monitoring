# -*- coding: utf-8 -*-
"""r691：去哪儿国际城市只能用搜索框——点文案不聚焦、输入还残留上次文字。

真机现场（2026-10-30，城市选择页切到「国际」）：

    选择出发地 / 搜索国家/城市/景点等 / 国内·港澳台 | 国际
    历史/热门  东南亚 日韩 欧洲 …
    热门城市   曼谷 首尔 吉隆坡 东京 …

  * 国际档的热门城市**没有上海/北京**，国内城市只能搜；
  * 搜索框的占位文案是 TextView，点它不一定聚焦（要按 EditText 取）；
  * 输入框里残留上次的「上海」，再输一次得到「上海上海」，搜不出城市行；
  * 搜到的是城市聚合行「上海（不限机场）… SHA」，下面是机场子项。

结果是 `set-city-dep`：整轮 0 行，账本只写一句 timeout。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_qunar import (_find_edit_box, _pick_city_row,
                                _search_result_row)


def _n(text, x1, y1, x2, y2, cls="android.widget.TextView"):
    return ('<node text="%s" resource-id="" class="%s"'
            ' bounds="[%d,%d][%d,%d]" />' % (text, cls, x1, y1, x2, y2))


INTL_PAGE = ('<hierarchy>'
             + _n("选择出发地", 380, 120, 700, 160)
             + _n("搜索国家/城市/景点等", 87, 193, 294, 225)
             + _n("国内/港澳台", 60, 300, 200, 330)
             + _n("国际", 260, 300, 320, 330)
             + _n("历史/热门", 40, 360, 140, 385)
             + _n("热门城市", 40, 620, 160, 650)
             + _n("曼谷", 60, 680, 140, 720)
             + _n("首尔", 180, 680, 260, 720)
             + _n("东京", 300, 680, 380, 720)
             + '</hierarchy>')

SEARCHED = ('<hierarchy>'
            + _n("上海上海", 60, 100, 400, 140, "android.widget.EditText")
            + _n("城市", 40, 200, 90, 220)
            + _n("上海（不限机场）   上海   中国   SHA", 60, 230, 700, 260)
            + _n("   浦东机场   PVG", 60, 280, 700, 310)
            + _n("   虹桥机场   SHA", 60, 330, 700, 360)
            + '</hierarchy>')


def test_international_hot_cities_lack_domestic_ones():
    """国际档热门城市里没有上海——所以必须走搜索框。"""
    assert _pick_city_row(INTL_PAGE, "上海") is None
    assert _pick_city_row(INTL_PAGE, "东京") is not None


def test_edit_box_found_by_class_not_by_placeholder():
    xml = ('<hierarchy>'
           + _n("搜索国家/城市/景点等", 87, 193, 294, 225)
           + _n("残留文字", 60, 100, 400, 140, "android.widget.EditText")
           + '</hierarchy>')
    box = _find_edit_box(xml)
    assert box is not None
    assert box["y1"] == 100, "取到了占位文案而不是输入框：%s" % box


def test_search_result_prefers_city_row_over_airport():
    row = _search_result_row(SEARCHED, "上海")
    assert row is not None
    assert "不限机场" in row["text"], row
    assert row["y1"] == 230, "取到了机场子项：%s" % row


def test_clears_residual_text_before_typing():
    """输入前必须清空，否则出现「上海上海」。"""
    import inspect
    from crawlers.app_qunar import AppQunarCrawler
    src = inspect.getsource(AppQunarCrawler._set_city)
    assert "KEYCODE_DEL" in src, "没有清空残留文字，会搜出「上海上海」"


def test_intl_does_not_switch_city_tab():
    """国际航线不该点「国内」tab：那会把列表换成国内热门，反而选不到。"""
    import inspect
    from crawlers.app_qunar import AppQunarCrawler
    src = inspect.getsource(AppQunarCrawler._set_city)
    assert "if not intl:" in src, "国际档也切档了，国际城市会选不到"


def test_pick_date_waits_for_dialog_activity():
    """日历是独立 Activity，只等 3s 会读到「还没起来」的中间态。

    真机：国际档第一次选日 100% 失败（dump 空/仍是首页），第二次才成功
    ——账本表现为「今天这轮没数据」。
    """
    import inspect
    from crawlers.app_qunar import AppQunarCrawler
    src = inspect.getsource(AppQunarCrawler._pick_date)
    assert "deadline_open" in src, "打开日历后没有轮询等待弹层出现"
