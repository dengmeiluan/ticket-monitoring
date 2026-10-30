# -*- coding: utf-8 -*-
"""数据层：tongcheng airlineCode（航司二字码）收编。

报文路径（冻结 dump 直证）：直飞 book1 → data.fl[].ac（两日 94/94
恒在）；中转 connection → data.fps[].ss[].ac（96/96 恒在，段级，
取首段=整体出发航司，与 code=ss[].fn 联接、asn 中文名同层）。
值域 ^[A-Z0-9]{2}$（MF/MU/3U/CZ/G5…，数字参位合法）。

iata2 守卫同 qunar shortCarrier/tuniu airlineIataCode 三源同律，
不匹配不落值（宁缺勿错，prate=20 先例）；同名落键即 webui 白名单
（airlineCode 通道现役）/CSV 列/搜索 hay 自动继承零协议改动。

样本形态取自生产冻结 dump。运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15114_fields.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.tongcheng import TongchengCrawler  # noqa: E402

_LOG = logging.getLogger("t15114")


# ---- 样本助手（v15110 同款形态） ----

def _tc_direct(ac="MU"):
    f = {"fn": "MU5700", "dt": "2026-10-05 13:20",
         "at": "2026-10-05 16:05", "asn": "东方航空",
         "lps": [{"atp": 1500, "brs": [{"al": 5}],
                  "pts": [{"td": "6.8折经济舱"}]}]}
    if ac is not None:
        f["ac"] = ac
    return {"data": {"fl": [f]}}


def _tc_direct_rows(payload):
    rows = TongchengCrawler._extract_flights(json.dumps(payload))
    assert rows
    return rows[0]


def _tc_trans_fp(ss):
    return {"dt": "2026-10-05 13:20", "at": "2026-10-05 21:30",
            "sd": "2h45m", "td": "8h10m", "sc": "张掖", "ss": ss,
            "lps": [{"atp": 1500, "brs": [{"al": 5}],
                     "pts": [{"td": "6.8折经济舱"}]}]}


def _tc_trans_rows(fp):
    rows = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp]}}))
    assert rows
    return rows[0]


# ---- 直飞 book1：fl[].ac ----

def test_tc_direct_airlinecode():
    """直飞行 ac → airlineCode（与 dasn/aasn 同层独立键）。"""
    r = _tc_direct_rows(_tc_direct("MU"))
    assert r["airlineCode"] == "MU"


def test_tc_direct_airlinecode_digit_carrier():
    """数字参位航司二字码合法（3U 川航/G5 华夏，iata2 值域）。"""
    r = _tc_direct_rows(_tc_direct("3U"))
    assert r["airlineCode"] == "3U"


def test_tc_direct_guard_dirty_values():
    """iata2 守卫：小写/三位/缺键/None 一律落空串不占位
    （键仍在，str 空串口径同邻键 depAirportCode）。"""
    assert _tc_direct_rows(_tc_direct("mu"))["airlineCode"] == ""
    assert _tc_direct_rows(_tc_direct("MU5"))["airlineCode"] == ""
    assert _tc_direct_rows(_tc_direct(None))["airlineCode"] == ""


# ---- 中转 connection：ss[0].ac 首段 ----

def test_tc_trans_airlinecode_first_segment():
    """中转行取 ss[0].ac（首段出发=整体出发航司，与 code=ss[].fn
    联接、asn 取首段同律）；段序抖动时首段仍是主承运语义。"""
    ss = [{"fn": "CZ6981", "dt": "2026-10-05 13:20",
           "at": "2026-10-05 16:05", "ac": "CZ"},
          {"fn": "MU5700", "dt": "2026-10-05 18:20",
           "at": "2026-10-05 21:30", "ac": "MU"}]
    r = _tc_trans_rows(_tc_trans_fp(ss))
    assert r["airlineCode"] == "CZ"


def test_tc_trans_guard_missing_ac():
    """中转段无 ac（历史 dump 形态守卫反例）：落空串不占位。"""
    ss = [{"fn": "CZ6981", "dt": "2026-10-05 13:20",
           "at": "2026-10-05 16:05"},
          {"fn": "MU5700", "dt": "2026-10-05 18:20",
           "at": "2026-10-05 21:30", "ac": "MU"}]
    r = _tc_trans_rows(_tc_trans_fp(ss))
    assert r["airlineCode"] == ""
