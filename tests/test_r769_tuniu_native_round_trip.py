# -*- coding: utf-8 -*-
"""r769：途牛国内往返是**接口原生**的，必须真用两段 segment。

实测（2026-10-31，同一进程交替对照，勿再重查）：
  * `listFlight` 的 `segmentList` 放两段（去程 + 反向回程日）时，每条
    fare 价就是**往返总价**：209 个航班里 202 个精确满足
    B = A + L_ret（A=同航班单程价，L_ret=返程日反向航线最低价 400），
    B−A 的中位数恰好 400；没有一个航班满足 B ≈ A。
  * 响应里**不**回显返程日，所以判据只能是价差不变式，不能靠字段。
  * 站点自己的 m 站页面永远发「段1 有日 + 段2 空日」（170001 参数错误），
    所以「看页面怎么发」会得出「接口不支持」的错误结论——必须自己放
    真实回程日。

这条门禁钉住三件事：
  1. 往返请求真的带上了两段、第二段是**反向**且带真实回程日；
  2. 单程请求仍然是**一段**（没被往返逻辑污染）；
  3. 国际往返仍然显式 unsupported（它的 productList 是单段结构）。
"""
import json
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from crawlers.tuniu import TuniuCrawler


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
