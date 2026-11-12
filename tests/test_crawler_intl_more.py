# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r336_intl_filter_tags.py
- tests/test_r372_intl_slow_capture.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import json
import logging
import os
import pytest
import sys

from crawlers.ctrip import CtripCrawler
from crawlers.qunar import QunarCrawler as _QN


# ---- merged from tests/test_r336_intl_filter_tags.py ----

def _filter(det_id, triples):
    """构造单个 filter 块（title+labels+detailItemId 三元组列表）。"""
    return {"filterId": det_id, "filterTitle": "x",
            "details": [{"detailItems": [
                {"title": t, "labels": l, "detailItemId": i}
                for t, l, i in triples]}]}


def _flight(trans_city=None, names=None, reduce=None, code="MU583"):
    """构造最小 intl 行（走通 _extract_intl_flights 时刻链所需键）。

    code 传列表=段链形态（FNO|FROM-TO|DATE），链推导分支产出
    transCity 展示名并保留码域供签证表直查。"""
    info = {"depTime": "08:00", "depDate": "2026-11-16",
            "arrTime": "14:00", "arrDate": "2026-11-16",
            "name": names or ["东方航空"]}
    if trans_city:
        info["transCity"] = trans_city
    f = {"binfo": info, "minPrice": "1000", "code": code}
    if reduce:
        f["reducePriceDesc"] = reduce
    return f


def _tags():
    return _QN._intl_filter_tags({"allFilters": [
        _filter("transCitys", [
            ("不限", None, "default_fcity"),
            ("香港(中国)", [], "HKG"),
            ("台北(中国)", ["需过境签"], "TPE"),
            ("伦敦(英国)", ["需过境签"], "LON"),
            ("曼谷(泰国)", [], "BKK"),
            ("东京(日本)", ["需落地签"], "TYO"),   # 白名单外词不采
        ]),
        _filter("carriers", [
            ("国泰航空", [], "CX"),
            ("马来峇迪航空", ["廉价航空"], "OD"),
            ("春秋航空", ["廉价航空"], "9C"),
        ]),
    ]})


def test_intl_filter_tags_collect():
    visa_code, visa_city, lcc = _tags()
    # 码域主通道：detailItemId 直收（UI 项 default_fcity 非 3 字母码不入）
    assert visa_code == {"TPE": "需过境签", "LON": "需过境签"}
    # 词面兜底通道：剥国别括号归一
    assert visa_city == {"台北": "需过境签", "伦敦": "需过境签"}
    assert lcc == {"马来峇迪航空", "春秋航空"}


def test_trans_visa_by_city_face():
    """渠道真值 transCity（无段链可推码）走词面兜底通道。"""
    tags = _tags()
    rows = _QN._extract_intl_flights(
        [_flight(trans_city="台北")], filter_tags=tags)
    assert rows[0].get("labels") == "需过境签"
    # 多转点任一命中即落（join 语义=行程含该中转地）
    rows2 = _QN._extract_intl_flights(
        [_flight(trans_city="郑州/台北")], filter_tags=tags)
    assert rows2[0].get("labels") == "需过境签"
    # 非过境签中转不落
    rows3 = _QN._extract_intl_flights(
        [_flight(trans_city="郑州")], filter_tags=tags)
    assert "labels" not in rows3[0]


def test_trans_visa_by_seg_code():
    """码域主通道（push 审校 P3 收口）：段链推导行 transCity 展示名
    「台北桃园」与 filter 归一名「台北」词面域失配——链推导转点码
    airport_city_code 归一后直查签证表，全量贴签（7 行零贴签根治）。"""
    rows = _QN._extract_intl_flights(
        [_flight(code=["BR711|PVG-TPE|2026-11-16",
                       "BR87|TPE-CDG|2026-11-16"])], filter_tags=_tags())
    assert rows[0].get("transCity") == "中国台北"   # R55b 一切以携程为准：TPE 官方名中国台北
    assert rows[0].get("labels") == "需过境签"


def test_visa_merges_with_reduce_desc():
    """labels 多值「·」联接（H5 _h5_labels_of 同形态）：降价词在前
    与既有 intl 出口序一致，过境签随后。"""
    rows = _QN._extract_intl_flights(
        [_flight(trans_city="台北", reduce="已减¥100")],
        filter_tags=_tags())
    assert rows[0].get("labels") == "已减¥100·需过境签"


def test_lcc_joins_by_airline_name():
    tags = _tags()
    rows = _QN._extract_intl_flights(
        [_flight(names=["马来峇迪航空"])], filter_tags=tags)
    assert rows[0].get("lcc") is True
    # 全服务航司不落
    rows2 = _QN._extract_intl_flights(
        [_flight(names=["国泰航空"])], filter_tags=tags)
    assert "lcc" not in rows2[0]


def test_no_tags_zero_change():
    """filter_tags 缺省（None/空表）= 既有行为逐字节不变（类名直调
    形态兼容——判例三§12 直调面零破坏）。"""
    for ft in (None, ({}, {}, set())):
        rows = _QN._extract_intl_flights(
            [_flight(trans_city="台北", names=["马来峇迪航空"])],
            filter_tags=ft)
        assert "labels" not in rows[0]
        assert "lcc" not in rows[0]


def test_parse_intl_response_wires_tags():
    """端到端：_parse_intl_response 解出 data 后自动收集双表并接线。"""
    data = {
        "allFilters": [
            _filter("transCitys", [("台北(中国)", ["需过境签"], "TPE")]),
            _filter("carriers", [("马来峇迪航空", ["廉价航空"], "OD")]),
        ],
        "flights": [_flight(trans_city="台北", names=["马来峇迪航空"])],
    }
    flights, risk = _QN._parse_intl_response(
        json.dumps({"bstatus": {"code": 0}, "code": 0,
                    "data": data}, ensure_ascii=False))
    assert risk == ""
    assert flights[0].get("labels") == "需过境签"
    assert flights[0].get("lcc") is True


# ---- 冻结 dump 回放（skipif：debug/ 语料不入库，本地强化 CI 稳定；
# 活文件律——锁结构关系不锚瞬时计数，判例十八§24）----

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---- merged from tests/test_r372_intl_slow_capture.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

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
