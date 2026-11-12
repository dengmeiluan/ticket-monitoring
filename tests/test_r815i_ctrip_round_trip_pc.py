# -*- coding: utf-8 -*-
"""r815i：携程 PC 往返列表接通（只采「往返含税价」产品总价）。

真机证据（2026-11-02，受信 profile）：
`flights.ctrip.com/online/list/round-sha-tyo?depdate=2026-11-19_2026-11-22
&cabin=y_s&adult=1&child=0&infant=0&containstax=1` 直出 6 张卡：
航司 / 航班号+机型 / 起降时刻 / 机场 / 「¥N起」/「往返含税价」/「选为去程」。
价格是渠道自己的往返含税总价（GK036 ¥2404 … 乐桃 ¥2682），
**不是**两段单程相加；顶部「更多日期」条带的 `¥2404低` 是单程日价，
不能混进往返池。
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.ctrip import CtripCrawler  # noqa: E402

_LOG = logging.getLogger("t_r815i")

SAMPLE = """
携程旅行网
自由搭配往返组合
11-19周四去
11-22周日返
¥2404低
1选择去程上海东京11-19 周四2选择返程东京上海11-22 周日
直飞
直飞优先低价优先起飞时间早-晚耗时短优先更多排序
司比价低价提醒
捷星日本
GK036 空客320(中)
02:20
浦东国际机场T2
06:20
成田国际机场T3
3小时航班详情
¥2404起
往返含税价
选为去程
春秋航空日本
IJ004 波音737(中)
17:30
浦东国际机场T2
21:30
成田国际机场T3
3小时航班详情
¥2451起
往返含税价
选为去程
日本乐桃航空
01:10
浦东国际机场T2
04:40
羽田机场T3
2小时30分航班详情
¥2682起
往返含税价
选为去程
"""


class _Page:
    def __init__(self, body, url=""):
        self._body = body
        self.url = url
        self.closed = False
        self.gotos = []

    def goto(self, url, **_k):
        self.gotos.append(url)
        self.url = url

    def set_default_timeout(self, *_a, **_k):
        return None

    def inner_text(self, *_a, **_k):
        return self._body

    def wait_for_timeout(self, *_a, **_k):
        return None

    def close(self):
        self.closed = True


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
    c = CtripCrawler({}, _LOG)
    c._debug_snapshot = lambda *_a, **_k: None
    CtripCrawler.login_suspect = False
    return c


def _wire(monkeypatch, c, page):
    # 绕过 BaseCrawler.new_page 的超时/响应钩子：这里只验正文解析
    # 与落账，不测 Playwright 页面对象本身。
    monkeypatch.setattr(c, "browser", lambda *_a, **_k: _Ctx(page))
    monkeypatch.setattr(c, "new_page", lambda *_a, **_k: page)


def test_parse_rt_body_uses_product_total_only():
    rows = CtripCrawler._parse_rt_body(SAMPLE, "2026-11-19", "2026-11-22")
    assert len(rows) == 3, rows
    by_no = {r["flight"]: r for r in rows}
    assert by_no["GK036"]["price"] == 2404.0
    assert by_no["IJ004"]["price"] == 2451.0
    assert by_no[""]["price"] == 2682.0  # 乐桃那行页面没给航班号，不臆造
    gk = by_no["GK036"]
    assert (gk["dep"], gk["arr"]) == ("02:20", "06:20")
    assert gk["depAirport"] == "浦东国际机场T2"
    assert gk["arrAirport"] == "成田国际机场T3"
    assert gk["airline"] == "捷星日本"
    assert gk["basis"] == "product_round_trip_tax"
    assert gk["tripType"] == "RT" and gk["backDate"] == "2026-11-22"
    assert gk["depDate"] == "2026-11-19"
    # 顶部条带 ¥2404低 不是价锚，不能被当成卡片
    assert all("低" not in str(r.get("price")) for r in rows)


DOM_SAMPLE = """
11-03周二去
11-06周五返
¥1002低
1选择去程上海北京11-03 周二2选择返程北京上海11-06 周五
东方航空
MU5195\xa0空客321(中)
19:55
浦东国际机场T1
22:15
大兴国际机场
3小时20分航班详情
¥1002起
往返总价
选为去程
新海航｜海南航空
HU7610 空客330(大)
20:55
虹桥国际机场T2
23:15
首都国际机场T2
3小时20分航班详情
¥1020起
往返总价
选为去程
"""


def test_parse_rt_body_domestic_total_label():
    """国内页标签是「往返总价」而非「往返含税价」（实测两棵真页面）。"""
    rows = CtripCrawler._parse_rt_body(DOM_SAMPLE, "2026-11-03",
                                       "2026-11-06")
    assert len(rows) == 2, rows
    assert [r["price"] for r in rows] == [1002.0, 1020.0]
    assert rows[0]["flight"] == "MU5195"
    assert rows[0]["priceLabel"] == "往返总价"
    assert rows[0]["basis"] == "product_round_trip_total"
    assert rows[0]["backDate"] == "2026-11-06"


def test_parse_rt_body_requires_round_trip_tax_anchor():
    body = "\n".join([
        "捷星日本", "GK036 空客320(中)", "02:20", "浦东国际机场T2",
        "06:20", "成田国际机场T3", "3小时航班详情", "¥2404起",
        "选为去程",  # 单程卡：没有「往返含税价」
    ])
    assert CtripCrawler._parse_rt_body(body, "2026-11-19", "2026-11-22") == []


def test_parse_rt_body_skips_card_without_times():
    body = "\n".join(["捷星日本", "GK036 空客320(中)", "¥2404起",
                      "往返含税价", "选为去程"])
    assert CtripCrawler._parse_rt_body(body, "2026-11-19", "2026-11-22") == []
    assert CtripCrawler._parse_rt_body("", "2026-11-19", "2026-11-22") == []


def test_rt_url_is_round_trip_with_containstax():
    url = CtripCrawler.URL_RT_PC.format(
        from_city="sha", to_city="tyo", date="2026-11-19",
        ret_date="2026-11-22")
    assert "/round-sha-tyo?" in url
    assert "depdate=2026-11-19_2026-11-22" in url
    assert "containstax=1" in url


def test_fetch_rt_returns_product_total_and_ok_path(monkeypatch):
    c = _crawler()
    page = _Page(SAMPLE, url="https://flights.ctrip.com/online/list/round-sha-tyo")
    _wire(monkeypatch, c, page)
    out = c._fetch_rt("SHA", "TYO", ["2026-11-19"], "2026-11-22")
    assert len(out) == 1
    fp = out[0]
    assert fp.platform == "ctrip"
    assert fp.depart_date == "2026-11-19"
    assert fp.price == 2404.0  # 往返含税总价，不是单程 1202×2
    assert fp.flight_no == "GK036"
    rows = json.loads(fp.extra)
    assert len(rows) == 3 and rows[0]["basis"] == "product_round_trip_tax"
    notes = [p for p in c.paths if p["path"] == "往返"]
    assert len(notes) == 1 and notes[0]["status"] == "ok", c.paths
    assert notes[0]["rows"] == 3
    # 国际机场码归并城市码（NRT→TYO），且 URL 是往返入口
    assert any("/round-sha-tyo" in u for u in page.gotos), page.gotos


def test_fetch_rt_no_anchor_is_error_not_empty(monkeypatch):
    c = _crawler()
    page = _Page("<html>whaleguard</html>")
    _wire(monkeypatch, c, page)
    assert c._fetch_rt("SHA", "PEK", ["2026-11-19"], "2026-11-22") == []
    notes = [p for p in c.paths if p["path"] == "往返"]
    assert notes and notes[0]["status"] == "blocked", c.paths

    c2 = _crawler()
    page2 = _Page("<html>页面改版了</html>")
    _wire(monkeypatch, c2, page2)
    assert c2._fetch_rt("SHA", "PEK", ["2026-11-19"], "2026-11-22") == []
    notes2 = [p for p in c2.paths if p["path"] == "往返"]
    assert notes2 and notes2[0]["status"] == "error", c2.paths


def test_fetch_rt_explicit_no_flight_is_empty(monkeypatch):
    c = _crawler()
    page = _Page("没有符合条件的航班，请更换日期")
    _wire(monkeypatch, c, page)
    assert c._fetch_rt("SHA", "PEK", ["2026-11-19"], "2026-11-22") == []
    notes = [p for p in c.paths if p["path"] == "往返"]
    assert notes and notes[0]["status"] == "empty", c.paths
    assert "站点明确无可售往返" == notes[0]["detail"]


def test_fetch_ret_date_routes_to_rt_not_oneway(monkeypatch):
    c = _crawler()
    seen = {}

    def boom(*_a, **_k):
        raise AssertionError("往返不得走单程 H5/日历通路")

    monkeypatch.setattr(c, "_fetch_intl", boom)
    monkeypatch.setattr(c, "_fetch_rt",
                        lambda f, t, d, r: seen.update(args=(f, t, list(d), r)) or [])
    for frm, to in (("SHA", "CAN"), ("SHA", "TYO")):
        assert c.fetch(frm, to, ["2026-11-10"], ret_date="2026-11-15") == []
    assert seen["args"] == ("SHA", "TYO", ["2026-11-10"], "2026-11-15")
    assert [p for p in c.paths if p["path"] == "TRIP"] == []
