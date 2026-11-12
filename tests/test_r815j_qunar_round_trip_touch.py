# -*- coding: utf-8 -*-
"""r815j：去哪儿 touch 往返页接通（只采产品「往返总价」）。

真页面（2026-11-02 10:26，受信 profile）：
`touch.qunar.com/ncs/page/flightDoubleList?depCity=北京&arrCity=上海
&goDate=2026-11-03&backDate=2026-11-05` 去程卡直接写
「往返总价 / ¥808 起」（CZ8889 20:30→22:50 …）。
返程卡也写「往返总价」，但价格是「补 ¥172」——这是在已选去程上
加价，不是总价；只认 `¥N 起`，返程卡不入池。
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import crawlers.qunar as qunar_mod  # noqa: E402
from crawlers.qunar import QunarCrawler  # noqa: E402

_LOG = logging.getLogger("t_r815j")

SAMPLE = """去程
11-03
周二
北京-上海
价格最低
时间最早
20:30
北京大兴
2h20m
22:50
浦东T2
南航CZ8889
往返总价
¥808 起
21:35
北京大兴
2h5m
23:40
虹桥T2
上航FM9102
往返总价
¥841 起
09:00
北京大兴
2h10m
11:10
虹桥T2
南航CZ8879
往返总价
¥1504 起
18:15
虹桥T2
2h15m
20:30
北京大兴
中联航KN3039
共享
往返总价
补 ¥172
18:15
虹桥T2
2h15m
20:30
北京大兴
东航MU122
共享
往返总价
补 ¥172
"""


class _Page:
    def __init__(self, body, url=""):
        self._body = body
        self.url = url
        self.gotos = []

    def goto(self, url, **_k):
        self.gotos.append(url)
        self.url = url

    def inner_text(self, *_a, **_k):
        return self._body

    def wait_for_timeout(self, *_a, **_k):
        return None

    def close(self):
        return None

    class _Mouse:
        def wheel(self, *_a, **_k):
            return None

    mouse = _Mouse()


class _Ctx:
    def __init__(self, page):
        self.page = page

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def new_page(self, *_a, **_k):
        return self.page


def _crawler():
    c = QunarCrawler({"user_data_dir": "user_data"}, _LOG)
    c._debug_snapshot = lambda *_a, **_k: None
    QunarCrawler.login_suspect = False
    return c


def _wire(monkeypatch, c, page):
    monkeypatch.setattr(c, "browser", lambda *_a, **_k: _Ctx(page))
    monkeypatch.setattr(c, "new_page", lambda *_a, **_k: page)
    monkeypatch.setattr(qunar_mod.time, "sleep", lambda *_a, **_k: None)


def test_parse_rt_body_uses_departure_total_only():
    rows = QunarCrawler._parse_rt_body(SAMPLE, "2026-11-03", "2026-11-05")
    assert len(rows) == 3, rows
    assert [r["price"] for r in rows] == [808.0, 841.0, 1504.0]
    first = rows[0]
    assert first["airline"] == "南航" and first["flight"] == "CZ8889"
    assert (first["dep"], first["arr"]) == ("20:30", "22:50")
    assert first["depAirport"] == "北京大兴"
    assert first["arrAirport"] == "浦东T2"
    assert first["priceLabel"] == "往返总价"
    assert first["basis"] == "product_round_trip_total"
    assert first["tripType"] == "RT" and first["backDate"] == "2026-11-05"
    # 返程卡的「补 ¥172」不是总价，一条都不能混进来
    assert all(r["price"] != 172.0 for r in rows)


def test_parse_rt_body_tolerates_blank_lines_in_inner_text():
    # 真实 innerText 每行之间有空行；机场必须取「下一非空行」。
    rows = QunarCrawler._parse_rt_body(
        SAMPLE.replace("\n", "\n\n"), "2026-11-03", "2026-11-05")
    assert len(rows) == 3
    assert rows[0]["depAirport"] == "北京大兴"
    assert rows[0]["arrAirport"] == "浦东T2"


def test_parse_rt_body_requires_label_before_price():
    body = "\n".join(["09:00", "北京大兴", "2h", "11:00", "虹桥T2",
                      "南航CZ8879", "¥1504 起"])
    assert QunarCrawler._parse_rt_body(body, "2026-11-03",
                                       "2026-11-05") == []
    body2 = "\n".join(["南航CZ8879", "往返总价", "¥1504 起"])
    assert QunarCrawler._parse_rt_body(body2, "2026-11-03",
                                       "2026-11-05") == []


def test_rt_url_is_touch_round_trip():
    url = QunarCrawler.RT_URL_TPL.format(
        from_name="%E5%8C%97%E4%BA%AC", to_name="%E4%B8%8A%E6%B5%B7",
        date="2026-11-03", ret_date="2026-11-05")
    assert "touch.qunar.com/ncs/page/flightDoubleList" in url
    assert "goDate=2026-11-03" in url and "backDate=2026-11-05" in url


def test_fetch_ret_date_routes_domestic_to_touch_rt(monkeypatch):
    c = _crawler()
    seen = {}

    def fake_rt(frm, to, dates, ret):
        seen["args"] = (frm, to, list(dates), ret)
        return []

    monkeypatch.setattr(c, "_fetch_rt", fake_rt)
    monkeypatch.setattr(c, "_fetch_intl", lambda *_a, **_k: (_ for _ in ()).throw(
        AssertionError("国内往返不得走国际单程通路")))
    assert c.fetch("BJS", "SHA", ["2026-11-03"],
                   ret_date="2026-11-05") == []
    assert seen["args"] == ("BJS", "SHA", ["2026-11-03"], "2026-11-05")


def test_fetch_intl_ret_date_is_explicitly_unsupported(monkeypatch):
    c = _crawler()
    called = []
    monkeypatch.setattr(c, "_fetch_rt", lambda *_a, **_k: called.append(1) or [])
    assert c.fetch("SHA", "TYO", ["2026-11-03"],
                   ret_date="2026-11-05") == []
    assert called == [], "国际往返未验证，不得调用国内往返页"
    notes = [p for p in c.paths if p["path"] == "TRIP"]
    assert notes and notes[0]["status"] == "unsupported", c.paths
    assert "国际往返" in notes[0]["detail"]


def test_fetch_rt_returns_product_total_and_ok_path(monkeypatch):
    c = _crawler()
    page = _Page(SAMPLE)
    _wire(monkeypatch, c, page)
    out = c._fetch_rt("BJS", "SHA", ["2026-11-03"], "2026-11-05")
    assert len(out) == 1
    fp = out[0]
    assert fp.price == 808.0
    assert fp.flight_no == "CZ8889"
    rows = json.loads(fp.extra)
    assert len(rows) == 3 and rows[0]["basis"] == "product_round_trip_total"
    notes = [p for p in c.paths if p["path"] == "往返"]
    assert notes and notes[0]["status"] == "ok", c.paths
    assert notes[0]["rows"] == 3
    assert any("flightDoubleList" in u and "goDate=2026-11-03" in u
               for u in page.gotos), page.gotos


def test_fetch_rt_no_price_is_error_not_empty(monkeypatch):
    c = _crawler()
    _wire(monkeypatch, c, _Page("<html>页面改版</html>"))
    assert c._fetch_rt("BJS", "SHA", ["2026-11-03"], "2026-11-05") == []
    notes = [p for p in c.paths if p["path"] == "往返"]
    assert notes and notes[0]["status"] == "error", c.paths


def test_fetch_rt_explicit_no_flight_is_empty(monkeypatch):
    c = _crawler()
    _wire(monkeypatch, c, _Page("没有符合条件的航班，请更换日期"))
    assert c._fetch_rt("BJS", "SHA", ["2026-11-03"], "2026-11-05") == []
    notes = [p for p in c.paths if p["path"] == "往返"]
    assert notes and notes[0]["status"] == "empty", c.paths
    assert notes[0]["detail"] == "站点明确无可售往返"


def test_fetch_rt_captcha_is_blocked(monkeypatch):
    c = _crawler()
    _wire(monkeypatch, c, _Page("请完成滑块验证"))
    assert c._fetch_rt("BJS", "SHA", ["2026-11-03"], "2026-11-05") == []
    notes = [p for p in c.paths if p["path"] == "往返"]
    assert notes and notes[0]["status"] == "blocked", c.paths
