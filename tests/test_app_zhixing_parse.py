# -*- coding: utf-8 -*-
"""智行 dump 解析器：以真实抓取的 fixture 为准。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_zhixing_parse import (detect_state, parse_calendar,
                                        parse_flight_rows)

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "fixtures", "zhixing_list_dump.xml")


def _xml():
    with open(FIX, encoding="utf-8") as f:
        return f.read()


def test_calendar_extracts_real_prices():
    rows = parse_calendar(_xml())
    prices = {r["date"]: r["price"] for r in rows}
    # 真实界面今日与明日最低价（截图与 dump 一致）
    assert prices.get("10-29") == 450
    assert prices.get("10-30") == 430
    assert prices.get("10-31") == 377
    assert len(rows) >= 7


def test_calendar_sorted_by_date():
    rows = parse_calendar(_xml())
    keys = [r["date"] for r in rows]
    assert keys == sorted(keys)


def test_calendar_no_fake_zero_when_missing():
    """没有价格的日子必须是 None，不能补 0。"""
    for r in parse_calendar(_xml()):
        assert r["price"] is None or r["price"] > 0


def test_flight_rows_carry_flight_no_when_page_has_one():
    """国内页有航班号时必须挂上（但**不是**每行都有）。

    首张「中转低价」卡片本来就不给航班号（真机同样如此），国际页更是
    整页没有航班号（r682）。原来断言"每一行都必须有航班号"，把这两类
    正常行都判成缺陷——真正该守的是「页面给了就要取到，没给不许编」。
    """
    rows = parse_flight_rows(_xml())
    assert rows, "fixture 里应有航班行"
    with_no = [r for r in rows if r["flight_no"]]
    assert len(with_no) >= 5, [r["flight_no"] for r in rows]
    for r in with_no:
        assert len(r["flight_no"]) >= 5, r


def test_flight_rows_prices_are_masked_not_zero():
    """未登录时列表价是 ￥ + 4?? 的遮罩，必须标 masked，不得给出 0。"""
    rows = parse_flight_rows(_xml())
    masked = [r for r in rows if r.get("masked")]
    assert masked, "fixture 应存在被遮罩的列表价"
    for r in masked:
        assert r["price"] is None


def test_detect_state_ok_when_rows_present():
    assert detect_state(_xml()) == "ok"


def test_detect_state_empty_for_explicit_no_result():
    xml = ('<hierarchy><node text="抱歉，没有找到符合条件的航班" '
           'bounds="[0,0][100,40]" /></hierarchy>')
    assert detect_state(xml) == "empty"


def test_detect_state_login_only_when_no_rows():
    """有登录横幅但列表照常渲染时，应判 ok（未登录也能拿日历价）。"""
    xml = ('<hierarchy><node text="登录解锁更低价" bounds="[0,0][100,40]" />'
           '<node text="KN5978" bounds="[0,60][100,90]" /></hierarchy>')
    assert detect_state(xml) == "ok"


def test_detect_state_login_when_blank_page():
    xml = ('<hierarchy><node text="立即登录" bounds="[0,0][100,40]" />'
           '<node text="请输入手机号" bounds="[0,60][100,90]" /></hierarchy>')
    assert detect_state(xml) == "login"


def test_detect_state_unknown_on_garbage():
    assert detect_state("") == "unknown"
    assert detect_state("<hierarchy></hierarchy>") == "unknown"


def test_calendar_uses_resource_id_when_present():
    """有 date-item-N-* 时按 id 配对，不看坐标。

    构造一个坐标故意错乱（日期和价格 y 差很远）的页面：按坐标会配错，
    按 id 必须仍然正确——id 是 App 自己的结构约定，比坐标稳。
    """
    xml = ('<hierarchy>'
           '<node text="11-05" resource-id="date-item-0-date-text" '
           'bounds="[0,10][80,30]" />'
           '<node text="\u00a5299" resource-id="date-item-0-price-text" '
           'bounds="[0,900][80,930]" />'
           '<node text="11-06" resource-id="date-item-1-date-text" '
           'bounds="[100,10][180,30]" />'
           '<node text="\u00a5388" resource-id="date-item-1-price-text" '
           'bounds="[100,900][180,930]" />'
           '</hierarchy>')
    rows = parse_calendar(xml)
    assert [(r["date"], r["price"]) for r in rows] == [
        ("11-05", 299), ("11-06", 388)]


def test_calendar_id_path_marks_masked_not_zero():
    xml = ('<hierarchy>'
           '<node text="11-05" resource-id="date-item-0-date-text" '
           'bounds="[0,10][80,30]" />'
           '<node text="3??" resource-id="date-item-0-price-text" '
           'bounds="[0,40][80,60]" />'
           '</hierarchy>')
    rows = parse_calendar(xml)
    assert rows[0]["price"] is None
    assert rows[0]["masked"] is True
