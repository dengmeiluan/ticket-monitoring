# -*- coding: utf-8 -*-
"""去哪儿 App 两程多程页解析门禁（真实页面夹具，2026-11-03）。

口径（真机差值实验）：左列第一程价 = **默认第二程 +¥0 组合的整单总价**
（¥5069，选 +¥150 也不变）；页脚 CountUpPrice +「两程含税总价」= 当前
选择组合总价（¥5219）；第二程 `+¥N` 是加价，不是票价。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_qunar_multi import is_multi_city_page, parse_multi_city

FIXTURE = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tests", "fixtures", "qunar_multicity.xml")


def _xml():
    with open(FIXTURE, encoding="utf-8") as f:
        return f.read()


def _parsed():
    return parse_multi_city(_xml())


def test_parses_two_leg_page_with_page_total():
    assert is_multi_city_page(_xml()) is True
    r = _parsed()
    assert r and r["legs"] == 2
    assert r["total"] == 5219.0
    assert r["total_label"] == "两程含税总价"
    assert r["total_basis"] == "page_multicity_total"
    assert len(r["first"]) == 7 and len(r["second"]) == 8


def test_first_leg_price_is_base_total_not_selected_combo_total():
    """左列 ¥5069 是默认第二程组合价；选了 +¥150 后只有页脚变 ¥5219。"""
    r = _parsed()
    by = {x["flight_no"]: x for x in r["first"]}
    assert by["MU3686"]["price"] == 5069.0
    assert by["MU3748"]["price"] == 5069.0
    assert by["CZ8757"]["price"] == 6511.0
    assert by["CA8573"]["price"] == 11022.0
    assert all(x["price_basis"] == "page_multicity_base_total"
               for x in r["first"])
    # 选中组合的总价在页脚，不在左列；左列价不因第二程加价而变化
    assert r["selected_second"]["surcharge"] == 150.0
    assert by["MU3686"]["price"] != r["total"]


def test_second_leg_surcharge_is_not_a_fare():
    r = _parsed()
    assert all("price" not in x for x in r["second"]), (
        "第二程 +¥N 是加价，不能落成 price")
    surs = {x["surcharge"] for x in r["second"]}
    assert {0.0, 150.0, 270.0, 1820.0} <= surs, surs


def test_selected_second_matches_footer_and_rendered_airports():
    r = _parsed()
    sel = r["selected_second"]
    assert sel["flight_no"] == "HO1274"
    assert sel["dep_time"] == "08:00" and sel["arr_time"] == "20:50"
    assert sel["dep_airport"] == "美兰T1"
    assert sel["arr_airport"] == "羽田T3"
    assert sel["duration"] == "11时50分"
    assert sel["transfer"] == "转 上海"
    assert sel["surcharge"] == 150.0
    assert "已选 08:00-20:50" in r["selected_note"]
    assert "+¥150" in r["selected_note"]


def test_non_two_leg_or_missing_total_returns_none():
    xml = _xml()
    assert parse_multi_city(xml.replace("两程含税总价", "含税总价")) is None
    assert parse_multi_city(xml.replace("两程含税总价", "三程含税总价")) is None
    assert parse_multi_city(xml.replace('text="5219"', 'text=""')) is None


def test_third_leg_page_is_not_claimed_supported():
    """三程及以上形态未验：is_multi_city_page 必须为 False，不猜。"""
    xml = _xml().replace("两程含税总价", "三程含税总价")
    assert is_multi_city_page(xml) is False
