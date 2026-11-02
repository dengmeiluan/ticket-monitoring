# -*- coding: utf-8 -*-
"""渠道字段第十五批回归：qunar 退改费 returnFee/changeFee 结构化双键
（PC/H5 两路径，价位级决策字段透传三端）/ qunar PC lateTime→avgDelay
出口键统一（延误分钟跨渠道第四源，webui 渲染通道现成零改动）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v181_fields.py
"""
import copy
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.qunar import QunarCrawler  # noqa: E402


# ---- 样本基座（同 v1554 PC 预案样本形态） ----

_PC_BASE = {
    "code": "FM9223", "minPrice": "2472", "transCity": "",
    "extparams": {"childPrice": 0, "infantPrice": None},
    "binfo": {"airCode": "FM9223", "shortName": "上航",
              "depTime": "19:55", "arrTime": "01:25",
              "date": "2026-10-04", "arrDate": "2026-10-05",
              "flightTime": "5h30m",
              "depTerminal": "", "arrTerminal": "T2",
              "depAirport": "乌鲁木齐天山", "arrAirport": "虹桥机场",
              "planeFullType": "空客330(大)"},
}


def _pc_raw(refund_rule=None, latetime=None):
    fl = copy.deepcopy(_PC_BASE)
    if refund_rule is not None:
        fl["extparams"]["refundChangeRule"] = refund_rule
    if latetime is not None:
        # 生产 dump 真实结构：lateTime 在 binfo 分段层（顶层恒缺，
        # v1.5.82 B1 读层修复时实证——自造顶层形态=假镜像教训）
        fl["binfo"]["lateTime"] = latetime
    return json.dumps({"ret": True, "code": 0,
                       "data": {"flights": [fl]}})


# ---- D-1 退改费结构化双键：PC 路径 ----

def test_qunar_pc_refund_fee_int_keys():
    fl = QunarCrawler._parse_pc_flights(
        _pc_raw(refund_rule='{"returnFee":366,"changeFee":0}'),
        "2026-10-04")
    f = fl[0]
    assert f["returnFee"] == 366 and isinstance(f["returnFee"], int)
    assert f["changeFee"] == 0 and isinstance(f["changeFee"], int)
    # 原 JSON 串键保持不动（既有消费兼容）
    assert f["refundChange"] == '{"returnFee":366,"changeFee":0}'


def test_qunar_pc_refund_fee_minus1_change_kept():
    # changeFee=-1 渠道「不可改」语义如实保留（与 refundChange 串同协议）
    fl = QunarCrawler._parse_pc_flights(
        _pc_raw(refund_rule='{"returnFee":430,"changeFee":-1}'),
        "2026-10-04")
    f = fl[0]
    assert f["returnFee"] == 430
    assert f["changeFee"] == -1


def test_qunar_pc_refund_fee_absent_not_set():
    # 规则缺失/空串不落键（宁缺勿错，无值不占位）
    fl = QunarCrawler._parse_pc_flights(_pc_raw(), "2026-10-04")
    assert "returnFee" not in fl[0]
    assert "changeFee" not in fl[0]


def test_qunar_pc_refund_fee_bad_json_not_set():
    fl = QunarCrawler._parse_pc_flights(
        _pc_raw(refund_rule='not-json'), "2026-10-04")
    assert "returnFee" not in fl[0]


# ---- D-1 退改费结构化双键：H5 路径 ----

_H5_BASE = {
    "code": "GS7587", "price": 800, "minPrice": 800,
    "crossDayDesc": "+1天", "transCity": "石家庄",
    "transTime": "17时25分",
    "binfo1": {"depTime": "14:30", "arrTime": "00:20",
               "depDate": "2026-10-06", "arrDate": "2026-10-07",
               "codeShare": False, "depTerminal": "", "arrTerminal": "T2"},
}


def _h5_raw(refund_rule=None):
    fl = copy.deepcopy(_H5_BASE)
    if refund_rule is not None:
        fl["extparams"] = json.dumps(
            {"refundChangeRule": refund_rule}, ensure_ascii=False)
    return json.dumps({"ret": True, "data": json.dumps(
        {"flights": [fl]})})


def test_qunar_h5_refund_fee_int_keys():
    fl = QunarCrawler._parse_response_flights(
        _h5_raw('{"returnFee":199,"changeFee":199}'))
    f = fl[0]
    assert f["returnFee"] == 199 and isinstance(f["returnFee"], int)
    assert f["changeFee"] == 199 and isinstance(f["changeFee"], int)
    assert f["refundChange"] == '{"returnFee":199,"changeFee":199}'


def test_qunar_h5_refund_fee_absent_not_set():
    fl = QunarCrawler._parse_response_flights(_h5_raw())
    assert "returnFee" not in fl[0]


# ---- D-2 lateTime→avgDelay 出口键统一：PC 路径 ----

def test_qunar_pc_latetime_to_avgdelay():
    fl = QunarCrawler._parse_pc_flights(_pc_raw(latetime="-10"),
                                        "2026-10-04")
    f = fl[0]
    assert f["avgDelay"] == -10 and isinstance(f["avgDelay"], int)


def test_qunar_pc_latetime_invalid_not_set():
    fl = QunarCrawler._parse_pc_flights(_pc_raw(latetime="abc"),
                                        "2026-10-04")
    assert "avgDelay" not in fl[0]


def test_qunar_pc_latetime_absent_not_set():
    fl = QunarCrawler._parse_pc_flights(_pc_raw(), "2026-10-04")
    assert "avgDelay" not in fl[0]
