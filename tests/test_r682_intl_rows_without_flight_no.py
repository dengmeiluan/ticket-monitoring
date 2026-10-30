# -*- coding: utf-8 -*-
"""r682：智行国际列表页不给航班号，明细整片作废。

真机实测（2026-10-30，上海浦东→东京成田/羽田，国际档）：
  * 卡片里只有 起飞时刻 / 全程时长 / 到达时刻 / 机场 / 价格 / 航司名，
    **没有任何 XX#### 航班号**（国内档有：CZ8890 之类）。
  * 原解析器以航班号为锚，一页 6 张卡片判出 0 行；而 `detect_state`
    同样以航班号为「有数据」判据，整页落到 unknown。
  * 下游 `_real_offer` 只要求 depTime+arrTime（飞猪国际中转卡片同样
    只有航司名），所以正确口径是**时刻行锚定**，航班号可有可无。

坐标取自真机 dump（1080 宽的设备按 900 缩放的布局）：
  起飞 21:10 [34,471][248,509]   到达 01:05 [499,471][583,509]
  ￥ [790,484][803,507]          988 [803,471][865,509]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_zhixing_parse import detect_state, parse_flight_rows


def _n(text, x1, y1, x2, y2):
    return ('<node text="%s" resource-id="" class="android.widget.TextView"'
            ' bounds="[%d,%d][%d,%d]" />' % (text, x1, y1, x2, y2))


def _intl_card(top, dep, arr, price, airline, dur="全程2h55m"):
    """国际卡片：无航班号。"""
    return "".join([
        _n(dep, 34, top, 248, top + 38),
        _n(dur, 270, top, 345, top + 21),
        _n(arr, 499, top, 583, top + 38),
        _n(price, 803, top, 865, top + 38),
        _n("￥", 790, top + 13, 803, top + 36),
        _n("浦东T2", 34, top + 36, 160, top + 61),
        _n("羽田T3", 526, top + 36, 583, top + 61),
        _n("补贴后价", 793, top + 38, 865, top + 59),
        _n(airline, 54, top + 76, 126, top + 101),
        _n("已优惠¥5", 794, top + 77, 860, top + 99),
    ])


def _xml(cards, header="<hierarchy rotation=\"0\">"):
    return header + "".join(cards) + "</hierarchy>"


def test_intl_cards_parsed_without_flight_no():
    xml = _xml([_intl_card(471, "21:10", "01:05", "988", "春秋航空"),
                _intl_card(642, "08:55", "13:00", "1068", "春秋航空日本")])
    rows = parse_flight_rows(xml)
    assert len(rows) == 2, rows
    assert [r["depart_time"] for r in rows] == ["21:10", "08:55"]
    assert [r["arrive_time"] for r in rows] == ["01:05", "13:00"]
    assert [r["price"] for r in rows] == [988, 1068]
    assert all(not r["flight_no"] for r in rows), "不得凭空编航班号"


def test_intl_rows_carry_airline_name():
    xml = _xml([_intl_card(471, "21:10", "01:05", "988", "日本乐桃航空")])
    rows = parse_flight_rows(xml)
    assert rows and rows[0].get("airline") == "日本乐桃航空", rows


def test_intl_page_detected_as_ok_so_crawler_stops_waiting():
    """detect_state 若仍判 unknown，明细路径会一直轮询到超时。"""
    xml = _xml([_intl_card(471, "21:10", "01:05", "988", "春秋航空"),
                _intl_card(642, "08:55", "13:00", "1068", "吉祥航空")])
    assert detect_state(xml) == "ok"


def test_home_page_date_strip_is_not_mistaken_for_cards():
    """首页日期条只有「¥910」这类整串价，没有时刻对——不得判成 ok。

    误判会把「首页」当成「列表页已出数据」，直接拿首页解析出空行。
    """
    xml = _xml([_n("上海", 42, 451, 106, 494),
                _n("东京", 794, 451, 858, 494),
                _n("11-18", 41, 118, 120, 140),
                _n("¥910", 41, 142, 83, 164),
                _n("11-19", 154, 118, 233, 140),
                _n("¥996", 154, 142, 200, 164)])
    assert detect_state(xml) != "ok"
    assert parse_flight_rows(xml) == []


def test_promo_times_never_become_rows():
    """「全程2h55m」「已优惠¥5」这类数字片段不得被拼成航班行。"""
    xml = _xml([_n("新客补贴", 186, 256, 270, 285),
                _n("¥", 137, 258, 147, 283),
                _n("5", 147, 253, 160, 285),
                _n("机酒订立返", 625, 256, 730, 285),
                _n("¥", 563, 258, 573, 283),
                _n("50", 573, 253, 599, 285)])
    assert parse_flight_rows(xml) == []


def test_transfer_card_carries_stop_city():
    """中转卡片必须标出经停城市。

    真机 11-06：首卡「10:25→10:05 / 全程23h40m / 青岛 20h35m / ￥450」，
    没有航班号。改按时刻锚定后它曾是**第一条被放行的行**——如果不标
    transCity，下游会把它当直飞塞进直飞最优池，还把行头价压到 450。
    """
    xml = _xml([_n("10:25", 34, 297, 245, 335),
                _n("全程23h40m", 248, 297, 345, 318),
                _n("10:05", 460, 297, 544, 335),
                _n("450", 803, 297, 865, 335),
                _n("￥", 790, 310, 803, 333),
                _n("首都T3", 34, 333, 160, 358),
                _n("浦东T2", 487, 333, 544, 358),
                _n("青岛 20h35m", 246, 343, 460, 364),
                _n("山航", 54, 372, 126, 397)])
    rows = parse_flight_rows(xml)
    assert rows and rows[0]["trans_city"] == "青岛", rows


def test_direct_card_has_no_stop_city():
    xml = _xml([_intl_card(471, "21:10", "01:05", "988", "春秋航空")])
    rows = parse_flight_rows(xml)
    assert rows and rows[0]["trans_city"] == "", rows


def test_airline_never_takes_toolbar_or_section_labels():
    """排序栏「比价」、表头「时间」、区头「国内中转」都不是航司名。"""
    xml = _xml([_n("比价", 500, 201, 560, 224),
                _n("时间", 185, 372, 239, 397),
                _intl_card(471, "21:10", "01:05", "988", "春秋航空")])
    rows = parse_flight_rows(xml)
    assert rows and rows[0]["airline"] == "春秋航空", rows
