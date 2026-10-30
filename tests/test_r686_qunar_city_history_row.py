# -*- coding: utf-8 -*-
"""r686：去哪儿选城市点到了「历史选择」里的同名城市，等于没选。

真机现场（2026-10-30，城市选择页）：

    选择目的地 / 搜索国家/城市/景点等
    国内/港澳台 | 国际
    历史选择  清除
    上海                    ← 按文案取第一个就是这个
    热门城市
    上海 北京 成都 …

`_find_text(page, "上海")` 命中的是历史区那条，点它页面不关、城市不变，
函数却返回 True。随后 `_pick_date` 拿到的是城市页（没有日历入口），
整轮记 `pick-date-failed`，账本上看不出真正卡在哪。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_qunar import _pick_city_row


def _n(text, x1, y1, x2, y2):
    return ('<node text="%s" resource-id="" class="android.widget.TextView"'
            ' bounds="[%d,%d][%d,%d]" />' % (text, x1, y1, x2, y2))


def _city_page(city="上海"):
    return ('<hierarchy>'
            + _n("选择目的地", 380, 120, 700, 160)
            + _n("搜索国家/城市/景点等", 87, 193, 294, 225)
            + _n("国内/港澳台", 60, 300, 200, 330)
            + _n("国际", 260, 300, 320, 330)
            + _n("历史选择", 40, 400, 140, 425)
            + _n("清除", 780, 400, 860, 425)
            + _n(city, 40, 440, 120, 480)          # 历史区那条
            + _n("热门城市", 40, 620, 160, 650)
            + _n(city, 60, 680, 140, 720)          # 有效的那条
            + _n("北京", 180, 680, 260, 720)
            + '</hierarchy>')


def test_skips_history_row_and_returns_hot_city():
    row = _pick_city_row(_city_page(), "上海")
    assert row is not None
    assert row["y1"] >= 680, "取到了历史选择区那条：%s" % row


def test_returns_none_when_city_only_in_history():
    xml = ('<hierarchy>'
           + _n("历史选择", 40, 400, 140, 425)
           + _n("东京", 40, 440, 120, 480)
           + _n("热门城市", 40, 620, 160, 650)
           + _n("上海", 60, 680, 140, 720)
           + '</hierarchy>')
    assert _pick_city_row(xml, "东京") is None, \
        "只有历史区有时不该返回可点行（应走搜索框）"


def test_works_without_hot_city_section():
    """没渲染「热门城市」时至少要避开历史区。"""
    xml = ('<hierarchy>'
           + _n("历史选择", 40, 400, 140, 425)
           + _n("上海", 40, 440, 120, 480)
           + '</hierarchy>')
    assert _pick_city_row(xml, "上海") is None


def test_set_city_verifies_leaving_city_page():
    """选中后必须确认离开了城市页；停在原页不许返回 True。"""
    import inspect
    from crawlers.app_qunar import AppQunarCrawler
    src = inspect.getsource(AppQunarCrawler._set_city)
    assert "_CITY_PAGE_MARK" in src, \
        "没有校验是否离开城市页：点了历史区也会返回 True"
