# -*- coding: utf-8 -*-
"""r325 飞猪国际分支（A 级日历通道，调研 report_fliggy.md）。

实证基线：cheapestCalendar/pc 零 cookie 直连 JSONP 出数（三航线实
测）；国际按城市码收（机场码被拒「城市基础数据缺失」）；票面/税费
分列（税费 340~1272 实测占比大），0 价=无报价日静默信号。离线钉：

- 机场码 → 城市码映射（core.intl.airport_city_code）；
- JSONP 壳剥离；
- _fetch_intl 全逻辑（网络层 monkeypatch）：含税口径 price=bare+tax、
  0 价日剔、日历窗外日期剔、元素数组 extra（共享消费链明细池/达标
  判定的入口——dict 形态 extra 会让推送面拿零明细）、intl 元素戳。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_intl_fliggy.py
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.intl import airport_city_code  # noqa: E402
from crawlers.fliggy import FliggyCrawler  # noqa: E402

_LOG = logging.getLogger("t_intl_fliggy")
_FG = FliggyCrawler({}, _LOG)


# ---- 机场码 → 城市码 ----

def test_airport_city_code_mapping():
    # report §3 实证：飞猪国际收城市码，NRT 机场码被拒
    assert airport_city_code("NRT") == "TYO"
    assert airport_city_code("HND") == "TYO"
    assert airport_city_code("LHR") == "LON"
    # 大陆码与城市机场同码目的地恒等（SHA/BKK/SIN 无需映射）
    assert airport_city_code("SHA") == "SHA"
    assert airport_city_code("BKK") == "BKK"
    # 字典外码恒等回退（宁缺勿错不猜）
    assert airport_city_code("ZZZ") == "ZZZ"


# ---- JSONP 壳剥离 ----

def test_unwrap_jsonp():
    obj = _FG._unwrap_jsonp('cb({"result":[{"leaveDate":"2026-10-25"}]});')
    assert obj["result"][0]["leaveDate"] == "2026-10-25"
    assert _FG._unwrap_jsonp('{"result":[]}')["result"] == []
    assert _FG._unwrap_jsonp("not-json") is None
    assert _FG._unwrap_jsonp("") is None


# ---- _fetch_intl 全逻辑（网络层替换） ----

def _patch_calendar(days):
    # v284 起国际 PC 明细优先；本文件冻结日历兜底逻辑，PC 返回空
    _FG._fetch_intl_pc = lambda fc, tc, dates: {}
    _FG._intl_calendar = lambda fc, tc, ld, ret_date="": days


def _day(d, p, t):
    return {"leaveDate": d, "price": p, "tax": t}


def test_fetch_intl_price_is_bare_plus_tax():
    _patch_calendar([_day("2026-11-16", 739.0, 550.0),
                     _day("2026-11-17", 446.0, 550.0)])
    rows = _FG._fetch_intl("SHA", "NRT", ["2026-11-16"])
    assert len(rows) == 1
    assert rows[0].price == 1289.0        # 含税口径（票面+税费）
    assert rows[0].depart_date == "2026-11-16"
    assert rows[0].airline == "" and rows[0].flight_no == ""  # 日历源诚实留空
    els = json.loads(rows[0].extra)
    # extra 必须是元素数组（dict 形态会让推送/达标链拿零明细）
    assert isinstance(els, list) and els[0]["intl"] == 1
    assert els[0]["tax"] == 550.0
    assert els[0]["currency"] == "CNY"
    assert els[0]["source"] == "cheapestCalendar"
    assert ["2026-11-17", 446.0, 550.0] in els[0]["days"]  # 全日历上下文


def test_fetch_intl_zero_price_day_is_no_quote():
    # 0 价=该日无报价（渠道静默信号），免费票不可能——宁缺勿错剔
    _patch_calendar([_day("2026-11-16", 0.0, 0.0),
                     _day("2026-11-17", 446.0, 550.0)])
    rows = _FG._fetch_intl("SHA", "TYO", ["2026-11-16"])
    assert rows == []
    rows2 = _FG._fetch_intl("SHA", "TYO", ["2026-11-17"])
    assert len(rows2) == 1 and rows2[0].price == 996.0


def test_fetch_intl_date_outside_calendar_window():
    _patch_calendar([_day("2026-11-16", 739.0, 550.0)])
    rows = _FG._fetch_intl("SHA", "TYO", ["2027-01-01"])
    assert rows == []


def test_fetch_intl_calendar_unavailable():
    _patch_calendar(None)
    assert _FG._fetch_intl("SHA", "TYO", ["2026-11-16"]) == []


def test_fetch_intl_band_guard():
    # 国际宽带内合法；带外垃圾剔（下界 100 同样生效）
    _patch_calendar([_day("2026-11-16", 80.0, 0.0)])
    assert _FG._fetch_intl("SHA", "TYO", ["2026-11-16"]) == []
    _patch_calendar([_day("2026-11-16", 60000.0, 500.0)])
    rows = _FG._fetch_intl("SHA", "TYO", ["2026-11-16"])
    assert rows[0].price == 60500.0
