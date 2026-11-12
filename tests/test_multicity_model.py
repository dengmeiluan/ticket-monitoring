# -*- coding: utf-8 -*-
"""多程数据契约与 itinerary_daily 存储门禁（未接采集/UI）。

口径：只接受渠道自报整单总价；legs 不得携带价格字段，从形状上禁止
「两段单程相加冒充多程总价」。矩阵 multi_city 在接通前仍为 ""。
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.multicity import (MultiCityError, build_mc_extra, is_mc_extra,
                            normalize_segments, parse_mc_extra, segments_key)
from core.storage import PriceStorage


SEGS = [{"from": "sha", "to": "nrt", "date": "2026-11-20"},
        {"from": "nrt", "to": "osa", "date": "2026-11-23"}]
LEGS = [{"flight_no": "9C8515", "from": "SHA", "to": "NRT",
         "date": "2026-11-20", "dep": "08:00", "arr": "12:00"},
        {"flight_no": "MM304", "from": "NRT", "to": "OSA",
         "date": "2026-11-23", "dep": "13:00", "arr": "14:30"}]


def test_normalize_segments_accepts_two_to_four():
    got = normalize_segments(SEGS)
    assert got[0]["from"] == "SHA" and got[0]["to"] == "NRT"
    assert len(normalize_segments(SEGS + [
        {"from": "osa", "to": "tyo", "date": "2026-11-25"}])) == 3
    assert len(normalize_segments(SEGS + [
        {"from": "osa", "to": "tyo", "date": "2026-11-25"},
        {"from": "tyo", "to": "sha", "date": "2026-11-28"}])) == 4


@pytest.mark.parametrize("bad", [
    SEGS[:1],
    SEGS + [{"from": "OSA", "to": "TYO", "date": "2026-11-25"},
            {"from": "TYO", "to": "SHA", "date": "2026-11-26"},
            {"from": "SHA", "to": "PEK", "date": "2026-11-27"}],
])
def test_normalize_segments_rejects_wrong_leg_count(bad):
    with pytest.raises(MultiCityError):
        normalize_segments(bad)


@pytest.mark.parametrize("bad", [
    [{"from": "SH", "to": "NRT", "date": "2026-11-20"}, SEGS[1]],
    [{"from": "SHA", "to": "NRT", "date": "2026/11/20"}, SEGS[1]],
    [{"from": "SHA", "to": "NRT"}, SEGS[1]],
])
def test_normalize_segments_rejects_bad_fields(bad):
    with pytest.raises(MultiCityError):
        normalize_segments(bad)


def test_segments_key_is_stable_and_order_sensitive():
    assert segments_key(SEGS) == "SHA-NRT@2026-11-20|NRT-OSA@2026-11-23"
    assert segments_key(list(reversed(SEGS))).startswith("NRT-OSA@")


def test_mc_extra_refuses_leg_prices_and_round_trips():
    extra = build_mc_extra(LEGS)
    assert extra["tripType"] == "MC"
    assert extra["totalBasis"] == "page_multicity_total"
    assert len(extra["legs"]) == 2
    assert is_mc_extra(extra)
    assert parse_mc_extra('{"tripType":"MC","legs":[{"flight_no":"X"}]}')
    assert parse_mc_extra({"tripType": "RT", "legs": []}) is None
    with pytest.raises(MultiCityError):
        build_mc_extra([dict(LEGS[0], price=500), LEGS[1]])
    with pytest.raises(MultiCityError):
        build_mc_extra([{"from": "SHA"}])


def test_itinerary_daily_upsert_and_read(tmp_path):
    db = PriceStorage(str(tmp_path / "prices.db"))
    key = db.save_itinerary("app_qunar", "r1", SEGS, 5069.0, LEGS)
    assert key == segments_key(SEGS)
    db.save_itinerary("app_qunar", "r1", SEGS, 5219.0, LEGS)
    rows = db.itineraries(route_id="r1")
    assert len(rows) == 1, "同一 (platform, route, key, date) 必须是 upsert"
    assert rows[0]["total_price"] == 5219.0
    assert rows[0]["extra"]["tripType"] == "MC"
    assert rows[0]["extra"]["legs"][1]["flight_no"] == "MM304"


def test_itinerary_daily_keeps_source_url_and_drops_bad_prov(tmp_path):
    db = PriceStorage(str(tmp_path / "prices.db"))
    url = "https://flights.ctrip.com/online/list/multi-sha-tyo-tyo-osa"
    db.save_itinerary("ctrip", "r1", SEGS, 1298.0, LEGS,
                      prov=json.dumps({"path": "多程", "url": url,
                                       "totalBasis": "page_multicity_total"},
                                      ensure_ascii=False))
    extra = db.itineraries(route_id="r1")[0]["extra"]
    assert extra["prov"]["url"] == url
    assert extra["prov"]["path"] == "多程"
    # 坏 JSON/非对象不落来源，也不影响整单总价
    db.save_itinerary("ctrip", "r1", SEGS, 1299.0, LEGS, prov="{oops")
    assert "prov" not in db.itineraries(route_id="r1")[0]["extra"]


def test_itinerary_daily_refuses_non_page_total(tmp_path):
    db = PriceStorage(str(tmp_path / "prices.db"))
    with pytest.raises(ValueError):
        db.save_itinerary("app_qunar", "r1", SEGS, 0, LEGS)
    with pytest.raises(ValueError):
        db.save_itinerary("app_qunar", "r1", SEGS, -1, LEGS)
    with pytest.raises(ValueError):
        db.save_itinerary("app_qunar", "r1", SEGS, 500, [
            dict(LEGS[0], price=250), LEGS[1]])
    with pytest.raises(ValueError):
        db.save_itinerary("app_qunar", "r1", SEGS, 500, LEGS,
                          depart_date="2026-11-23")
    # legs 必须与 segments 逐段对得上，不能把别的行程拼进同一总价
    with pytest.raises(ValueError):
        db.save_itinerary("app_qunar", "r1", SEGS, 500, LEGS[:1])
    with pytest.raises(ValueError):
        db.save_itinerary("app_qunar", "r1", SEGS, 500, [
            dict(LEGS[0], to="OSA"), LEGS[1]])
    with pytest.raises(ValueError):
        db.save_itinerary("app_qunar", "r1", SEGS, 500, [
            LEGS[0], dict(LEGS[1], date="2026-11-25")])


def test_route_segments_never_enter_single_od_schedule():
    import main
    routes = main.build_routes([{"segments": SEGS,
                                 "alert_direct": 1900,
                                 "alert_transfer": 1700}])
    assert len(routes) == 1
    r = routes[0]
    assert r.segments == normalize_segments(SEGS)
    assert (r.from_code, r.to_code) == ("SHA", "OSA")
    assert r.dates == ["2026-11-20", "2026-11-23"]
    reg, skipped = main.route_query_registry([{"routes": routes}])
    assert reg == {}, "多程航线被当单程注册进调度：%r" % (reg,)
    assert skipped and "2 段" in skipped[0], skipped

    normal = main.build_routes([{"from": "SHA", "to": "PEK",
                                 "dates": ["2026-11-20"]}])
    reg2, skipped2 = main.route_query_registry([{"routes": normal}])
    assert ("SHA", "PEK", "2026-11-20") in reg2
    assert not skipped2
    with pytest.raises(ValueError):
        main.build_routes([{"segments": SEGS[:1]}])


def test_itinerary_table_not_in_single_od_history(tmp_path):
    db = PriceStorage(str(tmp_path / "prices.db"))
    db.save_itinerary("app_qunar", "r1", SEGS, 5069.0, LEGS)
    assert db.itineraries(segments_key=segments_key(SEGS))[0]["extra"]["legs"]
    # 单 O-D 日桶必须保持空：多程不得混进 flight_daily
    assert db.flight_history("SHA", "NRT", "2026-11-20", "9C8515", "", 
                             ["app_qunar"], 30) == []
