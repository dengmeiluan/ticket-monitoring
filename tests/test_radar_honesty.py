# -*- coding: utf-8 -*-
"""特价雷达诚实性：价格口径、机场→城市码、缓存溯源、渠道边界。"""
import logging
import time
from datetime import date, timedelta

import pytest

import core.special_radar as sr
from core.specials import SpecialDeal

LOG = logging.getLogger("radar-honesty")
TOMORROW = date.today() + timedelta(days=1)
WEEK = TOMORROW + timedelta(days=6)


@pytest.fixture(autouse=True)
def _clear_caches():
    for cache in (sr._FLIGGY_CACHE, sr._QUNAR_CACHE, sr._TUNIU_CACHE,
                  sr._TONGCHENG_CACHE):
        cache.clear()
    sr._FLIGGY_COOLDOWN_UNTIL = 0.0
    sr._QUNAR_COOLDOWN_UNTIL = 0.0
    yield
    for cache in (sr._FLIGGY_CACHE, sr._QUNAR_CACHE, sr._TUNIU_CACHE,
                  sr._TONGCHENG_CACHE):
        cache.clear()
    sr._FLIGGY_COOLDOWN_UNTIL = 0.0
    sr._QUNAR_COOLDOWN_UNTIL = 0.0


def _body(**kw):
    p = {"from": "SHA", "to": "BKK", "start": TOMORROW.isoformat(),
         "end": WEEK.isoformat(), "channels": ["fliggy"]}
    p.update(kw)
    return p


def _deal(src, price, **kw):
    return SpecialDeal(src, "SHA", "BKK", TOMORROW.isoformat(), price,
                       to_name="曼谷", **kw)


def test_mixed_basis_prefers_tax_inclusive_and_flags(monkeypatch):
    bare = _deal("ctripbd", 500, tax_included=False, price_basis="bare",
                 price_basis_label="裸价不含税")
    taxed = _deal("fliggycal", 700, tax_included=True,
                  price_basis="tax_included", price_basis_label="含税总价")
    monkeypatch.setattr(sr, "_ctrip_deals",
                        lambda q, logger, proxy: (
                            [bare], sr._status("ok", "", 1)))
    monkeypatch.setattr(sr, "_fliggy_deals",
                        lambda q, logger, proxy: (
                            [taxed], sr._status("ok", "", 1)))
    out = sr.build_radar(_body(channels=["ctrip", "fliggy"]), LOG)
    row = out["dates"][0]
    assert row["by_channel"]["ctrip"]["basis"] == "bare"
    assert row["by_channel"]["fliggy"]["tax_included"] is True
    low = out["lowest"]
    assert low["price"] == 700
    assert low["lowest_basis"] == "tax_included"
    assert low["basis_mixed"] is True
    assert out["basis_mixed"] is True
    assert low["cheaper_cross_basis"]["price"] == 500
    assert "混合" in low["note"]


def test_bare_lowest_is_labeled_not_unqualified(monkeypatch):
    bare = _deal("ctripbd", 500, tax_included=False, price_basis="bare",
                 price_basis_label="裸价不含税")
    unknown = _deal("qunar", 450, tax_included=None, price_basis="unknown",
                    price_basis_label="口径未标注")
    monkeypatch.setattr(sr, "_ctrip_deals",
                        lambda q, logger, proxy: (
                            [bare], sr._status("ok", "", 1)))
    monkeypatch.setattr(sr, "_qunar_deals",
                        lambda q, logger, proxy, root: (
                            [unknown], sr._status("ok", "", 1)))
    out = sr.build_radar(_body(channels=["ctrip", "qunar"]), LOG)
    low = out["lowest"]
    assert low["price"] == 450
    assert low["lowest_basis"] == "unknown"
    assert low["basis_mixed"] is True
    assert "混合" in low["note"] and "口径未标注" in low["note"]
    assert out["lowest_platform"] == "qunar"
    assert out["lowest_date"] == TOMORROW.isoformat()


def test_airport_codes_normalized_before_channel_calls(monkeypatch):
    seen = {}

    def ctrip(fc, tc, start, logger, **kw):
        seen["ctrip"] = (fc, tc)
        return None

    def fliggy(fc, tc, leave, logger, **kw):
        seen["fliggy"] = (fc, tc)
        return []

    def tongcheng(fc, fn, tc, tn, anchor, logger, **kw):
        seen["tongcheng"] = (fc, tc)
        return []

    monkeypatch.setattr(sr, "fetch_ctrip_calendar", ctrip)
    monkeypatch.setattr(sr, "fetch_fliggy_calendar", fliggy)
    monkeypatch.setattr(sr, "fetch_tongcheng_calendar", tongcheng)
    out = sr.build_radar(
        _body(**{"from": "PVG", "to": "NRT",
                 "channels": ["ctrip", "fliggy", "tongcheng"]}), LOG)
    assert seen == {"ctrip": ("SHA", "TYO"), "fliggy": ("SHA", "TYO"),
                    "tongcheng": ("SHA", "TYO")}
    assert out["query"]["from"] == "SHA"
    assert out["query"]["to"] == "TYO"


def test_cache_key_identity_and_provenance(monkeypatch):
    calls = []

    def fake(fc, fn, tc, tn, anchor, logger, **kw):
        calls.append((fc, tc))
        return [{"date": TOMORROW.isoformat(), "price": 600}]

    monkeypatch.setattr(sr, "fetch_tongcheng_calendar", fake)
    body = _body(user="alice", channels=["tongcheng"])
    first = sr.build_radar(body, LOG)
    assert first["channels"]["tongcheng"]["status"] == "ok"
    assert not first["channels"]["tongcheng"].get("cache_hit")
    first_at = first["channels"]["tongcheng"]["generated_at"]
    second = sr.build_radar(body, LOG)
    st = second["channels"]["tongcheng"]
    assert len(calls) == 1
    assert st["cache_hit"] is True
    assert st["cached_at"]
    assert st["generated_at"] == first_at
    assert st["original_status"] == "ok"
    assert "复用" in st["reason"]
    # 不同用户不得复用同一缓存
    other = sr.build_radar(_body(user="bob", channels=["tongcheng"]), LOG)
    assert len(calls) == 2
    assert not other["channels"]["tongcheng"].get("cache_hit")


def test_fliggy_fallback_is_partial_and_sets_cooldown(monkeypatch):
    monkeypatch.setattr(sr, "fetch_fliggy_calendar", lambda *a, **k: None)
    payload = {"data": {"flights": [{
        "depCode": "SHA", "arrCode": "BKK",
        "depDate": TOMORROW.isoformat(), "price": 999,
    }]}}
    monkeypatch.setattr(sr, "fetch_fliggy_board",
                        lambda *a, **k: payload)
    body = _body(user="carol", channels=["fliggy"])
    out = sr.build_radar(body, LOG)
    st = out["channels"]["fliggy"]
    assert st["status"] == "ok"
    assert st["partial"] is True
    assert st["fallback"] == "board"
    assert "回退" in st["reason"] and "65B" in st["reason"]
    assert sr._FLIGGY_COOLDOWN_UNTIL > time.time()
    # 命中原缓存：重放回退原因，不改写为“复用成功结果”
    hit = sr.build_radar(body, LOG)["channels"]["fliggy"]
    assert hit["cache_hit"] is True
    assert "回退" in hit["original_reason"]
    assert "回退" in hit["reason"]
    assert "复用" in hit["reason"]


def test_fliggy_timeout_and_65b_are_distinct(monkeypatch):
    def boom(*a, **k):
        raise TimeoutError("read timeout")

    monkeypatch.setattr(sr, "fetch_fliggy_calendar", boom)
    monkeypatch.setattr(sr, "fetch_fliggy_board", lambda *a, **k: None)
    err = sr.build_radar(_body(user="t1", channels=["fliggy"]), LOG)
    reason = err["channels"]["fliggy"]["reason"]
    assert err["channels"]["fliggy"]["status"] == "error"
    assert "超时" in reason and "65B" not in reason

    sr._FLIGGY_COOLDOWN_UNTIL = 0.0
    monkeypatch.setattr(sr, "fetch_fliggy_calendar", lambda *a, **k: None)
    refused = sr.build_radar(_body(user="t2", channels=["fliggy"]), LOG)
    refuse_reason = refused["channels"]["fliggy"]["reason"]
    assert refused["channels"]["fliggy"]["status"] == "error"
    assert "65B" in refuse_reason and "超时" not in refuse_reason


def test_fliggy_90day_request_reports_partial_coverage(monkeypatch):
    calls = []

    def fake(fc, tc, leave, logger, **kw):
        calls.append(leave)
        d0 = date.fromisoformat(leave)
        return [{"leaveDate": (d0 + timedelta(days=i)).isoformat(),
                 "price": 300 + i, "tax": 0} for i in range(7)]

    monkeypatch.setattr(sr, "fetch_fliggy_calendar", fake)
    end = (TOMORROW + timedelta(days=89)).isoformat()
    out = sr.build_radar(_body(user="d90", start=TOMORROW.isoformat(),
                               end=end, channels=["fliggy"]), LOG)
    st = out["channels"]["fliggy"]
    assert len(calls) == 5
    assert st["requested_days"] == 90
    assert st["covered_days"] == 35
    assert st["partial"] is True
    assert "35/90" in st["reason"]


def test_tongcheng_code5_maps_to_unsupported(monkeypatch):
    monkeypatch.setattr(sr, "fetch_tongcheng_calendar",
                        lambda *a, **k: [])
    out = sr.build_radar(_body(channels=["tongcheng"]), LOG)
    st = out["channels"]["tongcheng"]
    assert st["status"] == "unsupported"
    assert "code=5" in st["reason"] and "非法航线" in st["reason"]


def test_tuniu_intl_never_uses_domestic_board(monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("国际航线不得调用国内出发榜")

    monkeypatch.setattr(sr, "fetch_tuniu_board", forbidden)
    out = sr.build_radar(_body(channels=["tuniu"]), LOG)
    st = out["channels"]["tuniu"]
    assert st["status"] == "unsupported"
    assert "国际" in st["reason"]
    assert out["dates"] == []


def test_tuniu_domestic_board_fallback_is_labeled(monkeypatch):
    monkeypatch.setattr(sr, "fetch_tuniu_calendar",
                        lambda *a, **k: None)
    payload = {"data": {"cityFlightInfo": {"singleTrip": [{
        "orgCityIata": "SHA", "dstCityIata": "BJS",
        "departureDate": TOMORROW.isoformat(), "priceBase": 450,
    }]}}}
    monkeypatch.setattr(sr, "fetch_tuniu_board", lambda *a, **k: payload)
    out = sr.build_radar(_body(to="BJS", channels=["tuniu"]), LOG)
    st = out["channels"]["tuniu"]
    assert st["status"] == "ok"
    assert st["rows"] == 1
    assert st["fallback"] == "board"
    assert st["partial"] is True
    assert "回退" in st["reason"] and "裸价" in st["reason"]
