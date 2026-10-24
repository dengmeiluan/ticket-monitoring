# -*- coding: utf-8 -*-
"""链接与爬虫同源一致性门禁。

v50.2.0 事故沉淀：渠道 PC 化时爬虫换了主路径、用户侧链接没跟上，
钉钉推送价格链接点开是风控死页（挂羊头卖狗肉）。本文件把
「用户链接必须与爬虫已验证主路径同 host 同关键参数」从交割纪律
变成常驻断言——渠道改版改了爬虫模板而没改 _build_view_url 时，
这里先红。
"""
from urllib.parse import urlparse, parse_qs, quote

from core.alerter import Alerter
from core.models import Route
from crawlers.ctrip import CtripCrawler
from crawlers.fliggy import FliggyCrawler
from crawlers.qunar import QunarCrawler
from crawlers.tongcheng import TongchengCrawler
from crawlers.tuniu import TuniuCrawler

import logging


def _route():
    return Route(from_code="SHA", from_name="上海", to_code="URC",
                 to_name="乌鲁木齐", dates=["2026-10-05"],
                 alert_direct=2000, alert_transfer=1800)


def _a():
    return Alerter(logging.getLogger("t"), storage=None, digest=True)


def _keys(url):
    return set(parse_qs(urlparse(url).query).keys())


def test_view_url_equals_crawler_template():
    """五渠道用户链接必须与爬虫入口模板「逐参全等」（升级：
    曾只比 host + 参数键——日期接错/三字码接反全绿放过）。渠道改版
    换模板时本测试必须同步，防挂羊头死链回归。"""
    a, r = _a(), _route()
    cases = {
        "qunar": QunarCrawler.URL_TPL.format(
            from_name=quote("上海"), to_name=quote("乌鲁木齐"),
            date="2026-10-05"),
        "fliggy": FliggyCrawler.URL_TPL.format(
            fn=quote("上海"), tn=quote("乌鲁木齐"),
            fc="SHA", tc="URC", d="2026-10-05"),
        "ctrip": CtripCrawler.URL_TPL.format(
            from_city="SHA", from_name=quote("上海"), to_city="URC",
            to_name=quote("乌鲁木齐"), date="2026-10-05"),
        "tongcheng": TongchengCrawler.URL_TPL.format(
            date="2026-10-05", from_name=quote("上海"),
            to_name=quote("乌鲁木齐"), from_city="SHA", to_city="URC"),
        "tuniu": TuniuCrawler.list_url("SHA", "URC", "2026-10-05"),
    }
    for plat, expect in cases.items():
        got = a._build_view_url(r, "2026-10-05", plat)
        assert got == expect, f"{plat}:\n  got    {got}\n  expect {expect}"


def ctrip_tpl_formatted():
    return CtripCrawler.URL_TPL.format(
        from_city="SHA", from_name="上海", to_city="URC",
        to_name="乌鲁木齐", date="2026-10-05")


def test_view_url_key_params_aligned_with_crawler():
    """曾因缺中文城市名参数点开空列表（v50.2 同型风险）：
    ctrip 须带 dcityName/acityName；tongcheng 须带
    fromCity/toCity/acn/dcn——与爬虫模板参数键对齐。"""
    a, r = _a(), _route()
    ck = _keys(a._build_view_url(r, "2026-10-05", "ctrip"))
    ck_tpl = _keys(ctrip_tpl_formatted())
    assert {"dcity", "acity", "ddate", "dcityName", "acityName"} <= ck
    assert ck_tpl <= ck, f"ctrip 用户链接缺参数: {ck_tpl - ck}"

    tk = _keys(a._build_view_url(r, "2026-10-05", "tongcheng"))
    tk_tpl = _keys(TongchengCrawler.URL_TPL.format(
        date="2026-10-05", from_name="上海", to_name="乌鲁木齐",
        from_city="SHA", to_city="URC"))
    assert {"fromcitycode", "fromCode", "tocitycode", "toCode"} <= tk
    assert tk_tpl <= tk, f"tongcheng 用户链接缺参数: {tk_tpl - tk}"


def test_view_url_carries_chinese_city_names():
    """中文城市名须 URL 编码在场——qunar/fliggy 列表页按中文城市名出数据。"""
    a, r = _a(), _route()
    qu = a._build_view_url(r, "2026-10-05", "qunar")
    assert "%E4%B8%8A%E6%B5%B7" in qu      # 上海
    assert "%E4%B9%8C%E9%B2%81%E6%9C%A8%E9%BD%90" in qu  # 乌鲁木齐
    fl = a._build_view_url(r, "2026-10-05", "fliggy")
    assert "depCityName=%E4%B8%8A%E6%B5%B7" in fl


if __name__ == "__main__":
    test_view_url_equals_crawler_template()
    test_view_url_key_params_aligned_with_crawler()
    test_view_url_carries_chinese_city_names()
    print("consistency OK")


def test_specials_deep_links_same_origin_as_crawlers():
    """r319 特价多源深链同源门禁（校准轮新增）：特价推送的购买链接
    必须与爬虫主路径同源——
    - tuniu 单程=TuniuCrawler.list_url 逐字单源（曾在 core 侧手抄
      PC 域 cheapList 模板造成 m./flight. 双轨，校准轮揪出）；
    - tuniu 往返=cheapList.js 官方 round 模板（唯一实证返程链）；
    - ctrip 日历构造链与爬虫入口同 host 同关键参数；
    - ctripbd 主题榜 jumpUrl=平台下发，host 必须 m.ctrip.com（用户侧
      H5 与爬虫同域），缺 jumpUrl 回退构造链同 host。"""
    from core.specials import (ctrip_calendar_deals, ctrip_link,
                               deals_from_ctrip_board,
                               deals_from_fliggy_board, parse_specials,
                               tuniu_link)
    from datetime import date as _d
    from crawlers.ctrip import CtripCrawler as _CC

    today = _d(2026, 10, 16)
    w = parse_specials([{"enabled": True, "from": "SHA",
                         "from_name": "上海", "max_price": 900}],
                       today)[0]
    # tuniu 单程逐字单源 + 往返官方模板
    assert tuniu_link("SHA", "URC", "2026-10-20") == \
        TuniuCrawler.list_url("SHA", "URC", "2026-10-20")
    assert tuniu_link("SHA", "CAN", "2026-10-21", "2026-10-25") == \
        ("http://flight.tuniu.com/city_SHA_CAN/round/"
         "?start=2026-10-21&back=2026-10-25")
    # ctrip 构造链：与爬虫入口模板同 host 同关键参数
    lk = ctrip_link("SHA", "URC", "乌鲁木齐", "2026-10-20", "上海")
    assert urlparse(lk).hostname == urlparse(
        _CC.URL_TPL.format(from_city="SHA", from_name="上海",
                           to_city="URC", to_name="乌鲁木齐",
                           date="2026-10-20")).hostname
    assert {"dcity", "acity", "ddate"} <= _keys(lk)
    # ctripbd 平台 jumpUrl：host 同域 + 关键参数在场；缺链回退构造同域
    pay = {"routes": [
        {"departCity": {"code": "SHA", "name": "上海"},
         "arriveCity": {"code": "LHW", "name": "兰州"},
         "pl": [{"price": 200, "departDate": "2026-10-20",
                 "jumpUrl": "https://m.ctrip.com/html5/flight/pages/"
                            "first?dcity=SHA&acity=LHW&ddate=2026-10-20"}]},
        {"departCity": {"code": "SHA", "name": "上海"},
         "arriveCity": {"code": "DLC", "name": "大连"},
         "pl": [{"price": 200, "departDate": "2026-10-23",
                 "jumpUrl": ""}]}]}
    deals = deals_from_ctrip_board(pay, w, today)
    assert [urlparse(d.link).hostname for d in deals] == \
        ["m.ctrip.com", "m.ctrip.com"]
    assert {"dcity", "acity", "ddate"} <= _keys(
        [d for d in deals if d.to_code == "LHW"][0].link)
    # 日历构造链 host 同域
    cal = ctrip_calendar_deals(
        {"priceList": [{"departDate": "/Date(1792857600000+0800)/",
                        "price": 382}]},
        "SHA", "URC", "乌鲁木齐", w, today)
    assert urlparse(cal[0].link).hostname == "m.ctrip.com"
    # fliggy 榜构造链：与 FliggyCrawler.URL_TPL 同域同路径族
    # （sjipiao SSR 页，r319f 实证 board 深链同型同源）
    from crawlers.fliggy import FliggyCrawler as _FC
    fl = deals_from_fliggy_board(
        {"data": {"flights": [
            {"depCode": "SHA", "arrCode": "KMG", "arrName": "昆明",
             "depDate": "2026-10-20", "price": 280, "discount": 1.9,
             "soldOut": False},
            {"depCode": "SHA", "arrCode": "SYX", "arrName": "三亚",
             "depDate": "2026-10-21", "price": 300, "discount": None,
             "soldOut": True}]}}, w, today)
    assert len(fl) == 1 and fl[0].discount == "1.9折"   # soldOut 剔
    assert urlparse(fl[0].link).hostname == urlparse(
        _FC.URL_TPL.format(fn="上海", tn="昆明", fc="SHA", tc="KMG",
                           d="2026-10-20")).hostname
    assert {"depCity", "arrCity", "depDate"} <= _keys(fl[0].link)
