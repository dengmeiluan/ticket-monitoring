# -*- coding: utf-8 -*-
"""r661：真机明细页两处解析错误（用实测 XML 的坐标结构复现）。

一、到达时刻按**水平距离**取最近，会张冠李戴。
    相邻卡片的到达列 x 只差几像素（实测 459 vs 465），下一行那个反而
    "更近"，于是 CZ3832 22:30 配上了下一班的 19:25（真值 01:15）——
    「到达早于起飞」的假行会直接进最优池。正确口径是**起飞/到达同一排**。

二、首个「当日低价」卡片的价格丢失。
    `￥`(x1=796, cy=321) 与 `331`(x1=809, cy=316) 之间在 dump 文档序里
    还夹着「虹桥T2」「01:05」两个节点，只向后看 2 个节点会漏掉这格价，
    整张卡片变成「有航班无价格」。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_zhixing_parse import parse_flight_rows


def _n(text, x1, y1, x2, y2, idx=0):
    return ('<node index="%d" text="%s" resource-id="" class="android.widget.TextView"'
            ' bounds="[%d,%d][%d,%d]" />' % (idx, text, x1, y1, x2, y2))


def _card(idx, dep, arr, code, price, top):
    """一张真实形态的航班卡片：时刻行(top..top+38) / 城市行 / 航班号行。"""
    return "".join([
        # 时刻行：左=起飞、右=到达（同一排，cy 相同）
        _n(dep, 34, top, 245, top + 38),
        _n(arr, 460, top, 544, top + 38),
        # 价格：￥ 与数字拆成两个节点，且数字可能排在若干节点之后
        _n("￥", 796, top + 5, 809, top + 22),
        _n("虹桥T2", 34, top + 29, 245, top + 54),
        _n("白云T3", 487, top + 29, 544, top + 54),
        _n("331", 809, top, 865, top + 19),
        _n("东航", 54, top + 68, 90, top + 91),
        _n(code, 92, top + 68, 160, top + 93),
    ])


def _xml(cards):
    return ('<?xml version="1.0" encoding="UTF-8"?><hierarchy rotation="0">'
            + "".join(cards) + "</hierarchy>")


def test_arrival_pairs_with_departure_on_same_row():
    """到达必须与起飞同排，不得被下一行"更近"的到达抢走。"""
    xml = _xml([_card(0, "22:30", "01:15", "CZ3832", "376", 1294),
                _card(1, "16:50", "19:25", "MU5311", "380", 1444)])
    rows = {r["flight_no"]: r for r in parse_flight_rows(xml)}
    assert rows["CZ3832"]["depart_time"] == "22:30"
    assert rows["CZ3832"]["arrive_time"] == "01:15", \
        "到达取成了别的卡片：%s" % rows["CZ3832"]
    assert rows["MU5311"]["arrive_time"] == "19:25"


def test_arrival_never_earlier_than_departure_by_mistake():
    """近似取值会造出「22:30→19:25」这种跨卡片的假行。"""
    xml = _xml([_card(0, "22:30", "01:15", "CZ3832", "376", 1294),
                _card(1, "16:50", "19:25", "MU5311", "380", 1444)])
    for r in parse_flight_rows(xml):
        dep_h, dep_m = r["depart_time"].split(":")
        arr_h, arr_m = r["arrive_time"].split(":")
        span = (int(arr_h) * 60 + int(arr_m)) - (int(dep_h) * 60 + int(dep_m))
        assert span > 0 or span < -600, \
            "%s 起飞 %s 到达 %s 相差 %.0f 分钟，明显跨卡片" % (
                r["flight_no"], r["depart_time"], r["arrive_time"], span)


def test_price_found_when_digits_are_not_adjacent_in_document_order():
    """￥ 与数字之间夹着别的节点时，价格仍要取到（当日低价卡片实测形态）。"""
    xml = _xml([_card(0, "22:30", "01:05", "MU5319", "331", 297)])
    rows = parse_flight_rows(xml)
    assert len(rows) == 1
    assert rows[0]["price"] == 331, "价格丢了：%r" % rows[0]


def test_price_still_none_when_absent():
    """没有价格节点时不得瞎猜（宁缺勿错）。"""
    xml = ('<?xml version="1.0"?><hierarchy>'
           + _n("22:30", 34, 297, 245, 335)
           + _n("01:05", 460, 297, 544, 335)
           + _n("MU5319", 92, 372, 160, 397)
           + "</hierarchy>")
    rows = parse_flight_rows(xml)
    assert rows and rows[0]["price"] is None
