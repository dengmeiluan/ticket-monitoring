# -*- coding: utf-8 -*-
"""r325 同程国际分支（A- 级日历通道，调研 report_tongcheng.md）。

实证基线：miflightapi/ts/calendar 无登录结构化（三航线实测），但
纯 httpx 全 444「非法链接」（会话层校验）——唯一通路=Playwright
环境（iflight 预热后页内 credentials fetch，探针 p7 实证）。离线钉：

- 机场码→同程城市码归并（PEK→BJS/PVG→SHA/NRT→TYO，report §7）；
- RD[] 按 DD==date 取点（TP 含税主源）+ 顶层 TP/LP 回落档 + 0 价剔；
- tax=TP−P 拆分、ext.segments 中转信号。

网络面（预热/页内 fetch）无法离线钉，按报告 §7 生产首采 dump 定谳。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_intl_tongcheng.py
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.intl import airport_city_code  # noqa: E402
from crawlers.tongcheng import TongchengCrawler  # noqa: E402

_LOG = logging.getLogger("t_intl_tc")
_TC = TongchengCrawler({}, _LOG)


# ---- 城市码归并 ----

def test_tongcheng_city_code_merge():
    # 同程国际面收城市码（值面=IATA 城市码），机场码需归并
    assert airport_city_code("NRT") == "TYO"
    assert airport_city_code("PEK") == "BJS"
    assert airport_city_code("PVG") == "SHA"
    assert airport_city_code("PKX") == "BJS"
    # 城市码/同码目的地恒等
    assert airport_city_code("SHA") == "SHA"
    assert airport_city_code("BKK") == "BKK"


# ---- 日历解析 ----

def _cal(rd, top=None):
    body = '{"data":' + ('{"RD":' + str(rd).replace("'", '"')
                         if rd is not None else '{"RD":[]') + \
          (', "TP":%s, "LP":%s' % (top[0], top[1]) if top else "") + "}}"
    return body


def test_parse_calendar_rd_by_date():
    body = _cal([{"DD": "2026-11-15", "P": 700, "TP": 1230},
                 {"DD": "2026-11-16", "P": 435, "TP": 922}])
    row = TongchengCrawler._parse_intl_calendar(body, "2026-11-16")
    assert row == (922.0, 487.0, False)      # TP 含税主源 + tax=TP−P


def test_parse_calendar_top_fallback():
    # RD 空/未命中查询日：回落顶层 TP/LP（查询日同义交叉档；
    # top=(TP 含税, LP 裸价)——report §4 键序）
    row = TongchengCrawler._parse_intl_calendar(
        _cal([], top=(922, 435)), "2026-11-16")
    assert row == (922.0, 487.0, False)


def test_parse_calendar_zero_price_and_garbage():
    # 0 价=无报价剔；坏 JSON None
    assert TongchengCrawler._parse_intl_calendar(
        _cal([{"DD": "2026-11-16", "P": 0, "TP": 0}]), "2026-11-16") is None
    assert TongchengCrawler._parse_intl_calendar("not-json", "x") is None
    assert TongchengCrawler._parse_intl_calendar("", "x") is None


def test_parse_calendar_transfer_signal():
    row = TongchengCrawler._parse_intl_calendar(
        _cal([{"DD": "2026-11-16", "P": 300, "TP": 800,
               "ext": {"segments": [{"no": "MU1"}]}}]),
        "2026-11-16")
    assert row == (800.0, 500.0, True)


# ---- R40b ret_date 穿链钉（98081b0 半链 NameError 生产实锤）----

def test_intl_ret_date_threaded_to_inner(monkeypatch):
    """ret_date 必须穿 _fetch_intl→_fetch_intl_inner：R15 往返一期
    穿链只落一半（inner 函数体用 ret_date 但签名缺参）→ 生产每轮
    NameError（22:00:37 实锤，98081b0 收编链）。"""
    got = {}

    def _fake_inner(self, from_city, to_city, dates, fc, tc, ret_date=""):
        got["ret_date"] = ret_date
        return []

    monkeypatch.setattr(TongchengCrawler, "_fetch_intl_inner", _fake_inner)
    assert _TC._fetch_intl("SHA", "NRT", ["2026-11-16"],
                           ret_date="2026-11-20") == []
    assert got["ret_date"] == "2026-11-20"
