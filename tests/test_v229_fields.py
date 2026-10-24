# -*- coding: utf-8 -*-
"""depTerminal 恒空键卫生：四渠道写点无值不落键（tuniu 同族律补齐）。

depTerminal 出发航站楼是航向相关稀疏键：单航站楼侧渠道恒下发空串
（GEN 窗 ctrip/qunar/fliggy 非空率 0%、tongcheng 0.9%），空串平铺
使 DB 累积数十万行恒空键。家族律=「有值才落键」（tuniu 先例：
_offer/行层双守卫），空串与缺键同态不落；真值面不变（qunar 反向
航线 75/75 真值照落），跨渠道 _propagate_fields 补全链不受影响
（补全本就跳过空值）。消费面零波及：webui 载荷 (f.get() or "").strip()
归一、CSV/明细行均为 falsy 判定。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v229_fields.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.ctrip import CtripCrawler  # noqa: E402
from crawlers.qunar import QunarCrawler  # noqa: E402

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
