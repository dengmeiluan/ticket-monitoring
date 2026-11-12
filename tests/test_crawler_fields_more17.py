# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_v229_fields.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import json
import logging
import os
import sys

from crawlers.ctrip import CtripCrawler
from crawlers.qunar import QunarCrawler


# ---- merged from tests/test_v229_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t229")
_CT = CtripCrawler({}, _LOG)


def _ctrip_one(item):
    rows = CtripCrawler._extract_ctrip_flights(_CT, json.dumps([item]))
    assert rows
    return rows[0]


def _ctrip_seg(bsname=""):
    return {"dateinfo": {"ddate": "2026-10-06 16:40:00",
                         "adate": "2026-10-06 21:30:00"},
            "basinfo": {"flgno": "MU5633"},
            "dportinfo": {"bsname": bsname, "aport": "URC"},
            "aportinfo": {"bsname": "T2", "aport": "SHA"}}


def _policy(price=2410, qty=5):
    return {"tprice": price, "quantity": qty, "drate": 5.2,
            "classinfor": [{"cgrd": 0}]}


def test_ctrip_dep_terminal_empty_not_landed():
    """dportinfo.bsname 空串（GEN 全量形态）：出发楼不落键，
    到达楼真值照落。"""
    r = _ctrip_one({"pid": "", "mutilstn": [_ctrip_seg()],
                    "policyinfo": [_policy()]})
    assert "depTerminal" not in r
    assert r["arrTerminal"] == "T2"


def test_ctrip_dep_terminal_value_lands():
    """bsname 有值（多航站楼出发侧）：真值照落（卫生律不裁真值）。"""
    r = _ctrip_one({"pid": "", "mutilstn": [_ctrip_seg(bsname="T1")],
                    "policyinfo": [_policy()]})
    assert r["depTerminal"] == "T1"
    assert r["arrTerminal"] == "T2"


def _h5_raw(flight):
    return json.dumps({"ret": True,
                       "data": json.dumps({"flights": [flight]})})


def test_qunar_h5_dep_terminal_empty_not_landed():
    """H5 binfo 层 depTerminal 空串（单航站楼出发侧）：不落键。"""
    fl = QunarCrawler._parse_response_flights(_h5_raw({
        "code": "MU8370", "price": 1500, "minPrice": 1500,
        "binfo": {"airCode": "MU8370", "shortName": "东航",
                  "depTime": "20:20", "arrTime": "01:25",
                  "depDate": "2026-10-06", "arrDate": "2026-10-07",
                  "flightTime": "5h30m",
                  "depTerminal": "", "arrTerminal": "T2"}}))
    assert len(fl) == 1
    assert "depTerminal" not in fl[0]
    assert fl[0]["arrTerminal"] == "T2"


def test_qunar_h5_dep_terminal_value_lands():
    """H5 binfo 层 depTerminal 真值（反向航线 75/75 形态）：照落。"""
    fl = QunarCrawler._parse_response_flights(_h5_raw({
        "code": "MU8370", "price": 1500, "minPrice": 1500,
        "binfo": {"airCode": "MU8370", "shortName": "东航",
                  "depTime": "20:20", "arrTime": "01:25",
                  "depDate": "2026-10-06", "arrDate": "2026-10-07",
                  "flightTime": "5h30m",
                  "depTerminal": "T3", "arrTerminal": ""}}))
    assert len(fl) == 1
    assert fl[0]["depTerminal"] == "T3"
    assert "arrTerminal" not in fl[0]


# ---- tongcheng cancelRate/bridgeRate：空串门（零值=显式真值照落） ----

def _tc_flight(**kw):
    f = {"fn": "CZ6981", "asn": "南航",
         "dt": "2026-10-06 18:30", "at": "2026-10-06 23:40",
         "td": "5h10m",
         "lps": [{"atp": 1500, "brs": [{"al": 5}]}]}
    f.update(kw)
    return f


def test_tongcheng_cancel_bridge_zero_truth_lands():
    """cancelRate/bridgeRate=0 是渠道显式真值：空串门（!= ""）不落
    空串、零值照落——truthy 门会把 0 一并吞掉（直飞行 0 占出勤
    67.7~79.8%，误吞=出勤塌方+哨兵误报键名失效）。"""
    from crawlers.tongcheng import TongchengCrawler
    f = _tc_flight(sts=[{"tt": 9, "td": "航班取消率0%"},
                        {"tt": 6, "td": "航班廊桥率0%"}])
    rows = TongchengCrawler._extract_flights(
        json.dumps({"data": {"fl": [f]}}))
    r = rows[0]
    assert r["cancelRate"] == 0
    assert r["bridgeRate"] == 0
