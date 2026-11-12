# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1251_tuniu_budget.py
- tests/test_r282_tuniu_prate.py
- tests/test_r334_tuniu_intl.py
- tests/test_r763_tuniu_arrival_cross_day.py
- tests/test_r769_tuniu_native_round_trip.py
- tests/test_r927_tuniu_intl_round_trip.py
- tests/test_v15107_tuniu_degrade.py
- tests/test_v15122_tuniu_cabin.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import crawlers.tuniu as T
import crawlers.tuniu as tn
import json
import logging
import os
import pytest
import sys

from crawlers.tuniu import LIST_API, TuniuCrawler, _prate
from unittest import mock


# ---- merged from tests/test_r1251_tuniu_budget.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

class FakeClock:
    """可控时钟：每次 sleep 就前进固定秒数。"""

    def __init__(self, step=60.0):
        self.now = 1000.0
        self.step = step

    def time(self):
        return self.now

    def sleep(self, s):
        self.now += max(float(s or 0), self.step)


def _crawler(clock, attempts=5, budget=180.0):
    c = object.__new__(T.TuniuCrawler)
    c._fail_streak = 0
    c.max_attempts = attempts
    c.max_poll = 3
    c.rate_limit = False
    c.backoff_s = 1
    c._login_wall = False
    c.hoop_budget_s = budget
    c.logger = _Log()
    return c


class _Log:
    def __init__(self):
        self.warns = []

    def warning(self, fmt, *a):
        self.warns.append(fmt % a if a else fmt)

    def info(self, *a, **kw):
        pass


def test_budget_stops_the_grind(monkeypatch):
    clock = FakeClock(step=60.0)
    monkeypatch.setattr(T, "time", clock)
    c = _crawler(clock, attempts=10, budget=180.0)
    monkeypatch.setattr(c, "_one_attempt",
                        lambda *a, **kw: (False, None, False), raising=False)
    out = c._hoop("SHA", "NRT", "2026-11-20")
    assert out is None
    # 预算 180s、每圈推进 ≥60s → 最多 4 圈就该收手
    assert c._fail_streak == 1, c._fail_streak
    assert any("超过预算" in w for w in c.logger.warns), c.logger.warns


def test_success_within_budget_unchanged(monkeypatch):
    """负控：预算内成功时行为不变（照常返回结果、不记失败）。"""
    clock = FakeClock(step=10.0)
    monkeypatch.setattr(T, "time", clock)
    c = _crawler(clock, attempts=5, budget=180.0)
    monkeypatch.setattr(c, "_one_attempt",
                        lambda *a, **kw: (True, {"ok": 1}, False), raising=False)
    assert c._hoop("SHA", "NRT", "2026-11-20") == {"ok": 1}
    assert c._fail_streak == 0
    assert not c.logger.warns


def test_zero_budget_disables_the_cap(monkeypatch):
    """预算置 0 = 关闭（老行为），便于现场对比与回滚。"""
    clock = FakeClock(step=60.0)
    monkeypatch.setattr(T, "time", clock)
    c = _crawler(clock, attempts=2, budget=0)
    monkeypatch.setattr(c, "_one_attempt",
                        lambda *a, **kw: (False, None, False), raising=False)
    assert c._hoop("SHA", "NRT", "2026-11-20") is None
    # 关掉预算时应走到圈数上限（attempts=2）
    assert any("最大重试圈数" in w for w in c.logger.warns), c.logger.warns


# ---- merged from tests/test_r282_tuniu_prate.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_placeholder_new_tiers_empty():
    # 新占位档 50/56 置空（旧守卫只挡 20 时穿透入库）
    assert _prate("50") == ""
    assert _prate("56") == ""
    assert _prate("50%") == ""
    assert _prate("56.0") == ""


def test_legacy_placeholder_still_empty():
    assert _prate("20") == ""
    assert _prate("20.0") == ""
    assert _prate("") == ""
    assert _prate(None) == ""


def test_real_value_band_untouched():
    # 真值带不误杀：63 档（avgDelay 有分布）与健康带全保留
    for v in ("63", "73", "86", "90", "93", "96", "100"):
        assert _prate(v) == v, v


def test_offers_to_flights_drops_new_placeholder_key():
    # 生产构造基座（同 test_v15104_fields._TUINU_OFFER 形态——
    # 缺必需键的 offer 会被上游守卫整行丢弃，断言对空输出恒真）
    o = {"airline": "东航", "flight_no": "MU137",
         "depart_time": "14:40", "arrive_time": "19:10",
         "price": 1750, "dep_date": "2027-02-13",
         "arr_date": "2027-02-13", "flight_time": 270,
         "cabin": "经济舱", "layover": "", "stopPoints": [],
         "onTimeRate": "50"}
    fs = TuniuCrawler._offers_to_flights([o])
    assert fs and "prate" not in fs[0]


# ---- merged from tests/test_r334_tuniu_intl.py ----

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

_L = logging.getLogger("probe")


def _capture_hoop(monkeypatch, raw=None):
    captured = []

    def _fake(self, fc, tc, date):
        captured.append((fc, tc, date))
        return {} if raw is None else raw

    monkeypatch.setattr(TuniuCrawler, "_hoop_intl", _fake)
    return captured


def _stub_parse(monkeypatch):
    monkeypatch.setattr(TuniuCrawler, "_parse_offers_intl",
                        lambda self, data: [{"price": 1000.0}])
    monkeypatch.setattr(TuniuCrawler, "_sleep", lambda self: None)


def test_tuniu_intl_merges_airport_to_city_code(monkeypatch):
    """纯机场码航线（PVG-CDG 实录）请求链归并为城市码（SHA-PAR）。"""
    captured = _capture_hoop(monkeypatch)
    _stub_parse(monkeypatch)
    c = TuniuCrawler({}, _L)
    out = c._fetch_intl("PVG", "CDG", ["2026-11-16"])
    assert captured == [("SHA", "PAR", "2026-11-16")], captured
    # 落库保持配置原码（展示面/出链零变化）
    assert len(out) == 1
    assert out[0].from_city == "PVG"
    assert out[0].to_city == "CDG"


def test_tuniu_intl_city_code_passthrough(monkeypatch):
    """城市码/同名码航线零变形（SHA-BKK 恒等回退）——在产航线零回归
    面。"""
    captured = _capture_hoop(monkeypatch)
    _stub_parse(monkeypatch)
    c = TuniuCrawler({}, _L)
    c._fetch_intl("SHA", "BKK", ["2026-11-16"])
    assert captured == [("SHA", "BKK", "2026-11-16")], captured


# ---- merged from tests/test_r763_tuniu_arrival_cross_day.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _item(**kw):
    base = {"airline": "东航", "fn": "MU5100 327", "dep": "07:00",
            "depAir": "首都机场T2", "arr": "08:55", "arrAir": "浦东机场T1",
            "dur": "1h55m", "rate": "100%", "price": "￥552\n经济舱",
            "cross": "08:55", "rowText": "东航 MU5100"}
    base.update(kw)
    return base


def test_arrival_with_same_day_suffix_parses():
    """真实快照里的 `arr='12:20+0'` 必须能解析。"""
    rows = TuniuCrawler._parse_pc_items(
        [_item(arr="12:20+0", price="￥1080\n经济舱")], "2026-10-24")
    assert len(rows) == 1, "带 +0 的到达时刻仍被判废——PC 通路永远出不了数"
    assert rows[0]["arrTime"] == "12:20"
    assert rows[0]["price"] == 1080.0


def test_arrival_with_next_day_suffix_marks_cross_day():
    """`+1` 是次日到达，要落成跨天标记而不是被丢掉。"""
    rows = TuniuCrawler._parse_pc_items(
        [_item(arr="00:35+1")], "2026-10-24")
    assert len(rows) == 1
    assert rows[0]["arrTime"] == "00:35"
    assert rows[0].get("crossDayDesc") == "+1天"


@pytest.mark.parametrize("bad", ["", "abc", "+1", "12", "1:5", "25:00"])
def test_broken_arrival_is_still_rejected(bad):
    """负控：放宽后缀不能放宽到「含数字就收」。"""
    assert TuniuCrawler._parse_pc_items(
        [_item(arr=bad)], "2026-10-24") == []


def test_departure_time_keeps_strict_validation():
    """去程时刻没有跨天后缀语义，坏值必须拒。"""
    assert TuniuCrawler._parse_pc_items(
        [_item(dep="7:00")], "2026-10-24") == []
    assert TuniuCrawler._parse_pc_items(
        [_item(dep="")], "2026-10-24") == []


def test_parse_real_snapshot_shape_end_to_end():
    """用真实快照的原始字段组合（含 +0 与多行价签）跑一遍。"""
    items = [
        _item(fn="CZ1925 325(中)", dep="10:15", arr="12:20+0",
              price="￥1080\n经济舱"),
        _item(fn="SC5161 321", dep="15:30", arr="18:55+0",
              price="￥1750\n经济舱"),
    ]
    rows = TuniuCrawler._parse_pc_items(items, "2026-10-26")
    assert [r["code"] for r in rows] == ["CZ1925", "SC5161"]
    assert [r["price"] for r in rows] == [1080.0, 1750.0]


# ---- merged from tests/test_r769_tuniu_native_round_trip.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class _Cfg(dict):
    def get(self, k, d=None):
        return dict.get(self, k, d)


@pytest.fixture
def crawler():
    c = TuniuCrawler(_Cfg(), mock.MagicMock())
    c.config = _Cfg()
    c._sleep = lambda: None
    # 限速器与轮询间隔是真实 sleep（RATE_WINDOW=600s），门禁必须绕开，
    # 否则用例会被自己的礼貌预算挂住——这不是被测行为。
    c._rate_acquire = lambda: None
    c._rate_record = lambda: None
    c.rate_limit = False
    c.max_poll = 1
    c.max_attempts = 1
    return c


def _captured_segments(crawler, ret_date):
    """跑一轮 fetch，把真实发出去的 segmentList 抓下来。"""
    seen = {}

    class _Resp:
        text = json.dumps({"success": True, "data": {"fareList": []}})

    class _Client:
        cookies = mock.MagicMock()

        def get(self, url, params=None, headers=None, **kw):
            d = json.loads((params or {}).get("d") or "{}")
            seen["segments"] = d.get("segmentList")
            return _Resp()

        def close(self):
            pass

    crawler._saved_page_token = lambda *a, **k: "tok"
    crawler._saved_session_cookies = lambda: []
    crawler._install_tac_cookies = lambda *_a, **_k: None
    crawler._fetch_pc_dom = lambda *a, **k: {}
    crawler._dump_raw = lambda *a, **k: None
    with mock.patch("crawlers.tuniu._net.new_client", return_value=_Client()):
        crawler.fetch("上海", "北京", ["2026-11-27"], ret_date=ret_date)
    return seen.get("segments")


def test_round_trip_sends_two_segments_with_real_back_date(crawler):
    """往返必须发两段，第二段是把第一段倒过来 + 真实回程日。"""
    segs = _captured_segments(crawler, ret_date="2026-12-01")
    assert segs is not None, "往返请求没有发出去"
    assert len(segs) == 2, "往返只发了一段：服务端会按单程返回，单程价冒充总价"
    assert segs[0]["departDate"] == "2026-11-27"
    assert segs[1]["departDate"] == "2026-12-01", (
        "第二段没带真实返程日——站点自己发的就是空日，会 170001")
    assert segs[1]["dCityIataCode"] == segs[0]["aCityIataCode"]
    assert segs[1]["aCityIataCode"] == segs[0]["dCityIataCode"]


def test_one_way_still_sends_exactly_one_segment(crawler):
    """负控：单程不能被往返逻辑污染成两段。"""
    segs = _captured_segments(crawler, ret_date="")
    assert len(segs) == 1
    assert segs[0]["departDate"] == "2026-11-27"


def test_round_trip_marks_rows_as_rt_with_back_date(crawler):
    """往返行的 extra 要带 tripType=RT 与 backDate，否则下游看不出口径。

    用真实抓下来的 fareList（`tests/fixtures/tuniu_rt_sample.json`，
    2026-10-31 响应裁剪的单行样本）喂假 client。
    """
    import io as _io
    fx = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "tests", "fixtures",
        "tuniu_rt_sample.json")
    assert os.path.isfile(fx), "真实夹具缺失：%s" % fx
    fixture = json.load(_io.open(fx, encoding="utf-8")) or {}
    # 两张表都要：fareList 给价格，flightList 给日期/机场（r769 踩过：
    # 只存 fareList 时 dep_date 全空 → _offers_to_flights 产出 0 条，
    # 用例会误报成「往返没进 extra」）。
    data = {"fareList": fixture.get("fareList") or [],
            "flightList": fixture.get("flightList") or {}}

    class _Resp:
        text = json.dumps({"success": True, "data": data})

    class _Client:
        cookies = mock.MagicMock()

        def get(self, url, params=None, headers=None, **kw):
            return _Resp()

        def close(self):
            pass

    crawler._saved_page_token = lambda *a, **k: "tok"
    crawler._saved_session_cookies = lambda: []
    crawler._install_tac_cookies = lambda *_a, **_k: None
    crawler._fetch_pc_dom = lambda *a, **k: {}
    crawler._dump_raw = lambda *a, **k: None
    with mock.patch("crawlers.tuniu._net.new_client", return_value=_Client()):
        rows = crawler.fetch("SHA", "BJS", ["2026-11-27"],
                             ret_date="2026-12-01")
    assert rows, "往返没有产出"
    ex = json.loads(rows[0].extra or "[]")
    assert ex, "extra 为空——往返明细没进 extra"
    assert all(e.get("tripType") == "RT" for e in ex), ex[:2]
    assert all(e.get("backDate") == "2026-12-01" for e in ex), ex[:2]


def test_international_round_trip_dispatches_to_h5(crawler, monkeypatch):
    """国际往返改走 H5 queryFlight（r927），不再显式 unsupported；这里只
    守分流，不发网络请求。"""
    seen = {}

    def fake(from_city, to_city, dates, ret_date):
        seen["args"] = (from_city, to_city, dates, ret_date)
        return []

    monkeypatch.setattr(crawler, "_fetch_intl_rt", fake)
    rows = crawler.fetch("SHA", "NRT", ["2026-11-27"],
                         ret_date="2026-12-01")
    assert rows == []
    assert seen["args"] == ("SHA", "NRT", ["2026-11-27"], "2026-12-01")
    notes = [(p.get("path"), p.get("status")) for p in (crawler.paths or [])]
    assert ("TRIP", "unsupported") not in notes, notes


def test_caliber_note_records_the_price_identity():
    """注释里必须留下判据本身（B = A + L_ret），否则下次又会去读字段。"""
    import io
    src = io.open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "crawlers", "tuniu.py"), encoding="utf-8").read()
    assert "L_ret" in src, "丢了往返口径的判据说明（B = A + L_ret）"
    assert "202/209" in src or "202 个" in src, "丢了实测样本量"


# ---- merged from tests/test_r927_tuniu_intl_round_trip.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "tuniu_intl_rt.json")


def _payload():
    with open(FIX, encoding="utf-8") as f:
        return json.load(f)


def test_parser_uses_channel_total_not_sum():
    p = _payload()
    date, ret = "2026-11-05", "2026-11-08"
    rows = TuniuCrawler._parse_intl_rt_products(
        p["productList"], date, ret)
    assert len(rows) == 35
    best = min(rows, key=lambda r: r["price"])
    assert best["price"] == 3010.0
    assert best["basis"] == "product_round_trip_total"
    assert best["tripType"] == "RT" and best["backDate"] == ret
    assert best["intl"] is True and best["date"] == date
    assert best["depTime"] == "15:25"
    assert best["code"] and best["name"]
    from core.alerter import _flights_from_extra
    fl = _flights_from_extra(rows, date, "tuniu")
    assert len(fl) == len(rows)
    assert fl[0]["depTime"] and fl[0]["intl"] is True


def test_parser_rejects_missing_or_out_of_band_price():
    p = _payload()
    bad = dict(p["productList"][0])
    bad.pop("avgTotalPrice", None)
    assert TuniuCrawler._parse_intl_rt_products(
        [bad], "2026-11-05", "2026-11-08") == []
    bad2 = dict(p["productList"][0])
    bad2["avgTotalPrice"] = 1
    assert TuniuCrawler._parse_intl_rt_products(
        [bad2], "2026-11-05", "2026-11-08") == []


def test_intl_ret_date_dispatches_to_rt():
    c = TuniuCrawler({"headless": True}, logging.getLogger("r927"))
    seen = {}

    def fake(from_city, to_city, dates, ret_date):
        seen["args"] = (from_city, to_city, dates, ret_date)
        return []

    c._fetch_intl_rt = fake
    c.fetch("SHA", "NRT", ["2026-11-05"], ret_date="2026-11-08")
    assert seen["args"] == ("SHA", "NRT", ["2026-11-05"], "2026-11-08")


# ---- merged from tests/test_v15107_tuniu_degrade.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _fare_body(n: int, base: int = 2990) -> str:
    """n 条 fare 的 listFlight 响应（每条独立航班号/价格）。"""
    fares = []
    for i in range(n):
        fares.append({
            "flightOptions": [{"flightNos": f"MU9{i:3d}"}],
            "flightPriceList": [
                {"fareBreakdownList": [{"baseFare": base + i, "psgType": "ADT"}]}
            ],
        })
    # separators 紧凑形态=真实渠道报文形态（fixture 忠实 mimic 渠道）；
    # 判据走结构化 json 解析不依赖子串形态
    return json.dumps({"success": True, "data": {"fareList": fares}},
                      ensure_ascii=False, separators=(",", ":"))


class _Resp:
    def __init__(self, text: str):
        self.text = text

    def json(self):
        return json.loads(self.text)


class _Cookies:
    def __init__(self):
        self._d = {}

    def set(self, k, v, domain=None, path=None):
        self._d[k] = v

    def get(self, k, default=""):
        return self._d.get(k, default)


class _FakeClient:
    """脚本化响应：listFlight 每次调用按序弹出一条 body（耗尽即抛错，
    兼作「续询越界」的失败信号）；其余 URL 返回空体。"""

    def __init__(self, bodies):
        self._bodies = list(bodies)
        self.cookies = _Cookies()
        self.list_calls = 0

    def get(self, url, params=None, headers=None, timeout=None):
        if LIST_API in url:
            self.list_calls += 1
            return _Resp(self._bodies.pop(0))
        return _Resp("")

    def close(self):
        pass


def _run(monkeypatch, bodies):
    """挂 fake Client 与免等待，跑一次 _one_attempt。
    返回 (crawler, ok, raw, blocked, fake)。"""
    calls = {"n": 0}

    def _factory(*a, **kw):
        fake = _FakeClient(bodies)
        calls["fake"] = fake
        return fake

    monkeypatch.setattr(tn._net, "new_client", _factory)
    monkeypatch.setattr(tn.time, "sleep", lambda s: None)
    crawler = TuniuCrawler({"rate_limit": False, "tuniu_max_poll": 10},
                           logging.getLogger("t107"))
    ok, raw, blocked = crawler._one_attempt("SHA", "URC", "2026-10-08")
    return crawler, ok, raw, blocked, calls["fake"]


def test_full_first_poll_zero_extra_cost(monkeypatch):
    """健康轮（43 条）：首响即收，零额外请求（礼貌预算不回退）。"""
    _, ok, raw, _, fake = _run(monkeypatch, [_fare_body(43)])
    assert ok and raw is not None
    assert len(raw["data"]["fareList"]) == 43
    assert fake.list_calls == 1


def test_thin_then_full_accepts_full(monkeypatch):
    """薄样本（3 条）不早收：续询到全量（43 条）收全量。"""
    _, ok, raw, _, fake = _run(monkeypatch,
                               [_fare_body(3), _fare_body(43)])
    assert ok
    assert len(raw["data"]["fareList"]) == 43
    assert fake.list_calls == 2


def test_all_thin_bounded_best_so_far(monkeypatch):
    """全薄（真稀疏/持续降级）：薄响应最多连看 3 个，兜底返回条数最多
    的样本，且打「疑似降级样本」警告供观测记责任周期。"""
    rec = []

    def _crawler(monkeypatch, bodies):
        def _factory(*a, **kw):
            return _FakeClient(bodies)
        monkeypatch.setattr(tn._net, "new_client", _factory)
        monkeypatch.setattr(tn.time, "sleep", lambda s: None)
        lg = logging.getLogger("t107thin")
        monkeypatch.setattr(lg, "warning",
                            lambda m, *a: rec.append(m % a if a else m))
        return TuniuCrawler({"rate_limit": False, "tuniu_max_poll": 10}, lg)

    crawler = _crawler(monkeypatch, [_fare_body(3), _fare_body(1),
                                     _fare_body(2), _fare_body(1)])
    ok, raw, blocked = crawler._one_attempt("SHA", "URC", "2026-10-08")
    assert ok and raw is not None
    # best-so-far：3 条样本胜过后续 1/2 条
    assert len(raw["data"]["fareList"]) == 3
    assert any("疑似降级样本" in m for m in rec), rec
    # 有界性由 test_thin_bound_caps_polling 强钉（list_calls==_THIN_MAX）


def test_thin_bound_caps_polling(monkeypatch):
    """薄样本续询有界：脚本给 10 个薄响应，实际 LIST_API 恰好 3 次调用。"""
    box = {}

    def _factory(*a, **kw):
        fake = _FakeClient([_fare_body(3)] * 10)
        box["fake"] = fake
        return fake

    monkeypatch.setattr(tn._net, "new_client", _factory)
    monkeypatch.setattr(tn.time, "sleep", lambda s: None)
    crawler = TuniuCrawler({"rate_limit": False, "tuniu_max_poll": 10},
                           logging.getLogger("t107cap"))
    ok, raw, _ = crawler._one_attempt("SHA", "URC", "2026-10-08")
    assert ok and len(raw["data"]["fareList"]) == 3
    assert box["fake"].list_calls == tn._THIN_MAX


def test_legacy_price_without_farelist_still_accepted(monkeypatch):
    """历史形态（无 fareList、data.salePrice>0）保持首响即收。"""
    body = json.dumps({"success": True, "data": {"salePrice": 2990}},
                      separators=(",", ":"))
    _, ok, raw, _, fake = _run(monkeypatch, [body])
    assert ok and raw is not None
    assert fake.list_calls == 1


# ---- 门槛演进：8→20（恰卡 n=8 截断轮虚高 +6.8%~+47% 在案）→39
#（自然轮 DB 实证 16-38 非恒空，20-38 过闸段关死——过闸带
# 整体落入薄样本续询）----

def test_gap_band_goes_thin_continuation(monkeypatch):
    """n=19（旧门槛过闸带）不得首响即收：走薄样本续询，穷尽兜底并打警告。"""
    box = {}

    def _factory(*a, **kw):
        fake = _FakeClient([_fare_body(19, base=3280)] * 10)
        box["fake"] = fake
        return fake

    monkeypatch.setattr(tn._net, "new_client", _factory)
    monkeypatch.setattr(tn.time, "sleep", lambda s: None)
    lg = logging.getLogger("t108gap")
    warns = []
    monkeypatch.setattr(lg, "warning",
                        lambda m, *a: warns.append(m % a if a else m))
    crawler = TuniuCrawler({"rate_limit": False, "tuniu_max_poll": 10}, lg)
    ok, raw, _ = crawler._one_attempt("SHA", "URC", "2026-10-08")
    assert ok and raw is not None
    assert len(raw["data"]["fareList"]) == 19
    assert box["fake"].list_calls == tn._THIN_MAX
    assert any("疑似降级样本" in m for m in warns), warns


def test_new_floor_boundary_first_poll(monkeypatch):
    """n=20（前门槛值）翻案为薄续询：空档带实证非恒空后，
    20-38 段全带不早收（DB n=24 过闸形态在案）。"""
    _, ok, raw, _, fake = _run(monkeypatch,
                               [_fare_body(20), _fare_body(45)])
    assert ok
    assert len(raw["data"]["fareList"]) == 45
    assert fake.list_calls == 2


# ---- 自然轮 DB 实证推翻「空档恒空」：当日 4/102 轮 n 落 16-38
#（16/27/16/24，抽检 2 轮 min/max 在场、最低价与邻域持平——真稀疏
# 与良性截断并存，但门槛 20 下 20-38 段首响即收不续询）。门槛设计
# 文档自身的哲学是「让整个过闸带落入续询面」——floor 须取健康带
# 下缘 39：健康轮（39-46）零额外请求不回退，16-38 全带续询，
# best-so-far 兜底真稀疏零丢失 ----

def test_gap_band_20_38_first_poll_not_accepted(monkeypatch):
    """n=24（生产 13:12 实测形态）不得首响即收：续询到全量收全量。"""
    _, ok, raw, _, fake = _run(monkeypatch,
                               [_fare_body(24, base=3280),
                                _fare_body(45)])
    assert ok
    assert len(raw["data"]["fareList"]) == 45
    assert fake.list_calls == 2


def test_gap_band_all_sparse_bounded_best_so_far(monkeypatch):
    """n=27 持续（真稀疏形态）：薄样本续询 ≤3 拍兜底 best-so-far，
    零数据丢失（对账 DB 06:32 轮 min/max 在场的自然出勤）。"""
    _, ok, raw, _, fake = _run(
        monkeypatch, [_fare_body(27)] * 10)
    assert ok and raw is not None
    assert len(raw["data"]["fareList"]) == 27
    assert fake.list_calls == tn._THIN_MAX


def test_healthy_band_bottom_edge_first_poll(monkeypatch):
    """n=39（健康带下缘）首响即收：健康轮零额外请求不回退。"""
    _, ok, raw, _, fake = _run(monkeypatch, [_fare_body(39)])
    assert ok and raw is not None
    assert len(raw["data"]["fareList"]) == 39
    assert fake.list_calls == 1


def test_gap_band_upper_edge_goes_thin(monkeypatch):
    """n=38（健康带下缘之下）走薄样本续询：过闸带上缘关死。"""
    _, ok, raw, _, fake = _run(monkeypatch,
                               [_fare_body(38, base=3280),
                                _fare_body(45)])
    assert ok
    assert len(raw["data"]["fareList"]) == 45
    assert fake.list_calls == 2


# ---- merged from tests/test_v15122_tuniu_cabin.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_CT = TuniuCrawler

_FLIGHT_LIST = {
    "MU8370#2026-10-06#URC#SHA": {
        "airlineCompany": "东航",
        "departureTime": "20:20", "arrivalTime": "01:15",
        "departureDate": "2026-10-06", "arrivalDate": "2026-10-07",
        "flightTime": "295",
    },
}


def _policy(cabin, code, price, black=False, discount="6.7折"):
    pj = [{"priceFlightCabinList": [
        {"cabinTypeName": cabin, "cabinCode": code}]}] if cabin else []
    return {"supportBlack": black,
            "fareBreakdownList": [
                {"baseFare": price, "discount": discount, "psgType": "ADT"}],
            "priceJourneyCabinList": pj}


def _raw(*policies):
    fare = {"flightOptions": [{"flightNos": "MU8370"}],
            "flightPriceList": list(policies)}
    return {"data": {"fareList": [fare], "flightList": _FLIGHT_LIST}}


def _one(*policies):
    offers = _CT._parse_offers(_raw(*policies))
    assert len(offers) == 1
    return offers[0]


def test_cabin_follows_selected_policy_not_first():
    # 串舱复现（生产错配形态）：公务舱政策排前、经济舱政策价更低
    # → 行价 1500（经济舱），舱名必须随选中价政策落「经济舱」
    o = _one(_policy("公务舱", "J", 3000), _policy("经济舱", "Y", 1500))
    assert o["price"] == 1500
    assert o["cabin"] == "经济舱"


def test_cabin_business_when_selected():
    # 公务舱政策恰是最低价时：舱名公务舱（选中价配对的双向正确性）
    o = _one(_policy("经济舱", "Y", 2000), _policy("公务舱", "J", 1800))
    assert o["price"] == 1800
    assert o["cabin"] == "公务舱"
    assert o["bizPrice"] == 1800  # _biz_fare 独立遍历不受本修复影响


def test_cabin_code_within_selected_policy():
    # cabinCode 随选中价政策聚合：两政策各单码（J/Y），选中经济舱
    # → 落 Y（旧全列表聚合 J≠Y 恒空=出勤 35-59% 的根因）
    o = _one(_policy("公务舱", "J", 3000), _policy("经济舱", "Y", 1500))
    assert o["cabinCode"] == "Y"


def test_cabin_code_multi_in_selected_policy_stays_empty():
    # 选中价政策内仍多码：宁缺勿错守卫保持（单政策内不落）
    o = _one({"supportBlack": False,
              "fareBreakdownList": [
                  {"baseFare": 1500, "psgType": "ADT"}],
              "priceJourneyCabinList": [
                  {"priceFlightCabinList": [
                      {"cabinCode": "Y"}, {"cabinCode": "B"}]}]},
             _policy("公务舱", "J", 3000))
    assert o["price"] == 1500
    assert o["cabinCode"] == ""


def test_black_tie_normal_policy_wins_cabin():
    # 同价平手按普通政策算（标记零误报）：舱名随平手胜者（普通政策）
    o = _one(_policy("经济舱", "Y", 1000, black=True),
             _policy("经济舱", "M", 1000))
    assert o["price"] == 1000
    assert not o.get("blackCard")
    assert o["cabin"] == "经济舱"


def test_cabin_legacy_top_level_fallback_kept():
    # 09-18 旧顶层形态兼容回退保持：选中政策无舱名 → fare 顶层舱名
    fare = {"flightOptions": [{"flightNos": "MU8370"}],
            "flightPriceList": [
                {"fareBreakdownList": [{"baseFare": 3600,
                                        "psgType": "ADT"}]}],
            "priceJourneyCabinList": [
                {"priceFlightCabinList": [{"cabinTypeName": "经济舱"}]}]}
    offers = _CT._parse_offers(
        {"data": {"fareList": [fare], "flightList": _FLIGHT_LIST}})
    assert len(offers) == 1
    assert offers[0]["cabin"] == "经济舱"


def test_cabin_missing_returns_empty():
    # 两层都无舱名：宁缺勿错返回空（不借兄弟政策的舱名造数据）
    o = _one({"supportBlack": False,
              "fareBreakdownList": [{"baseFare": 1500, "psgType": "ADT"}]})
    assert o["price"] == 1500
    assert o["cabin"] == ""
    assert o["cabinCode"] == ""
