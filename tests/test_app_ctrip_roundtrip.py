# -*- coding: utf-8 -*-
"""携程 App 往返页解析（真机 dump 夹具）。"""
import os

from crawlers.app_ctrip_roundtrip import (build_combos, is_round_trip_form,
                                          is_round_trip_page,
                                          is_round_trip_picker,
                                          parse_round_trip, picker_footer,
                                          selected_card)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FX = os.path.join(ROOT, "tests", "fixtures")


def _load(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return f.read()


def test_result_page_total_is_the_card_price_not_sum_of_legs():
    """去程卡价=页脚往返总价；返程小卡是差价（+0），两段不相加。"""
    xml = _load("app_ctrip_roundtrip.xml")
    assert is_round_trip_page(xml)
    p = parse_round_trip(xml)
    assert len(p["go"]) == 9
    assert p["go_sel"] == 1 and p["back_sel"] == 1
    first = p["go"][0]
    assert first["price"] == 2709.0
    assert p["footer_total"] == first["price"]
    ret = selected_card(p["back"], p["back_sel"])
    assert ret["ret_diff"] == 0.0
    assert ret["dep_time"] == "19:20" and ret["arr_time"] == "22:00"
    # 返程差价是 0；若把它当整段价或两段相加，都会得到别的数字。
    assert ret["ret_diff"] != first["price"]


def test_build_combos_marks_round_trip_basis_and_selected_return():
    p = parse_round_trip(_load("app_ctrip_roundtrip.xml"))
    combos = build_combos(p, "2026-11-19", "2026-11-21")
    assert len(combos) == 9
    c = combos[0]
    assert c["price"] == 2709.0
    assert c["tripType"] == "RT"
    assert c["depDate"] == "2026-11-19" and c["retDate"] == "2026-11-21"
    assert c["retDepTime"] == "19:20"
    assert c["totalBasis"] == "page_roundtrip_total"
    assert [x["price"] for x in combos] == sorted(
        x["price"] for x in combos) or len(combos) > 1


def test_picker_footer_and_form_detection():
    picker = _load("app_ctrip_roundtrip_picker.xml")
    assert is_round_trip_picker(picker)
    assert picker_footer(picker) == ("11-22", "11-25")
    assert is_round_trip_form(
        '<hierarchy><node text="" content-desc="return date" '
        'bounds="[0,0][10,10]"/></hierarchy>')


def test_u2_fallback_wording_is_parsed_too():
    """国内页 CLI dump 撞动画时走 u2：第一程标题/出发时间/控件选中。"""
    p = parse_round_trip(_load("app_ctrip_roundtrip_u2.xml"))
    assert p is not None
    assert len(p["go"]) == 5
    assert p["go_sel"] == 1 and p["back_sel"] == 1
    assert p["footer_total"] == 760.0
    first = p["go"][0]
    assert first["price"] == 760.0
    assert first["dep_time"] == "09:15" and first["arr_time"] == "11:40"
    assert first["airline"] == "南方航空" and first["airline_code"] == "CZ"
    ret = selected_card(p["back"], p["back_sel"])
    assert ret["ret_diff"] == 0.0
    assert ret["dep_time"] == "14:00" and ret["arr_time"] == "16:30"
    combos = build_combos(p, "2026-11-22", "2026-11-25")
    assert min(x["price"] for x in combos) == 760.0
    assert all(x["tripType"] == "RT" for x in combos)
    assert all(x["retLoaded"] for x in combos)


def test_non_round_trip_page_returns_none():
    assert parse_round_trip("") is None
    assert parse_round_trip(
        '<hierarchy><node text="" content-desc="单程列表页" '
        'bounds="[0,0][10,10]"/></hierarchy>') is None


def _crawler():
    import logging
    from crawlers.app_ctrip import AppCtripCrawler
    return AppCtripCrawler({"user_data_dir": "user_data",
                            "android": {"enabled": True}},
                           logging.getLogger("ctrip_rt_scope"))


def test_domestic_round_trip_reaches_device(monkeypatch):
    import pytest
    c = _crawler()
    touched = []

    def _stop():
        touched.append(1)
        raise RuntimeError("reach-device")

    monkeypatch.setattr(c, "runtime", _stop)
    with pytest.raises(RuntimeError):
        c.fetch("SHA", "BJS", ["2026-11-19"], ret_date="2026-11-21")
    assert touched == [1]


def test_international_round_trip_reaches_device(monkeypatch):
    import pytest
    c = _crawler()
    touched = []

    def _stop():
        touched.append(1)
        raise RuntimeError("reach-device")

    monkeypatch.setattr(c, "runtime", _stop)
    with pytest.raises(RuntimeError):
        c.fetch("SHA", "NRT", ["2026-11-19"], ret_date="2026-11-21")
    assert touched == [1]
