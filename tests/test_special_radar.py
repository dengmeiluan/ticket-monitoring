# -*- coding: utf-8 -*-
"""特价雷达：日期/渠道归一化与诚实状态。"""
import logging
from datetime import date, timedelta

import pytest

from core.special_radar import build_radar, normalize, parse_query
from core.specials import SpecialDeal

@pytest.fixture(autouse=True)
def _clear_radar_cache():
    import core.special_radar as sr
    sr._FLIGGY_CACHE.clear()
    sr._QUNAR_CACHE.clear()
    sr._TUNIU_CACHE.clear()
    sr._FLIGGY_COOLDOWN_UNTIL = 0.0
    sr._QUNAR_COOLDOWN_UNTIL = 0.0
    yield


TOMORROW = (date.today() + timedelta(days=1)).isoformat()
LATER = (date.today() + timedelta(days=30)).isoformat()


def _q(**kw):
    p = {"from": "SHA", "to": "BKK", "start": TOMORROW, "end": LATER,
         "channels": ["ctrip", "fliggy"]}
    p.update(kw)
    return parse_query(p)


def test_parse_query_rejects_short_range_and_bad_city():
    with pytest.raises(ValueError):
        parse_query({"from": "SHA", "to": "BKK", "start": LATER,
                     "end": TOMORROW, "channels": ["ctrip"]})
    with pytest.raises(ValueError):
        parse_query({"from": "??", "to": "BKK", "start": TOMORROW,
                     "end": LATER, "channels": ["ctrip"]})


def test_parse_query_accepts_chinese_intl_names():
    q = _q(**{"from": "上海", "to": "曼谷"})
    assert (q.from_code, q.to_code) == ("SHA", "BKK")
    q = _q(**{"from": "上海", "to": "大阪关西"})
    assert q.to_code == "KIX"
    q = _q(**{"from": "上海", "to": "大阪"})
    assert q.to_code == "OSA"


def test_normalize_keeps_lowest_per_channel_and_marks_kind():
    q = _q()
    deals = [
        SpecialDeal("ctrip", "SHA", "BKK", TOMORROW, 1200,
                    link="https://c/1", to_name="曼谷"),
        SpecialDeal("ctripbd", "SHA", "BKK", TOMORROW, 1100,
                    link="https://c/2", to_name="曼谷"),
        SpecialDeal("fliggy", "SHA", "BKK", TOMORROW, 1300,
                    to_name="曼谷"),
        SpecialDeal("fliggy", "SHA", "BKK", LATER, 900, to_name="曼谷"),
    ]
    rows = normalize(deals, q)
    assert [r["date"] for r in rows] == [TOMORROW, LATER]
    first = rows[0]
    assert first["by_channel"]["ctrip"]["price"] == 1100
    assert first["by_channel"]["ctrip"]["kind"] == "board"
    assert first["best"]["channel"] == "ctrip"
    assert first["best"]["kind"] in ("calendar", "board")
    assert rows[1]["best"]["channel"] == "fliggy"


def test_normalize_filters_route_and_range():
    q = _q()
    rows = normalize([
        SpecialDeal("ctrip", "SHA", "CAN", TOMORROW, 500, to_name="广州"),
        SpecialDeal("ctrip", "SHA", "BKK", LATER, 800, to_name="曼谷"),
    ], q)
    assert len(rows) == 1
    assert rows[0]["date"] == LATER


def test_qunar_low_price_calendar_maps(monkeypatch):
    import core.special_radar as sr
    monkeypatch.setattr(sr, "_QUNAR_COOLDOWN_UNTIL", 0.0)
    obj = {"bstatus": 0, "lowPriceList": [
        {"depDate": TOMORROW, "price": 1262},
        {"depDate": LATER, "price": 0},
    ]}
    monkeypatch.setattr(
        "crawlers.qunar.QunarCrawler.fetch_low_price_calendar",
        staticmethod(lambda *a, **k: obj))
    out = build_radar({"from": "SHA", "to": "BKK", "start": TOMORROW,
                       "end": LATER, "channels": ["qunar"]},
                      logging.getLogger("radar"))
    assert out["channels"]["qunar"]["status"] == "ok"
    assert out["channels"]["qunar"]["rows"] == 1
    assert out["lowest"]["kind"] == "calendar"
    assert "lowFlight" in out["lowest"]["link"]


def test_qunar_failure_is_honest(monkeypatch):
    import core.special_radar as sr
    monkeypatch.setattr(sr, "_QUNAR_COOLDOWN_UNTIL", 0.0)
    monkeypatch.setattr(
        "crawlers.qunar.QunarCrawler.fetch_low_price_calendar",
        staticmethod(lambda *a, **k: None))
    out = build_radar({"from": "SHA", "to": "BKK", "start": TOMORROW,
                       "end": LATER, "channels": ["qunar"]},
                      logging.getLogger("radar"))
    assert out["dates"] == []
    assert out["channels"]["qunar"]["status"] == "error"
    assert "风控" in out["channels"]["qunar"]["reason"]


def test_tongcheng_calendar_maps_prices(monkeypatch):
    days = [{"date": TOMORROW, "price": 1262},
            {"date": LATER, "price": None},
            {"date": LATER, "price": 700}]
    seen = {}

    def fake(*a, **k):
        seen["args"] = a
        return days
    monkeypatch.setattr("core.special_radar.fetch_tongcheng_calendar", fake)
    out = build_radar({"from": "SHA", "to": "BKK", "start": TOMORROW,
                       "end": LATER, "channels": ["tongcheng"]},
                      logging.getLogger("radar"))
    assert out["channels"]["tongcheng"]["status"] == "ok"
    assert out["channels"]["tongcheng"]["rows"] == 2
    assert out["lowest"]["price"] == 700
    assert out["lowest"]["kind"] == "calendar"
    assert seen["args"][0] == "SHA" and seen["args"][2] == "BKK"


def test_fliggy_calendar_uses_tax_inclusive_rows(monkeypatch):
    days = [
        {"leaveDate": TOMORROW, "price": 800, "tax": 462,
         "url": "//sijipiao.fliggy.com/ie/x"},
        {"leaveDate": LATER, "price": 900, "tax": 0, "url": ""},
        {"leaveDate": LATER, "price": 950, "tax": 0, "url": ""},
    ]
    monkeypatch.setattr("core.special_radar.fetch_fliggy_calendar",
                        lambda *a, **k: days)
    out = build_radar({"from": "SHA", "to": "BKK", "start": TOMORROW,
                       "end": LATER, "channels": ["fliggy"]},
                      logging.getLogger("radar"))
    assert out["channels"]["fliggy"]["status"] == "ok"
    assert out["channels"]["fliggy"]["rows"] == 2
    row = next(d for d in out["dates"] if d["date"] == TOMORROW)
    assert row["best"]["price"] == 1262
    assert row["best"]["kind"] == "calendar"
    assert row["best"]["link"].startswith("https://")
    # 同日重复只保留一条（normalize 按渠道取最低）
    later = next(d for d in out["dates"] if d["date"] == LATER)
    assert later["best"]["price"] == 900


def test_fliggy_and_qunar_reuse_short_cache(monkeypatch):
    import core.special_radar as sr
    calls = {"fliggy": 0, "qunar": 0}

    def f_fliggy(*a, **k):
        calls["fliggy"] += 1
        return [{"leaveDate": TOMORROW, "price": 100, "tax": 0,
                 "url": ""}]

    def f_qunar(*a, **k):
        calls["qunar"] += 1
        return {"bstatus": 0, "lowPriceList": [
            {"depDate": TOMORROW, "price": 90}]}
    monkeypatch.setattr("core.special_radar.fetch_fliggy_calendar", f_fliggy)
    monkeypatch.setattr(
        "crawlers.qunar.QunarCrawler.fetch_low_price_calendar",
        staticmethod(f_qunar))
    body = {"from": "SHA", "to": "BKK", "start": TOMORROW,
            "end": LATER, "channels": ["fliggy", "qunar"]}
    a = build_radar(body, logging.getLogger("radar"))
    b = build_radar(body, logging.getLogger("radar"))
    # 飞猪按 30 天范围滚 5 个 7 天窗（首次），第二次整段命中缓存
    assert calls == {"fliggy": 5, "qunar": 1}, calls
    assert a["channels"]["fliggy"]["rows"] == 1
    assert b["channels"]["fliggy"]["rows"] == 1
    assert "复用" in b["channels"]["fliggy"]["reason"]
    assert "复用" in b["channels"]["qunar"]["reason"]


def test_tuniu_domestic_calendar_maps(monkeypatch):
    days = [{"date": TOMORROW, "price": 410},
            {"date": LATER, "price": 0},
            {"date": LATER, "price": 380}]
    monkeypatch.setattr("core.special_radar.fetch_tuniu_calendar",
                        lambda *a, **k: days)
    out = build_radar({"from": "SHA", "to": "BJS", "start": TOMORROW,
                       "end": LATER, "channels": ["tuniu"]},
                      logging.getLogger("radar"))
    assert out["channels"]["tuniu"]["status"] == "ok"
    assert out["channels"]["tuniu"]["rows"] == 2
    assert out["lowest"]["kind"] == "calendar"
    assert out["lowest"]["price"] == 380
    assert "m.tuniu.com" in out["lowest"]["link"]


def test_nationwide_only_ctrip_and_others_unsupported():
    q = _q(nationwide=True, to="", channels=["qunar"])
    out = build_radar({"from": q.from_code, "to": "", "nationwide": True,
                       "start": q.start.isoformat(), "end": q.end.isoformat(),
                       "channels": q.channels}, logging.getLogger("radar"))
    assert out["channels"]["qunar"]["status"] == "unsupported"
    assert out["dates"] == []
