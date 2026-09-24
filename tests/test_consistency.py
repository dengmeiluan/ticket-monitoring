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
        "qunar": QunarCrawler.PC_URL_TPL.format(
            from_name=quote("上海"), to_name=quote("乌鲁木齐"),
            fcode="SHA", tcode="URC", date="2026-10-05"),
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
