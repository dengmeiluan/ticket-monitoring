# -*- coding: utf-8 -*-
"""同程 App 纯解析：WebView 结果行 / 原生表单 / 日历。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_tongcheng_parse import (_rt_split_flight, is_calendar,
                                         is_form, is_login_wall,
                                         parse_calendar_days, parse_form,
                                         parse_result_rows, parse_round_trip,
                                         parse_round_trip_form)


def _xml(*parts):
    body = "".join(parts)
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            f'<hierarchy rotation="0">{body}</hierarchy>')


def _node(text, x1, y1, x2, y2, desc=""):
    return (f'<node text="{text}" content-desc="{desc}" '
            f'bounds="[{x1},{y1}][{x2},{y2}]" />')


def _row(dep="21:05", arr="23:20", price="¥373¥336",
         flight="东航 MU5185", cabin="1.8折经济舱", dy=0):
    return "".join((
        _node(dep, 21, 516 + dy, 114, 546 + dy),
        _node("浦东T1", 21, 543 + dy, 114, 566 + dy),
        _node(arr, 237, 516 + dy, 330, 546 + dy),
        _node("北京大兴", 237, 543 + dy, 330, 566 + dy),
        _node(price, 775, 515 + dy, 879, 545 + dy),
        _node("可优惠约¥37", 783, 542 + dy, 861, 566 + dy),
        _node(flight, 42, 583 + dy, 300, 603 + dy),
        _node("空客321(窄)", 153, 583 + dy, 300, 603 + dy),
        _node(cabin, 802, 583 + dy, 879, 603 + dy),
    ))


def test_parse_result_rows_reads_flight_and_coupon_price():
    rows = parse_result_rows(_xml(_row()))
    assert len(rows) == 1
    r = rows[0]
    assert r["flight_no"] == "MU5185"
    assert r["dep_time"] == "21:05" and r["arr_time"] == "23:20"
    assert r["dep_airport"] == "浦东T1"
    assert r["arr_airport"] == "北京大兴"
    assert r["airline"] == "东航"
    assert r["cabin"] == "1.8折经济舱"
    assert r["price"] == 336.0
    assert r["list_price"] == 373.0
    assert r["discount_note"] == "可优惠约¥37"


def test_parse_result_rows_dedupes_same_flight_keeps_lowest():
    page = _xml(_row(price="¥373¥336") + _row(price="¥373¥330", dy=300))
    rows = parse_result_rows(page)
    assert len(rows) == 1
    assert rows[0]["price"] == 330.0


def test_parse_result_rows_requires_price_and_flight_no():
    page = _xml(_row(flight="东航"),
                _row(price="", flight="中联航 KN5956", dy=300))
    assert parse_result_rows(page) == []


def test_parse_form_reads_flutter_content_desc():
    page = _xml(
        _node("上海", 39, 443, 410, 489, "上海") +
        _node("北京", 490, 443, 861, 489, "北京") +
        _node("11月16日\n周一", 39, 540, 450, 585, "11月16日\n周一") +
        _node("机票查询", 39, 800, 861, 866, "机票查询"))
    assert is_form(page) is True
    assert parse_form(page) == {"dep": "上海", "arr": "北京",
                                "date": "11月16日"}


def test_parse_calendar_days_reads_content_desc_cells():
    page = _xml(
        _node("价格日历", 200, 240, 400, 280) +
        _node("仅看直飞", 700, 320, 800, 360) +
        _node("2026年11月", 300, 440, 600, 480) +
        _node("出发\n16\n¥373", 170, 690, 246, 738, "出发\n16\n¥373") +
        _node("17\n¥374", 291, 690, 367, 738, "17\n¥374") +
        _node("2026年12月", 300, 956, 600, 996))
    assert is_calendar(page) is True
    assert parse_calendar_days(page, 2026, 11) == {16: 373.0, 17: 374.0}


def test_parse_calendar_days_separates_months_and_day_labels():
    """两月同日号不能互相覆盖；今天/明天按 today 映射到日号。"""
    from datetime import date
    page = _xml(
        _node("价格日历", 200, 240, 400, 280) +
        _node("仅看直飞", 700, 320, 800, 360) +
        _node("2026年11月", 300, 440, 600, 480) +
        _node("今天\n¥450", 170, 540, 246, 588) +
        _node("5\n¥360", 570, 540, 646, 588) +
        _node("2026年12月", 300, 956, 600, 996) +
        _node("5\n¥560", 570, 1056, 646, 1104) +
        _node("6\n¥570", 691, 1056, 767, 1104))
    today = date(2026, 11, 2)
    assert parse_calendar_days(page, 2026, 11, today=today) == {
        2: 450.0, 5: 360.0}
    assert parse_calendar_days(page, 2026, 12, today=today) == {
        5: 560.0, 6: 570.0}
    assert parse_calendar_days(page, 2027, 1, today=today) == {}


def test_login_wall_detected():
    page = _xml(_node("手机号一键登录", 0, 700, 900, 800))
    assert is_login_wall(page) is True


def test_round_trip_form_has_two_dates_and_418_city_row():
    """往返档城市行在 y=418（单程 466），必须仍能读出出发/到达。"""
    page = _xml(
        _node("上海", 150, 400, 300, 436, "上海") +
        _node("东京", 600, 400, 750, 436, "东京") +
        _node("11月17日\n周二", 180, 490, 310, 538) +
        _node("11月22日\n周日", 580, 490, 730, 538) +
        _node("机票查询", 39, 680, 861, 746, "机票查询"))
    form = parse_round_trip_form(page)
    assert form == {"dep": "上海", "arr": "东京",
                    "dep_date": "11月17日", "ret_date": "11月22日",
                    "round_trip": True}
    assert parse_form(page)["date"] == "11月17日"


def test_round_trip_result_reads_page_total_and_return_surcharges():
    """真实夹具：去程行价=含税总价，返程 `+¥N` 是加价，总价取页脚。"""
    path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "tests", "fixtures",
        "tongcheng_roundtrip.xml")
    with open(path, encoding="utf-8") as f:
        parsed = parse_round_trip(f.read())
    assert parsed["route"] == {"dep": "上海", "arr": "东京"}
    assert parsed["dep_date"] == "11-16"
    assert parsed["ret_date"] == "11-19"
    assert parsed["total"] == 2209.0
    by = {r["flight_no"]: r for r in parsed["outbounds"]}
    assert len(parsed["outbounds"]) == 7
    assert by["9C8515"]["price"] == 2209.0
    assert by["9C8515"]["arr_date"] == "11月17日"
    assert by["9C8515"]["airline"] == "春秋航空"
    assert by["GK036"]["duration"] == "3时"
    assert by["MM876"]["duration"] == "2时30分"
    assert by["IJ006"]["duration"] == "3时5分"
    rets = {(r["flight_no"], r["surcharge"]) for r in parsed["returns"]}
    assert len(rets) == 8, "重复行未去重：%s" % rets
    assert ("9C6218", 0.0) in rets
    assert ("IJ005", 72.0) in rets
    assert parsed["selected_return"]["flight_no"] == "9C6218"
    assert parsed["selected_return"]["surcharge"] == 0.0
    assert "往返价格已降" in parsed["note"]
    # 页脚总价必须等于最低去程行价（同一条返程组合），不能是 3034。
    assert min(r["price"] for r in parsed["outbounds"]) == parsed["total"]


def test_round_trip_live_page_with_range_footer_and_compact_rows():
    """现网新版：页脚「已选 02:20- 06:20 …」不写「出发」，返程栏有紧凑时刻副本。

    紧凑副本宽度只有 ~54px；旧实现把它当返程行，会产出 05:00→05:00 的假行；
    同时页脚锁定条件要求「出发」，整页会解析成 None。两条都要钉住。
    """
    path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "tests", "fixtures",
        "tongcheng_roundtrip_live.xml")
    with open(path, encoding="utf-8") as f:
        parsed = parse_round_trip(f.read())
    assert parsed["total"] == 2420.0
    assert parsed["dep_date"] == "11-17"
    assert len(parsed["outbounds"]) == 9
    assert len(parsed["returns"]) == 8
    assert parsed["selected_return"]["flight_no"] == "MM877"
    assert parsed["selected_return"]["surcharge"] == 0.0
    assert not [r for r in parsed["returns"]
                if r["dep_time"] == r["arr_time"]], "紧凑时刻副本被当成返程行"
    by = {r["flight_no"]: r for r in parsed["outbounds"]}
    assert by["GK036"]["price"] == 2420.0
    assert min(r["price"] for r in parsed["outbounds"]) == parsed["total"]


def test_round_trip_split_flight_strips_duration_glued_to_number():
    assert _rt_split_flight("春秋航空9C85152时55分") == (
        "9C8515", "春秋航空", "2时55分")
    assert _rt_split_flight("捷星日本航空GK0363时") == (
        "GK036", "捷星日本航空", "3时")
    assert _rt_split_flight("春秋航空日本IJ0063时5分") == (
        "IJ006", "春秋航空日本", "3时5分")
    assert _rt_split_flight("春秋航空9C6218") == ("9C6218", "春秋航空", "")


def test_round_trip_result_requires_footer_total():
    """没有页脚总价就不解析：宁可报空，不拿去程行价冒充整单总价。"""
    page = _xml(
        _node("去程", 19, 192, 76, 226) +
        _node("返程", 642, 192, 699, 226) +
        _node("含税总价", 444, 324, 549, 376) +
        _node("已选 21:10 出发 春秋航空", 19, 1470, 216, 1497))
    assert parse_round_trip(page) is None
