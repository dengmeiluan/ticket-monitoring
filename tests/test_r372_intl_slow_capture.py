# -*- coding: utf-8 -*-
"""r372 携程国际列表慢响应：零包重载重试 + 无响应独立归因。

起因（2026-10-26 live 实测）：五渠道并行时 SHA→BKK 的 PC 国际列表在
16s 窗口内一个 batchSearch/pull 包都没到，采集被判“国际列表未解析到
航班”→ 兜底只落日历￥670；同路由独立抓取 2.7s 即到 268 行真实行程。
慢响应被当成渠道无数据，是当轮大量“补位”行的一个真实来源。

修法：抽出 _await_intl_capture 增量等待；首轮零包且无登录证据时重载
一次再等；一包未到的空结果归因“请求无响应”，与“解析器读不懂”分开。
"""
import json
import logging
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers.ctrip import CtripCrawler  # noqa: E402

_DATE = "2026-11-16"


def _leg():
    return {"flightNo": "VZ3525", "marketAirlineCode": "VZ",
            "marketAirlineName": "泰国越捷航空",
            "departureCityCode": "SHA", "departureCityName": "上海",
            "departureAirportCode": "PVG", "departureAirportName": "浦东国际机场",
            "departureAirportShortName": "浦东",
            "departureDateTime": _DATE + " 01:30:00",
            "arrivalCityCode": "BKK", "arrivalCityName": "曼谷",
            "arrivalAirportCode": "BKK", "arrivalAirportName": "素万那普国际机场",
            "arrivalAirportShortName": "素万那普",
            "arrivalDateTime": _DATE + " 05:20:00",
            "aircraftName": "空客321", "aircraftSize": "M",
            "stopCount": 0, "transferDuration": 0, "duration": 290}


def _body():
    return json.dumps({"status": 0, "data": {"needUserLogin": False,
                        "flightItineraryList": [{
                            "flightSegments": [{"duration": 290,
                                                "flightList": [_leg()]}],
                            "priceList": [{"adultPrice": 148.0,
                                           "adultTax": 523.0,
                                           "ticketCount": 5}]}]}},
                      ensure_ascii=False)


class _Page:
    """可控假页面：reload 时才投放响应，模拟并行排队后的迟到包。"""

    def __init__(self, captured, deliver_on_reload=0):
        self.captured = captured
        self.deliver_on_reload = deliver_on_reload
        self.reloads = 0

    def reload(self, **_kw):
        self.reloads += 1
        for _ in range(self.deliver_on_reload):
            self.captured.append({"url": "https://x/batchSearch?d=%d"
                                         % self.reloads, "text": _body()})

    def wait_for_timeout(self, _ms):
        return None

    def inner_text(self, *_a, **_kw):
        return "机票列表"


def _crawler():
    c = CtripCrawler({"headless": True, "debug": False},
                     logging.getLogger("r372"))
    c.path_reset()
    return c


def test_await_intl_capture_parses_late_packages():
    """迟到包在等待窗内到达：增量解析出真实行程。"""
    c = _crawler()
    captured = [{"url": "https://x/batchSearch", "text": _body()}]
    page = _Page(captured)
    flights, need = c._await_intl_capture(
        page, captured, _DATE, set(), [], False, budget=0.2)
    assert need is False
    assert len(flights) == 1
    assert flights[0]["code"] == "VZ3525"
    assert flights[0]["price"] == 671


def test_await_intl_capture_stops_on_finished():
    """finished:true 立即收尾，不被宽限期无谓拖住。"""
    c = _crawler()
    body = _body().replace('"status": 0', '"status": 0, "finished": true')
    captured = [{"url": "https://x/pull/1", "text": body}]
    page = _Page(captured)
    flights, _ = c._await_intl_capture(
        page, captured, _DATE, set(), [], False, budget=30)
    assert len(flights) == 1
    assert page.reloads == 0


def test_zero_packages_triggers_one_reload_then_parses():
    """首轮零包：重载一次即拿到真实包（live BKK 场景）。"""
    c = _crawler()
    captured = []
    page = _Page(captured, deliver_on_reload=1)
    assert captured == []
    # 模拟 _fetch_intl_list 的首轮等待
    flights, need = c._await_intl_capture(
        page, captured, _DATE, set(), [], False, budget=0)
    assert flights == [] and not captured and need is False
    page.reload()
    flights, need = c._await_intl_capture(
        page, captured, _DATE, set(), flights, need, budget=0.2)
    assert page.reloads == 1
    assert len(flights) == 1 and flights[0]["code"] == "VZ3525"


def test_no_response_is_not_reported_as_parse_failure(monkeypatch):
    """一包未到时空结果归因“请求无响应”，不写成“未解析到航班”。"""
    c = _crawler()
    notes = []
    monkeypatch.setattr(c, "path_note",
                        lambda p, s, **kw: notes.append((p, s, kw)))
    captured = []
    page = _Page(captured)
    monkeypatch.setattr(c, "browser",
                        lambda *a, **k: __import__("contextlib")
                        .nullcontext(object()))
    monkeypatch.setattr(c, "new_page", lambda _ctx: page)
    monkeypatch.setattr(c, "attach_xhr_collector",
                        lambda _p, _k: captured)
    monkeypatch.setattr(c, "URL_LIST_INTL",
                        "https://flights.ctrip.com/online/list/"
                        "oneway-{from_city}-{to_city}?depdate={date}")
    page.goto = lambda *_a, **_k: None
    c._sleep = lambda: None
    c._await_intl_capture = lambda *_a, **_k: ([], False)
    out = c._fetch_intl_list("SHA", "BKK", "SHA", "BKK", [_DATE])
    assert out == []
    assert notes, "空结果必须留路径证据"
    _path, _status, kw = notes[-1]
    assert kw["detail"] == "国际列表请求无响应"
    assert kw["detail"] != "国际列表未解析到航班"
