# -*- coding: utf-8 -*-
"""Fliggy Taobao-H5 listing parser and fallback wiring."""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _payload():
    def flight(fno, price, dep="2026-10-24 08:00:00",
               arr="2026-10-24 12:00:00"):
        return {
            "flightInfos": [{
                "depTime": dep, "arrTime": arr,
                "flightSegments": [{
                    "marketingFlightNo": fno,
                    "marketingAirlineName": "东方航空|中国东方航空",
                    "segmentFlightDetailUniq": "SHA_BKK_2026-10-24_" + fno,
                    "depCityCode": "SHA", "arrCityCode": "BKK",
                }],
            }],
            "priceInfo": {"adultPrice": price, "adultTax": 4000,
                          "adultTotalPrice": price + 4000,
                          "afterPromotionTotalPrice": price + 3000},
        }
    return {"data": {"items": [
        {"itemType": "TITLE", "data": []},
        {"itemType": "FLIGHT_DIRECT", "data": [flight("MU521", 56000)]},
        {"itemType": "FLIGHT_TRANSFER", "data": [flight("MU999", 48000)]},
        {"itemType": "FLIGHT_DIRECT", "data": [flight("MU521", 59000)]},
    ]}}


def test_parse_listing_keeps_real_flights_and_lowest_price():
    from crawlers.fliggy_h5 import parse_listing
    rows = parse_listing(_payload(), "SHA", "BKK", "2026-10-24")
    assert len(rows) == 2
    by = {r.flight_no: r for r in rows}
    assert by["MU521"].price == 600.0          # adultTotalPrice 60000 分
    assert by["MU521"].depart_time == "08:00"
    assert by["MU521"].arrive_time == "12:00"
    assert by["MU999"].price == 520.0
    assert by["MU521"].platform == "fliggy"
    assert "fliggy_h5" in by["MU521"].extra


def test_parse_listing_rejects_wrong_route_or_date():
    from crawlers.fliggy_h5 import parse_listing
    p = _payload()
    assert parse_listing(p, "PEK", "BKK", "2026-10-24") == []
    assert parse_listing(p, "SHA", "BKK", "2026-10-25") == []


def test_parse_listing_skips_rows_without_flight_number_or_price():
    from crawlers.fliggy_h5 import parse_listing
    assert parse_listing({"data": {"items": [
        {"itemType": "FLIGHT_DIRECT", "data": [{"flightInfos": [],
                                                 "priceInfo": {"adultPrice": 1}}]},
        {"itemType": "FLIGHT_DIRECT", "data": [{
            "flightInfos": [{"flightSegments": [{"marketingFlightNo": "MU1"}],
                             "depTime": "2026-10-24 08:00:00"}],
            "priceInfo": {}}]},
    ]}}, "SHA", "BKK", "2026-10-24") == []


def test_h5_crawler_uses_separate_profile_and_has_pc_fallback():
    from crawlers.fliggy import FliggyCrawler
    from crawlers.fliggy_h5 import FliggyH5Crawler
    c = FliggyH5Crawler({"user_data_dir": "user_data"},
                        logging.getLogger("h5-test"))
    assert c.name == "fliggy"
    assert c.profile_name == "fliggy_h5"
    assert c.use_mobile is True
    assert "_h5_fallback" in dir(FliggyCrawler)
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "crawlers", "fliggy.py"),
        encoding="utf-8").read()
    assert "listingsearch" in src or "FliggyH5Crawler" in src
    assert "H5:" in src
