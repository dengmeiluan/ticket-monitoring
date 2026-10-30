# -*- coding: utf-8 -*-
"""r285 数据层：ctrip 衔接时长结构化真源转正（CT-W3 挂哨结案）。

互证材料（调研双 dump 代际一致）：fltitem.costtime（item 级，中转行
83/83 在场、直飞行结构性不出）≡ totalduration − 两段纯飞 ≡ 现行
layover（日期差推算）逐行全等——转正=结构化优先、日期差兜底：
解析链上少一次对 dateinfo 键存活的依赖（渠道改版双源冗余），真值
挂来源标 layoverSrc="ct"（LESSONS 一.7：真值挂来源标；来源变了
标记跟着变，flightnorm 判伪豁免面同步收编）。三段中转的 costtime
语义未证（单值 vs 逐段归属），维持逐段差累计宁缺勿错。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r285_fields.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.ctrip import CtripCrawler  # noqa: E402

_LOG = logging.getLogger("t285")
_CT = CtripCrawler({}, _LOG)


def _seg(dd, ad, flgno="GS7529"):
    return {"dateinfo": {"ddate": dd, "adate": ad},
            "basinfo": {"flgno": flgno},
            "dportinfo": {"bsname": "", "aport": "URC"},
            "aportinfo": {"bsname": "T2", "aport": "SHA"}}


def _trans_item(**top):
    """两段中转样本：首段 16:40→19:10、二段 20:30→23:30（同日，
    日期差口径衔接=80 分钟）。_no_costtime=True 时删除键（真缺席）。"""
    drop = top.pop("_no_costtime", False)
    item = {"pid": "x", "costtime": 80,
            "mutilstn": [_seg("2026-10-08 16:40:00", "2026-10-08 19:10:00"),
                         _seg("2026-10-08 20:30:00", "2026-10-08 23:30:00",
                              "MU5700")],
            "policyinfo": [{"tprice": 2457, "quantity": 5, "drate": 5.2}]}
    item.update(top)
    if drop:
        item.pop("costtime", None)
    rows = _CT._extract_ctrip_flights(json.dumps([item]))
    assert rows, "样本应产出至少一行"
    return rows[0]


class TestCosttimeStructuredLayover:
    """衔接时长结构化真源优先、日期差兜底。"""

    def test_costtime_present_wins_with_ct_marker(self):
        """costtime 在场（两段中转、值>0）：layover 取结构化真值，
        layoverSrc 标 "ct"（来源标随源变，LESSONS 一.7）。"""
        r = _trans_item(costtime=225)
        assert r.get("layover") == 225, r
        assert r.get("layoverSrc") == "ct", r

    def test_costtime_absent_falls_back_to_times(self):
        """costtime 缺席：退回日期差推算（现行行为零变化，
        layoverSrc="times"）。"""
        r = _trans_item(_no_costtime=True)
        assert r.get("layover") == 80, r
        assert r.get("layoverSrc") == "times", r

    def test_costtime_zero_or_bad_falls_back(self):
        """costtime=0 / 非数字：视为缺席退回日期差（占位宁缺勿错，
        与 prate 恒 0 组合行占位同律）。"""
        for bad in (0, -5, "abc", None):
            r = _trans_item(costtime=bad)
            assert r.get("layover") == 80, (bad, r)
            assert r.get("layoverSrc") == "times", (bad, r)

    def test_three_seg_keeps_times_path(self):
        """三段中转：costtime 单值语义未证（逐段归属未知），维持
        逐段日期差累计 + "times"（宁缺勿错）。"""
        item = {"pid": "x", "costtime": 300,
                "mutilstn": [_seg("2026-10-08 16:40:00",
                                  "2026-10-08 18:00:00"),
                             _seg("2026-10-08 19:00:00",
                                  "2026-10-08 20:00:00", "MU5700"),
                             _seg("2026-10-08 21:00:00",
                                  "2026-10-08 23:30:00", "HO1108")],
                "policyinfo": [{"tprice": 2457, "quantity": 5,
                                "drate": 5.2}]}
        rows = _CT._extract_ctrip_flights(json.dumps([item]))
        assert rows, "样本应产出至少一行"
        r = rows[0]
        assert r.get("layover") == 120, r   # 60+60 逐段累计
        assert r.get("layoverSrc") == "times", r


class TestFlightnormCtExempt:
    """flightnorm 判伪豁免面收编：layoverSrc="ct" 与 transInfo/times
    同属结构化真值——启发守卫不判真值（真值跨天长停恰落击杀区）。"""

    def test_ct_marker_exempt_from_1440_guard(self):
        """真值行（lay+dur 恰 1440 整：510+930）：layoverSrc="ct"
        不被判伪清零。"""
        from core.flightnorm import normalize
        f = {"price": 1200, "depTime": "08:00", "arrTime": "23:30",
             "depDate": "2026-10-08", "arrDate": "2026-10-09",
             "layover": 510, "layoverM": 510, "layoverSrc": "ct",
             "totalDuration": "15时30分", "_platform": "ctrip",
             "transCity": "郑州", "flightNo": "GS7529"}
        out = normalize(f, {})
        assert out.get("layoverM") == 510, out

    def test_unmarked_still_guarded(self):
        """无来源标行守卫不豁免（守卫本体零回归）。"""
        from core.flightnorm import normalize
        f = {"price": 1200, "depTime": "08:00", "arrTime": "23:30",
             "depDate": "2026-10-08", "arrDate": "2026-10-09",
             "layover": 510, "layoverM": 510, "totalDuration": "15时30分",
             "_platform": "qunar", "transCity": "郑州",
             "flightNo": "GS7529"}
        out = normalize(f, {})
        assert out.get("layoverM") in (0, None, ""), out
