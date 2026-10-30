# -*- coding: utf-8 -*-
"""r694：去哪儿 App「低价机票」= low_fare 发现源（每天一条最低价）。

真机形态（2026-10-30，北京→上海）：

    y=112  10.31   11.01   11.02   11.03   11.04   11.05   ← 日期带（横排 6 列）
    y=133  今天    明天    后天    周二    周三    周四
    y=156  ¥410    ¥358    ¥420    ¥410    ¥450    ¥523    ← 每天最低价
    y=322  「直飞低价」区头 + 当天航班卡片（07:30→09:45 ¥358 …）

这条维度在 PC/H5 那边指的是**发现源**（`core/specials.py` 的榜单），
不是明细——每天一条最低价，不带航班号。所以解析必须只取顶部日期带，
不能把下方卡片的票价混进来。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_qunar_lowfare import is_low_fare_page, parse_low_fare_strip


def _n(text, x1, y1, x2, y2):
    return ('<node text="%s" resource-id="" class="android.widget.TextView"'
            ' bounds="[%d,%d][%d,%d]" />' % (text, x1, y1, x2, y2))


def _page():
    """真机结构缩影：日期带 + 一天航班卡片（后者不得被当低价）。"""
    return ('<hierarchy>'
            + _n("北京", 734, 55, 782, 84)
            + _n("上海", 824, 55, 872, 84)
            + _n("10.31", 7, 112, 60, 133)
            + _n("11.01", 273, 112, 326, 133)
            + _n("11.02", 539, 112, 592, 133)
            + _n("11.03", 805, 112, 858, 133)
            + _n("今天", 22, 133, 62, 154)
            + _n("明天", 287, 133, 327, 154)
            + _n("后天", 554, 133, 594, 154)
            + _n("周二", 820, 133, 860, 154)
            + _n("¥410", 7, 156, 67, 182)
            + _n("¥358", 273, 156, 333, 182)
            + _n("¥420", 539, 156, 599, 182)
            + _n("¥410", 805, 156, 865, 182)
            # 下方是当天的航班明细卡片，票价 358 与上面 11.01 相同
            + _n("直飞低价", 24, 322, 120, 343)
            + _n("07:30", 36, 363, 200, 399)
            + _n("09:45", 270, 363, 420, 399)
            + _n("¥", 1490, 359, 1501, 385)
            + _n("358", 1502, 356, 1560, 400)
            + _n("东航MU5186", 57, 437, 200, 462)
            + '</hierarchy>')


def test_strip_parses_daily_min_price():
    rows = parse_low_fare_strip(_page(), "2026")
    got = [(r["date"], r["price"]) for r in rows]
    assert got == [("2026-10-31", 410), ("2026-11-01", 358),
                   ("2026-11-02", 420), ("2026-11-03", 410)], got


def test_strip_ignores_flight_card_prices():
    """下方卡片的 `¥358` 不得被当成 11.01 之外的另一天。"""
    rows = parse_low_fare_strip(_page(), "2026")
    assert len(rows) == 4, rows
    assert all(r["price"] in (410, 358, 420) for r in rows)


def test_strip_carries_weekday():
    rows = {r["date"]: r for r in parse_low_fare_strip(_page(), "2026")}
    assert rows["2026-10-31"]["weekday"] == "今天"
    assert rows["2026-11-01"]["weekday"] == "明天"


def test_missing_price_is_none_not_zero():
    xml = ('<hierarchy>'
           + _n("10.31", 7, 112, 60, 133)
           + _n("11.01", 273, 112, 326, 133)
           + _n("11.02", 539, 112, 592, 133)
           + _n("今天", 22, 133, 62, 154)
           + _n("¥410", 273, 156, 333, 182))
    rows = {r["mm_dd"]: r for r in parse_low_fare_strip(xml, "2026")}
    assert rows["10-31"]["price"] is None
    assert rows["11-02"]["price"] is None
    assert rows["11-01"]["price"] == 410


def test_home_strip_with_chajia_is_not_low_fare_page():
    """首页 7 天条每天下面是「查价」，不是价格——不能当结果页。"""
    xml = ('<hierarchy>'
           + _n("10.31", 7, 112, 60, 133)
           + _n("11.01", 273, 112, 326, 133)
           + _n("11.02", 539, 112, 592, 133)
           + _n("查价", 7, 156, 67, 182)
           + _n("查价", 273, 156, 333, 182)
           + _n("查价", 539, 156, 599, 182)
           + '</hierarchy>')
    assert not is_low_fare_page(xml)


def test_low_fare_prunes_to_window():
    """日期带会渲染跨年远期日；14 天窗口之外的必须裁掉。"""
    import datetime as dt
    from crawlers.app_qunar import AppQunarCrawler
    today = dt.date.today()
    rows = [{"date": today.isoformat(), "price": 1},
            {"date": (today + dt.timedelta(days=13)).isoformat(), "price": 2},
            {"date": (today + dt.timedelta(days=14)).isoformat(), "price": 3},
            {"date": (today - dt.timedelta(days=1)).isoformat(), "price": 4}]
    out = AppQunarCrawler._pick_window(rows, 14)
    assert [r["price"] for r in out] == [1, 2], out
