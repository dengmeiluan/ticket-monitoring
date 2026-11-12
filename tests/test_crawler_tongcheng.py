# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1577_tongcheng_train_tab.py
- tests/test_r1711_tc_on_form_guard.py
- tests/test_r280_tc_prate.py
- tests/test_r384_tongcheng_window.py
- tests/test_r399_tc_city_level.py
- tests/test_r737_tongcheng_round_trip_honesty.py
- tests/test_r815h_tongcheng_round_trip_api.py
- tests/test_v289_tongcheng_intl_h5.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import crawlers.tongcheng as _tc_mod
import datetime as _dt
import httpx
import io
import json
import logging
import os
import pytest
import sys

from crawlers.app_tongcheng import _TRAIN_MARKERS, _flight_tab_node, is_train_page
from crawlers.app_tongcheng_parse import is_form
from crawlers.tongcheng import TongchengCrawler


# ---- merged from tests/test_r1577_tongcheng_train_tab.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "tongcheng_train_page.xml")


def _fixture():
    return io.open(FIX, encoding="utf-8", errors="replace").read()


def test_train_page_is_recognised():
    xml = _fixture()
    assert is_train_page(xml) is True, "火车票页没被认出来——城市位会一直找错"
    assert is_form(xml) is False, "火车票页被当成机票表单：城市/日期会读到火车票的"


def test_flight_tab_node_is_the_topmost():
    node = _flight_tab_node(_fixture())
    assert node is not None, "火车票页里找不到「机票」tab，没法切回去"
    # tab 在顶部；同屏没有比它更靠上的「机票」候选
    assert node["cy"] < 1200, "取到的「机票」节点不在顶部区域：%s" % node


def test_plain_text_is_not_train_page():
    assert is_train_page("<hierarchy></hierarchy>") is False
    assert is_train_page('<node text="机票查询"/>') is False, \
        "有机票查询就不算火车票页"


# ---- merged from tests/test_r1711_tc_on_form_guard.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIN = os.path.join(ROOT, "tests", "fixtures", "tongcheng_train_page.xml")


def test_guard_helper_exists():
    src = io.open(os.path.join(ROOT, "crawlers", "app_tongcheng.py"),
                  encoding="utf-8").read()
    assert "def _on_flight_form(" in src, "没有「还在机票表单」的守卫"
    assert src.count("self._on_flight_form(dev,") >= 2, \
        "守卫没有接进 _set_city 与 _pick_round_trip_dates"
    assert "本次提前结束" in src, "提前结束时没有写明原因"


def test_train_fixture_is_not_a_flight_form():
    xml = io.open(TRAIN, encoding="utf-8", errors="replace").read()
    assert is_form(xml) is False
    assert is_train_page(xml) is True
    assert _TRAIN_MARKERS, "火车票判据丢了"


# ---- merged from tests/test_r280_tc_prate.py ----

def _mk_xhr(prate_td: str) -> str:
    data = {"ec": 0, "d": "HAK", "a": "SHA", "dd": "2027-02-14",
            "fl": [{"fn": "SC2168", "asn": "SC",
                    "dt": "2027-02-14 19:05", "at": "2027-02-14 22:45",
                    "lps": [{"atp": 1750, "brs": [{"al": -1}]}],
                    "sts": [{"tt": 1, "td": prate_td},
                            {"tt": 4, "td": "无餐食"}]}]}
    # 响应包装层与生产同形（解析器取 obj["data"]，缺包装=恒零行）
    return json.dumps({"success": True, "data": data},
                      ensure_ascii=False)


def test_placeholder_50_never_lands():
    """恒档「到达准点率50%」不得落库（tuniu 恒 20 同律）。"""
    rows = TongchengCrawler._extract_flights(_mk_xhr("到达准点率50%"))
    assert rows, "回放零行=样本形态错位"
    assert all(r.get("prate") != "50" for r in rows), \
        f"恒档占位 50 落库: {set(r.get('prate') for r in rows)}"


def test_real_value_kept():
    """真实值域（多值时代的 97）照常入库——守卫不误杀真值。"""
    rows = TongchengCrawler._extract_flights(_mk_xhr("到达准点率97%"))
    assert rows and any(r.get("prate") == "97" for r in rows)


def test_placeholder_isolation_from_meal():
    """同 sts 内其余字段（tt=4 餐食）不受守卫牵连。"""
    rows = TongchengCrawler._extract_flights(_mk_xhr("到达准点率50%"))
    assert rows and all(r.get("meal") == "无餐食" for r in rows)


# ---- merged from tests/test_r384_tongcheng_window.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t_r384_tc")
_TC = TongchengCrawler({}, _LOG)
# r1063 T257：冻结"今天"到本文件假设的那天（`_rows` 起点 2026-10-28）。
# 窗历窗口相对今天计算，硬编码日期否则会**跨天变红**（2026-11-10 那天 14 条全红）。
TongchengCrawler._today_override = "2026-10-28"

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
    # r1063 T257：用**冻结的今天**算昨天（否则与 _today_override 打架：
    # 11-09 会变成"未来"，被当成有价返回）。
    _t0 = TongchengCrawler._today_override or date.today().isoformat()
    y = (date.fromisoformat(_t0) - timedelta(days=1)).isoformat()
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


# ---- merged from tests/test_r399_tc_city_level.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _row(fc, tc, from_city, to_city):
    c = TongchengCrawler({}, logging.getLogger("t_r399"))
    r = c._intl_window_row(from_city, to_city, fc, tc, "2026-11-16", 1000.0)
    return r, json.loads(r.extra)[0]


def test_multi_airport_city_is_marked_city_level():
    """NRT 订票但查的是 TYO → 必须标城市级。"""
    r, e = _row("SHA", "TYO", "SHA", "NRT")
    assert r.to_city == "NRT", "行仍按配置的机场码存"
    assert e["cityLevel"] is True, e
    assert e["cityCodes"] == "SHA-TYO", e


def test_london_marked_city_level():
    r, e = _row("SHA", "LON", "SHA", "LHR")
    assert e["cityLevel"] is True, e


def test_single_airport_city_not_marked():
    """BKK 这种城市即机场的不该被误标成城市级。"""
    r, e = _row("SHA", "BKK", "SHA", "BKK")
    assert e["cityLevel"] is False, e


def test_source_still_traceable():
    """标注不应破坏原有溯源字段。"""
    r, e = _row("SHA", "TYO", "SHA", "NRT")
    assert e["source"] == "tc_window_calendar"
    assert e["price"] == 1000.0
    assert e["depTime"] == "" and e["arrTime"] == ""


# ---- merged from tests/test_r737_tongcheng_round_trip_honesty.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _src():
    return io.open(os.path.join(ROOT, "crawlers", "tongcheng.py"),
                   encoding="utf-8").read()


def _fetch_body():
    src = _src()
    i = src.index("    def fetch(self")
    j = src.find("\n    def ", i + 10)
    return src[i:j if j > 0 else len(src)]


def test_domestic_round_trip_routes_to_api_before_the_list_loop():
    body = _fetch_body()
    i_rt = body.find("self._fetch_dom_rt(")
    # 国内主路径以 `with self.browser()` 开单程列表
    i_loop = body.find("with self.browser()")
    assert i_rt > 0, "fetch 里没有国内往返的接口分流"
    assert i_loop > 0, "找不到国内单程列表段"
    assert i_rt < i_loop, (
        "国内往返分流出现在单程列表之后——单程价已经先算出来了")


def test_domestic_round_trip_does_not_open_oneway_browser():
    """行为：国内传 ret_date → 只调 _fetch_dom_rt，不启单程浏览器。"""
    import logging
    from crawlers.tongcheng import TongchengCrawler

    inst = TongchengCrawler({"user_data_dir": "user_data"},
                            logging.getLogger("t"))
    opened, seen = [], {}

    class _NoBrowser:
        def __enter__(self):
            opened.append(1)
            raise AssertionError("不该启浏览器跑单程")

        def __exit__(self, *a):
            return False

    inst.browser = lambda *a, **k: _NoBrowser()   # type: ignore

    def fake_rt(frm, to, dates, ret):
        seen["args"] = (frm, to, list(dates), ret)
        return []

    inst._fetch_dom_rt = fake_rt  # type: ignore
    rows = inst.fetch("SHA", "BJS", ["2026-11-20"], ret_date="2026-11-24")
    assert rows == [], rows
    assert opened == [], "国内往返仍然启动了单程浏览器"
    assert seen["args"] == ("SHA", "BJS", ["2026-11-20"], "2026-11-24")


def test_oneway_still_goes_to_the_list_page():
    """负控：不传 ret_date 时照常走单程列表（别把单程也拦掉）。

    r805 起同程国内有**两条**通路（PC 的 getflightlist + H5 的 book1），
    所以一次单程可能开不止一个上下文：PC 先跑、挂了再回落 H5 是设计
    行为，不是「被误拦」。本判据要的仍是原来那件事——**单程没有被往返
    闸门拦死**，即至少走到过一次列表页。
    """
    import logging
    from crawlers.tongcheng import TongchengCrawler

    inst = TongchengCrawler({"user_data_dir": "user_data"},
                            logging.getLogger("t"))
    opened = []

    class _B:
        def __enter__(self):
            opened.append(1)
            raise RuntimeError("到此为止")

        def __exit__(self, *a):
            return False

    inst.browser = lambda *a, **k: _B()      # type: ignore
    try:
        inst.fetch("SHA", "BJS", ["2026-11-20"])
    except RuntimeError:
        pass
    assert opened, "单程没有走到列表页（被误拦）"
    # 也不能无限重试：两条通路各一次是上限
    assert len(opened) <= 2, "单程开了 %d 次上下文，通路重试失控" % len(opened)
    # 更关键的：不许记成 unsupported（那是往返专用状态）
    assert not [p for p in (inst.paths or [])
                if p.get("status") == "unsupported"], (
        "单程被记成了 unsupported：%s" % (inst.paths,))


# ---- merged from tests/test_r815h_tongcheng_round_trip_api.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _payload(atp=1055, atpd=113, lp=942, fn="CA1835"):
    return {"success": True, "data": {
        "lp": lp,
        "fps": [{
            "fn": fn, "dt": "2026-11-06 07:55",
            "at": "2026-11-06 10:15", "asn": "国航",
            "atp": atp, "atpd": atpd,
        }],
    }}


def _crawler():
    return TongchengCrawler(
        {"user_data_dir": "user_data", "android": {"enabled": True}},
        logging.getLogger("t"))


def test_parse_uses_product_atp_not_sum():
    """接口 atp 就是产品总价；即使 atp 与 lp+atpd 不等也照用 atp。"""
    rows = TongchengCrawler._parse_rt_fps(
        _payload(atp=9999, atpd=113, lp=942)["data"]["fps"], 942,
        "2026-11-03", "2026-11-06")
    assert len(rows) == 1
    assert rows[0]["price"] == 9999.0
    assert rows[0]["return_price"] == 113.0
    assert rows[0]["trip_type"] == "RT"
    assert rows[0]["back_date"] == "2026-11-06"


def test_parse_skips_invalid_or_nonpositive():
    rows = TongchengCrawler._parse_rt_fps(
        [{"atp": 0, "atpd": 1}, {"atp": "x", "atpd": 1},
         {"atp": 1055, "atpd": 0, "fn": "MU5138"}],
        942, "2026-11-03", "2026-11-06")
    assert [r["price"] for r in rows] == [1055.0]


def test_fetch_dom_rt_returns_product_total(monkeypatch):
    class R:
        status_code = 200

        def json(self):
            return _payload()

    monkeypatch.setattr(httpx, "post", lambda *a, **k: R())
    c = _crawler()
    rows = c.fetch("SHA", "BJS", ["2026-11-03"], ret_date="2026-11-06")
    assert len(rows) == 1
    f = rows[0]
    assert f.price == 1055.0
    ex = json.loads(f.extra)
    assert ex["tripType"] == "RT"
    assert ex["backDate"] == "2026-11-06"
    assert ex["outboundLowest"] == 942.0
    assert ex["flight"] == "CA1835"
    assert f.flight_no == "CA1835"
    assert f.depart_time == "07:55" and f.arrive_time == "10:15"
    assert any(p.get("path") == "往返" and p.get("status") == "ok"
               for p in c.paths), c.paths


def test_fetch_ret_date_dispatch_intl_vs_domestic(monkeypatch):
    """ret_date 分支只接管国内；国际仍走 _fetch_intl（不被国内接口劫持）。"""
    c = _crawler()
    seen = {}

    def dom(*a, **k):
        seen["dom"] = (a, k)
        return []

    def intl(*a, **k):
        seen["intl"] = (a, k)
        return []

    monkeypatch.setattr(c, "_fetch_dom_rt", dom)
    monkeypatch.setattr(c, "_fetch_intl", intl)
    c.fetch("SHA", "BJS", ["2026-11-03"], ret_date="2026-11-06")
    assert "dom" in seen, "国内 ret_date 没走 roundtrips 分支"
    c.fetch("SHA", "BKK", ["2026-11-16"], ret_date="2026-11-20")
    assert "intl" in seen, "国际 ret_date 被国内分支劫持"
    assert seen["intl"][1].get("ret_date") == "2026-11-20"


def test_fetch_dom_rt_http_error_is_error(monkeypatch):
    class R:
        status_code = 502

        def json(self):
            return {}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: R())
    c = _crawler()
    rows = c.fetch("SHA", "BJS", ["2026-11-03"], ret_date="2026-11-06")
    assert rows == []
    assert any(p.get("path") == "往返" and p.get("status") == "error"
               for p in c.paths), c.paths


def test_fetch_dom_rt_empty_has_reason(monkeypatch):
    class R:
        status_code = 200

        def json(self):
            return {"success": True, "data": {"lp": 942, "fps": []}}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: R())
    c = _crawler()
    rows = c.fetch("SHA", "BJS", ["2026-11-03"], ret_date="2026-11-06")
    assert rows == []
    p = [x for x in c.paths if x.get("path") == "往返"][0]
    assert p["status"] == "empty" and "返程" in p["detail"], p


# ---- merged from tests/test_v289_tongcheng_intl_h5.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _card(**kw):
    base = {
        "dep": "08:05", "arr": "11:20", "depAp": "浦东T2",
        "arrAp": "关西T2", "dur": "2时15分", "price": "1418",
        "tickets": "余3张", "airline": "春秋航空", "code": "9C6575",
        "aircraft": "空客A321(中)", "transfer": False, "via": "",
        "share": False,
    }
    base.update(kw)
    return base


def test_intl_h5_url_contract():
    url = TongchengCrawler._intl_h5_url(
        "SHA", "OSA", "2026-10-25", "上海", "大阪")
    assert url.startswith("https://m.ly.com/tiflight/book1.html?")
    for part in ("tt=0", "dc=SHA", "ac=OSA", "dt=2026-10-25",
                 "rt=1900-01-01", "cabin=Y|S|C|F"):
        assert part in url, part
    assert "%E4%B8%8A%E6%B5%B7" in url
    assert "%E5%A4%A7%E9%98%AA" in url


def test_cards_parse_real_fields():
    rows = TongchengCrawler._parse_intl_cards(
        [_card()], "2026-10-25")
    assert len(rows) == 1
    f = rows[0]
    assert f["code"] == "9C6575"
    assert f["name"] == "春秋航空"
    assert f["price"] == 1418.0
    assert f["depTime"] == "08:05" and f["arrTime"] == "11:20"
    assert f["depAirport"] == "浦东T2"
    assert f["arrAirport"] == "关西T2"
    assert f["duration"] == 135
    assert f["seats"] == "3"
    assert f["source"] == "ts_h5" and f["intl"] == 1
    # 无中转证据不得落 transfer=0 冒充直飞
    assert "transfer" not in f


def test_cards_overnight_and_transfer_evidence():
    rows = TongchengCrawler._parse_intl_cards(
        [_card(code="NX117", dep="16:50", arr="12:45",
               dur="18时55分", price="1887", transfer=True,
               via="澳门", airline="澳门航空")], "2026-10-25")
    f = rows[0]
    assert f["arrDate"] == "2026-10-26"
    assert f["transfer"] == 1
    assert f["transCity"] == "澳门"


def test_cards_dedup_keep_lowest_and_drop_invalid():
    rows = TongchengCrawler._parse_intl_cards([
        _card(price="1500"),
        _card(price="1418"),
        _card(code=""),                    # 缺航班号
        _card(dep=""),                     # 缺时刻
        _card(price=""),                   # 缺价
        _card(price="999999"),             # 越价格上界
    ], "2026-10-25")
    assert len(rows) == 1
    assert rows[0]["price"] == 1418.0


def test_probe_only_visible_window_and_dom_selector():
    src = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "crawlers", "tongcheng.py"), encoding="utf-8").read()
    assert "headless=(False if self.probe_mode else None)" in src
    assert "#flightBoxId .flight-list'" in src
    assert ".flight-list .flight-main.mb-12" not in src
    assert ".airplane-box > span" in src
    assert "[class*=trans-style]" in src

    ts = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "crawlers", "tuniu.py"), encoding="utf-8").read()
    # 2026-11-02：PC 只查近 30 天；可见窗口重试只针对 PC 实际查过的日期。
    assert 'if _pc_missing and getattr(self, "probe_mode", False):' in ts
    # 已保存会话读取不得引用未定义 headless（NameError 曾使 httpx
    # 匿名请求丢登录 cookie，接口恒 710114）
    _cookie_seg = ts.split("def _saved_session_cookies", 1)[1].split(
        "def ", 1)[0]
    assert "self.browser(headless=headless)" not in _cookie_seg
    assert "self.browser(headless=True)" in _cookie_seg
