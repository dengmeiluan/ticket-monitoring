# -*- coding: utf-8 -*-
"""r695：去哪儿 App 的低价机票接进特价雷达（发现源，不是明细）。

PC/H5 的 `low_fare` 维度指**发现源**：每天一条最低价，供「哪天最便宜」
使用。App 侧的对应物是首页「低价机票」→ 选城市 → 「搜索低价机票」，
顶部日期带每天一条最低价（真机 2026-10-30：北京→上海 14 天，¥350 起）。

两条必须守住的口径：
  * 价格是「优惠前含税均价」——标成 `tax_included=True` 并写明白，
    不能悄悄当裸价，也不能和「到手价」混为一谈；
  * 采不到时要区分「被拦/要登录」与「确实没有低价」，前者记 error。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.special_radar as sr


def _query(channels=("app_qunar",)):
    import datetime as dt
    today = dt.date.today()
    return sr.RadarQuery(
        user="t", from_code="BJS", from_name="北京", to_code="SHA",
        to_name="上海", start=today,
        end=today + dt.timedelta(days=13), channels=list(channels))


def test_app_qunar_is_a_radar_channel():
    assert "app_qunar" in sr._CHANNELS, sr._CHANNELS


def test_deals_mark_basis_unknown_when_page_says_nothing(monkeypatch):
    """页面没写口径时必须标「未标注」，不能假设含税。"""
    class Fake:
        paths = [{"path": "low-fare", "status": "ok", "detail": "14 天最低价"}]

        def low_fare(self, fc, tc, days=14):
            import datetime as dt
            d = dt.date.today()
            return [{"date": d.isoformat(), "weekday": "今天", "price": 358},
                    {"date": (d + dt.timedelta(days=1)).isoformat(),
                     "weekday": "明天", "price": 420}]

    import crawlers.app_qunar as mod
    monkeypatch.setattr(mod, "AppQunarCrawler", lambda *a, **k: Fake())
    rows, st = sr._app_qunar_deals(_query(), None)
    assert st["status"] == "ok" and st["rows"] == 2, st
    assert [r.src_price for r in rows] == [358.0, 420.0]
    for r in rows:
        # 页面没写口径 → 只能是 unknown（标含税会让人误当到手价）
        assert r.tax_included is None
        assert r.price_basis == "unknown"
        assert r.price_basis_label == "口径未标注"
        assert r.src == "app_qunar"


def test_blocked_source_is_error_not_empty(monkeypatch):
    """被登录/风控挡住时账本要写 error，不能记 empty（那是「没低价」）。"""
    class Fake:
        paths = [{"path": "low-fare", "status": "login",
                  "detail": "查询后要求登录"}]

        def low_fare(self, fc, tc, days=14):
            return []

    import crawlers.app_qunar as mod
    monkeypatch.setattr(mod, "AppQunarCrawler", lambda *a, **k: Fake())
    rows, st = sr._app_qunar_deals(_query(), None)
    assert rows == []
    assert st["status"] == "error", st
    assert "登录" in st["reason"]


def test_truly_no_low_fare_is_empty(monkeypatch):
    class Fake:
        paths = [{"path": "low-fare", "status": "ok", "detail": "0 天最低价"}]

        def low_fare(self, fc, tc, days=14):
            return []

    import crawlers.app_qunar as mod
    monkeypatch.setattr(mod, "AppQunarCrawler", lambda *a, **k: Fake())
    rows, st = sr._app_qunar_deals(_query(), None)
    assert rows == [] and st["status"] == "empty", st


def test_future_range_requests_strip_from_today(monkeypatch):
    """日期带从今天起算：未来 11-10..11-12 必须请求 11 天，不能只请求 3 天。

    负控：改回 `(end-start).days+1` 时 fake 只拿到 3 天，返回 11-02..11-04，
    过滤后为空——这正是 r815 线上 176s/empty 的形态。
    """
    import datetime as dt
    today = dt.date.today()
    seen = {}

    class Fake:
        paths = [{"path": "low-fare", "status": "ok", "detail": "ok"}]

        def low_fare(self, fc, tc, days=14):
            seen["days"] = days
            return [{"date": (today + dt.timedelta(days=i)).isoformat(),
                     "price": 300 + i} for i in range(days)]

    import crawlers.app_qunar as mod
    monkeypatch.setattr(mod, "AppQunarCrawler", lambda *a, **k: Fake())
    q = sr.RadarQuery("t", "BJS", "北京", "CAN", "广州",
                      today + dt.timedelta(days=8),
                      today + dt.timedelta(days=10), ["app_qunar"])
    rows, st = sr._app_qunar_deals(q, None)
    assert seen["days"] == 11, seen
    assert len(rows) == 3 and st["status"] == "ok", st
    assert {r.date for r in rows} == {
        (today + dt.timedelta(days=i)).isoformat() for i in (8, 9, 10)}


def test_range_beyond_strip_has_reason_not_bare_empty(monkeypatch):
    """超出 14 天日期带要明确说原因，不能只回一个无理由的 empty。"""
    import datetime as dt
    today = dt.date.today()
    called = {"n": 0}

    class Fake:
        paths = [{"path": "low-fare", "status": "ok", "detail": "ok"}]

        def low_fare(self, fc, tc, days=14):
            called["n"] += 1
            return []

    import crawlers.app_qunar as mod
    monkeypatch.setattr(mod, "AppQunarCrawler", lambda *a, **k: Fake())
    q = sr.RadarQuery("t", "BJS", "北京", "CAN", "广州",
                      today + dt.timedelta(days=20),
                      today + dt.timedelta(days=22), ["app_qunar"])
    rows, st = sr._app_qunar_deals(q, None)
    assert rows == [] and st["status"] == "empty", st
    assert "14 天" in st["reason"], st
    assert called["n"] == 0, "已知超出日期带仍去开真机（会白等）"


def test_returned_strip_missing_request_range_has_reason(monkeypatch):
    """App 只回今天附近而请求在更远日期：必须报「未覆盖」，不能裸 empty。"""
    import datetime as dt
    today = dt.date.today()

    class Fake:
        paths = [{"path": "low-fare", "status": "ok", "detail": "ok"}]

        def low_fare(self, fc, tc, days=14):
            return [{"date": (today + dt.timedelta(days=i)).isoformat(),
                     "price": 300} for i in range(3)]

    import crawlers.app_qunar as mod
    monkeypatch.setattr(mod, "AppQunarCrawler", lambda *a, **k: Fake())
    q = sr.RadarQuery("t", "BJS", "北京", "CAN", "广州",
                      today + dt.timedelta(days=8),
                      today + dt.timedelta(days=10), ["app_qunar"])
    rows, st = sr._app_qunar_deals(q, None)
    assert rows == [] and st["status"] == "empty", st
    assert "未覆盖" in st["reason"], st


def test_build_radar_routes_app_qunar(monkeypatch):
    """分发必须真的走到 _app_qunar_deals，不能落到 not_connected。"""
    called = {}

    def fake_deals(q, logger):
        called["yes"] = True
        return [], sr._status("ok", "", 0)

    monkeypatch.setattr(sr, "_app_qunar_deals", fake_deals)
    import datetime as dt
    today = dt.date.today()
    out = sr.build_radar({"user": "t", "from": "BJS", "to": "SHA",
                          "start": today.isoformat(),
                          "end": (today + dt.timedelta(days=5)).isoformat(),
                          "channels": ["app_qunar"]}, None)
    assert called.get("yes"), "build_radar 没分发到 app_qunar"
    assert "app_qunar" in out["channels"]
