# -*- coding: utf-8 -*-
"""r384 同程国际：窗历（queryCalendarLowestPrice）为主通路。

实证（2026-10-26）：
- ts/calendar 需页内 as-sdk 会话签名；页内 fetch/XHR 手打同形 URL
  均回 {"code":444,"message":"非法链接"}——签名只覆盖站点自己发的
  请求（hook uri 白名单只有 search/list/submitOrder，calendar 不在内）。
- 所以「页内 fetch + 同形 URL」这条路本身不成立，此前国际持续
  0 数据不是限流也不是无票。
- 低价日历 queryCalendarLowestPrice 无登录无签名，一次 HTTP 返回
  90 天窗口，价格与站点签名日历的 TP 逐日同值（11-08 640/640、
  11-10 643/643、11-24 643/643）。

本文件钉住窗历通路的行为契约（离线，全部替身）。
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.tongcheng import TongchengCrawler  # noqa: E402

_LOG = logging.getLogger("t_r384_tc")
_TC = TongchengCrawler({}, _LOG)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_window_cache():
    """窗历缓存是实例级、跨轮存活：每个用例都必须从空缓存开始，
    否则前一个用例的窗口会把后一个用例的请求全吃掉。"""
    _TC._intl_win_cache = {}
    yield
    _TC._intl_win_cache = {}


def _rows(days, first="2026-10-28", gaps=False):
    """构造渠道窗历行：从 first 起逐日；gaps=True 时每天给 None。
    真实窗口首日常无价（站点当天不报价），其余日价为 500+i。"""
    from datetime import date, timedelta
    d0 = date.fromisoformat(first)
    out = []
    for i in range(days):
        d = (d0 + timedelta(days=i)).isoformat()
        out.append({"date": d,
                    "price": (None if (gaps and i % 7 == 0) else 500 + i),
                    "dcc": "HKG", "occ": "SHA", "isInter": 1,
                    "week": "周一"})
    return out


def _patch(monkeypatch, fn):
    import crawlers.special as sp
    monkeypatch.setattr(sp, "fetch_tongcheng_calendar", fn)


# ---- 通路：一次请求覆盖 90 天窗口 ----

def test_window_single_call_covers_year_dates(monkeypatch):
    calls = []

    def fake(fc, fn, tc, tn, anchor, logger, **kw):
        calls.append((fc, tc, anchor))
        return _rows(90)

    _patch(monkeypatch, fake)
    got, info = _TC._intl_window_prices(
        "SHA", "HKG", ["2026-11-10", "2026-11-24", "2026-12-05"])
    assert info["calls"] == 1, "同窗内多日期只发 1 次请求"
    assert set(got) == {"2026-11-10", "2026-11-24", "2026-12-05"}
    assert got["2026-11-10"] == 513.0     # 首日 2026-10-28 起第 13 天
    assert calls[0][:2] == ("SHA", "HKG")


def test_window_advances_anchor_for_far_dates(monkeypatch):
    calls = []

    def fake(fc, fn, tc, tn, anchor, logger, **kw):
        calls.append(anchor)
        # 窗口固定 90 天，从 fake 的锚点起（模拟真实边界）
        return _rows(90, first=anchor)

    _patch(monkeypatch, fake)
    got, info = _TC._intl_window_prices(
        "SHA", "HKG", ["2026-11-10", "2027-03-05"])
    assert info["calls"] == 2, "超出首窗的日期需换锚再取一次"
    assert len(calls) == 2 and calls[1] > calls[0]
    assert "2027-03-05" in got

def test_window_never_exceeds_three_calls(monkeypatch):
    calls = []

    def fake(fc, fn, tc, tn, anchor, logger, **kw):
        calls.append(anchor)
        return _rows(1, first=anchor)   # 每天只给 1 天 → 最坏情况

    _patch(monkeypatch, fake)
    got, info = _TC._intl_window_prices(
        "SHA", "HKG", ["2026-11-10", "2026-11-11", "2026-11-12",
                       "2026-11-13", "2026-11-14"])
    assert info["calls"] <= 3, "换锚有硬上限，防死循环"
    assert info["covered"] <= 3


def test_window_none_price_is_not_invented(monkeypatch):
    def fake(fc, fn, tc, tn, anchor, logger, **kw):
        return [{"date": "2026-11-10", "price": None},
                {"date": "2026-11-11", "price": 0},
                {"date": "2026-11-12", "price": 688}]

    _patch(monkeypatch, fake)
    got, _info = _TC._intl_window_prices(
        "SHA", "HKG", ["2026-11-10", "2026-11-11", "2026-11-12"])
    assert got == {"2026-11-12": 688.0}, "空价/0 价不臆造"


def test_window_channel_no_data_is_unsupported(monkeypatch):
    def fake(fc, fn, tc, tn, anchor, logger, **kw):
        return []          # 渠道 code=5（非法航线/超窗）

    _patch(monkeypatch, fake)
    got, info = _TC._intl_window_prices("SHA", "ZZZ", ["2026-11-10"])
    assert got == {}
    assert info["unsupported"] is True and info["failed"] is False


def test_window_request_failure_is_failed_not_empty(monkeypatch):
    def fake(fc, fn, tc, tn, anchor, logger, **kw):
        return None        # 网络/协议失败

    _patch(monkeypatch, fake)
    got, info = _TC._intl_window_prices("SHA", "HKG", ["2026-11-10"])
    assert got == {}
    assert info["failed"] is True and info["unsupported"] is False


def test_window_skips_expired_dates_without_request(monkeypatch):
    calls = []

    def fake(fc, fn, tc, tn, anchor, logger, **kw):
        calls.append(anchor)
        return _rows(90)

    _patch(monkeypatch, fake)
    got, info = _TC._intl_window_prices(
        "SHA", "HKG", ["2000-01-01", "2000-01-02"])
    assert calls == [], "全过期日期不发请求"
    assert info["expired"] == 2 and got == {}


def test_window_reused_across_dates_in_one_round(monkeypatch):
    """主链路按日期拆多次 fetch：窗历必须复用，否则 14 日窗=14 次请求。"""
    calls = []

    def fake(fc, fn, tc, tn, anchor, logger, **kw):
        calls.append(anchor)
        return _rows(90)

    _patch(monkeypatch, fake)
    _TC._intl_win_cache = {}
    d1, i1 = _TC._intl_window_prices("SHA", "HKG", ["2026-11-10"])
    d2, i2 = _TC._intl_window_prices("SHA", "HKG", ["2026-11-24"])
    assert len(calls) == 1, "同日航线的第二个日期直接命中缓存"
    assert i2["cached"] == 1 and i2["calls"] == 0
    assert d1["2026-11-10"] == 513.0
    assert d2["2026-11-24"] == 527.0, "整窗都在缓存里（不只首个日期）"
    assert i2["span"], "复用也要带上窗口跨度（可观测）"


def test_window_cache_expires(monkeypatch):
    calls = []

    def fake(fc, fn, tc, tn, anchor, logger, **kw):
        calls.append(anchor)
        return _rows(90)

    _patch(monkeypatch, fake)
    import crawlers.tongcheng as tc_mod
    _TC._intl_win_cache = {}
    _TC._intl_window_prices("SHA", "HKG", ["2026-11-10"])
    old = tc_mod.time.time
    try:
        tc_mod.time.time = lambda: old() + _TC.INTL_WIN_CACHE_S + 1
        _TC._intl_window_prices("SHA", "HKG", ["2026-11-24"])
    finally:
        tc_mod.time.time = old
    assert len(calls) == 2, "TTL 过后重新取窗"

    _TC._intl_win_cache = {}


def test_window_failures_are_not_cached(monkeypatch):
    state = {"n": 0}

    def fake(fc, fn, tc, tn, anchor, logger, **kw):
        state["n"] += 1
        return None if state["n"] == 1 else _rows(90)

    _patch(monkeypatch, fake)
    _TC._intl_win_cache = {}
    d1, i1 = _TC._intl_window_prices("SHA", "HKG", ["2026-11-10"])
    assert i1["failed"] and not d1
    d2, i2 = _TC._intl_window_prices("SHA", "HKG", ["2026-11-24"])
    assert i2["calls"] == 1 and d2, "失败不缓存，下一日期可重试"
    _TC._intl_win_cache = {}


# ---- 行形态：可溯源 + 无明细不假装 ----

def test_window_row_is_traceable_calendar_row():
    row = _TC._intl_window_row("SHA", "HKG", "SHA", "HKG", "2026-11-10",
                               643.0)
    el = json.loads(row.extra)[0]
    assert el["source"] == "tc_window_calendar", "通路可溯源到窗历"
    assert el["name"] == "日历最低价"
    assert el["depTime"] == "" and el["arrTime"] == "", \
        "窗历无时刻，不得冒充明细"
    assert el["intl"] == 1 and el["price"] == 643.0
    assert "tax" not in el, "窗历只给含税总价，不臆造票面/税额"
    assert row.price == 643.0 and row.depart_date == "2026-11-10"


# ---- 接线：定时走窗历、探针要明细 ----

def _fetch_harness(monkeypatch, *, probe, rest_called, extra_dates=()):
    _patch(monkeypatch, lambda *a, **k: _rows(90))

    def fake_fb(self, from_city, to_city, dates, fc, tc, ret_date=""):
        rest_called.append(list(dates))
        return []

    monkeypatch.setattr(TongchengCrawler, "_intl_browser_fallback",
                        fake_fb)
    _TC.probe_mode = probe
    _TC.paths = []
    try:
        return _TC._fetch_intl("SHA", "HKG",
                               ["2026-11-10", "2026-11-24", *extra_dates])
    finally:
        _TC.probe_mode = False


def test_monitor_mode_uses_window_only(monkeypatch):
    rest = []
    rows = _fetch_harness(monkeypatch, probe=False, rest_called=rest)
    assert len(rows) == 2, "定时面两日都由窗历给出"
    assert rest == [], "定时面不启浏览器（限流主因）"
    assert all(json.loads(r.extra)[0]["source"] == "tc_window_calendar"
               for r in rows)


def test_monitor_mode_skips_dates_outside_window(monkeypatch):
    rest = []
    # 2028 远超 90 天窗口且换锚也取不到 → 定时面不得为此启浏览器
    rows = _fetch_harness(monkeypatch, probe=False, rest_called=rest,
                          extra_dates=("2028-06-01",))
    assert len(rows) == 2
    assert rest == []


def test_probe_mode_still_prefers_real_detail(monkeypatch):
    rest = []
    # 2028-06-01 窗口取不到：探针要明细，这一日必须走页内真实列表
    rows = _fetch_harness(monkeypatch, probe=True, rest_called=rest,
                          extra_dates=("2028-06-01",))
    assert len(rows) == 2, "窗历行照出"
    assert rest and rest[0] == ["2028-06-01"], \
        "只对未覆盖日期去取明细，已覆盖日期不重复启浏览器"


def test_window_path_recorded_as_calendar(monkeypatch):
    rest = []
    _fetch_harness(monkeypatch, probe=False, rest_called=rest)
    notes = [p for p in _TC.paths if p["path"] == "窗历"]
    assert len(notes) == 2
    assert all(p["status"] == "calendar" for p in notes)
    assert all(p["http"] == 200 for p in notes), "HTTP 状态入账"
    assert all(p["date"] for p in notes), "逐日可溯源"


# ---- 建议引擎：窗历出数后不得再喊日历劣化 ----

def _deg_node(paths):
    return {"paths": paths, "query_attempts": 10, "query_ok": 5,
            "query_detail_ok": 0, "query_calendar_only": 5,
            "scopes": {"dom": {"paths": {}},
                       "intl": {"paths": paths}}}


def test_advise_skips_calendar_family_when_window_ok():
    from core.pacing import advise
    paths = {
        "日历": {"attempts": 20, "ok": 0, "calendar_ok": 0,
                 "rate": 0.0, "rate_excl_empty": 0.0},
        "窗历": {"attempts": 20, "ok": 20, "calendar_ok": 20,
                 "rate": 1.0, "rate_excl_empty": 1.0},
    }
    a = advise("tongcheng", {}, paths,
               now=None, node=_deg_node(paths))
    assert a["state"] != "path_degraded", \
        "同域窗历在出数，不能再把旧日历路径报成待修（%s）" % a


def test_advise_still_reports_other_degraded_paths():
    from core.pacing import advise
    paths = {
        "窗历": {"attempts": 20, "ok": 20, "calendar_ok": 20,
                 "rate": 1.0, "rate_excl_empty": 1.0},
        "H5列表": {"attempts": 20, "ok": 0, "calendar_ok": 0,
                   "rate": 0.0, "rate_excl_empty": 0.0},
    }
    a = advise("tongcheng", {}, paths, now=None, node=_deg_node(paths))
    assert a["state"] == "path_degraded"
    # r658：提示里给人看的是中文通路名（H5列表 → 「H5 列表」），
    # 断言走同一个显示名函数，别把中文字面量钉死。
    from core.channels import path_cn
    assert path_cn("H5列表") in a["hint"]


# ---- 复审回归：缓存不得短路过期/换锚；定时面不得启浏览器 ----

def test_cache_hit_does_not_return_expired_dates():
    """跨午夜的缓存会把昨天的日期当有价返回（复审 #1）。"""
    from datetime import date, timedelta
    _TC._intl_win_cache = {}
    y = (date.today() - timedelta(days=1)).isoformat()
    _TC._intl_win_cache["SHA-HKG"] = (
        __import__("time").time(), {y: 640.0}, "old")
    got, info = _TC._intl_window_prices("SHA", "HKG", [y])
    assert got == {}, "过期日期不得从缓存里被当成有价"
    assert info["expired"] == 1


def test_cache_hit_re_anchors_for_uncovered_dates(monkeypatch):
    """缓存只覆盖首窗时，超出日期必须换锚再取（复审 #1）。"""
    calls = []

    def fake(fc, fn, tc, tn, anchor, logger, **kw):
        calls.append(anchor)
        return _rows(90, first=anchor)

    _patch(monkeypatch, fake)
    _TC._intl_win_cache = {}
    _TC._intl_window_prices("SHA", "HKG", ["2026-11-10"])
    assert len(calls) == 1
    got, info = _TC._intl_window_prices("SHA", "HKG", ["2027-03-05"])
    assert len(calls) == 2, "缓存没覆盖的日期要真的去取，不能短路"
    assert "2027-03-05" in got


def test_cache_repeat_anchor_not_hammered(monkeypatch):
    """渠道把窗口钳住时不重复打同一锚点（复审 nit）。"""
    calls = []

    def fake(fc, fn, tc, tn, anchor, logger, **kw):
        calls.append(anchor)
        # 无论锚点是什么，只返回同一段 → 永远覆盖不到超窗日期
        return _rows(10, first="2026-11-01")

    _patch(monkeypatch, fake)
    _TC._intl_win_cache = {}
    got, info = _TC._intl_window_prices(
        "SHA", "HKG", ["2027-03-05", "2027-04-05", "2027-05-05"])
    assert len(calls) == len(set(calls)), "同一锚点不得重复请求"
    assert got == {}


def test_monitor_mode_never_opens_browser_on_window_failure(monkeypatch):
    """窗历失败时定时面不得启浏览器（复审 #2：等于装回逐日 444）。"""
    _patch(monkeypatch, lambda *a, **k: None)   # 请求失败
    opened = []
    monkeypatch.setattr(
        TongchengCrawler, "_intl_browser_fallback",
        lambda self, *a, **k: opened.append(a) or [])
    _TC.probe_mode = False
    _TC.paths = []
    try:
        rows = _TC._fetch_intl("SHA", "HKG", ["2026-11-10"])
    finally:
        _TC.probe_mode = False
    assert rows == []
    assert opened == [], "定时面窗历失败=本轮到此为止，不启浏览器"
    assert any(p["path"] == "窗历" and p["status"] == "error"
               for p in _TC.paths)


def test_probe_mode_still_opens_browser_on_window_failure(monkeypatch):
    _patch(monkeypatch, lambda *a, **k: None)
    opened = []
    monkeypatch.setattr(
        TongchengCrawler, "_intl_browser_fallback",
        lambda self, *a, **k: opened.append(a) or [])
    _TC.probe_mode = True
    _TC.paths = []
    try:
        _TC._fetch_intl("SHA", "HKG", ["2026-11-10"])
    finally:
        _TC.probe_mode = False
    assert opened, "探针是人主动要明细，窗历失败仍可试浏览器"


# ---- 建议引擎：不得自己掩掉自己 ----

def test_advise_reports_degraded_window_calendar():
    """窗历 2/50 时不能被"同族有人在出数"掩掉（复审 #3）。"""
    from core.pacing import advise
    paths = {"窗历": {"attempts": 50, "ok": 2, "calendar_ok": 2,
                     "rate": 0.04, "rate_excl_empty": 0.04}}
    a = advise("tongcheng", {}, paths, now=None, node=_deg_node(paths))
    assert a["state"] == "path_degraded", a


def test_advise_reports_roundtrip_unsupported_forever(tmp_path):
    """「往返」只有 unsupported 时不该被判成待修的路（复审 #5）。

    用真实 path_stats 生成节点：unsupported 是渠道能力边界，必须从
    有效率分母里剔除（否则往返航线会被永久判劣化）。
    """
    from core.pacing import advise
    from core.storage import PriceStorage
    st = PriceStorage(str(tmp_path / "p.db"))
    for i in range(40):
        st.save_fetch_path("tongcheng", "SHA", "HKG", "2027-06-01", "往返",
                           "unsupported", note="本通路取不到往返价",
                           attempt_id="u%d" % i)
    node = st.path_stats(24)["tongcheng"]
    a = advise("tongcheng", {}, node.get("paths") or {}, node=node)
    assert a["state"] != "path_degraded", a
