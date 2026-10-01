# -*- coding: utf-8 -*-
"""渠道字段回归（v1.5.109 批次 b）：ctrip nt=31 FreeRRE 英文旗标 →
labels「航变免费退改」（nt=10 中文真源的独立载体形态）/ ctrip
classNoteList nt=3 LimitedAirlineAgreementID → agePolicy「限协议」。

样本形态取自生产 dump 直证：
- FreeRRE：nt=31 逗号旗标串内词，72/289 政策行在场；带 nt=10 中文
  「航变免费退改」的 66 政策行 66/66 与 FreeRRE 同现（家族律），另有
  6 政策行 FreeRRE 独立在场而 nt=10 缺席——同词面换独立载体（英文
  旗标），不收则该 6 行权益永久缺失。与同串 FreeLuggage 收编同法
  （逗号分隔精确等值匹配，防子串误命中）。
- LimitedAirlineAgreementID（成对 AirlineAgreementIDLimit）：
  classinfor[].classNoteList[] nt=3，航司大客户协议价（COR）硬资格；
  该政策价=行内最低有票价（1860/1860、1890/1890）票价互证成立，
  Limited* 资格家族律自洽（限卡支付/限航司会员/限年龄同门）。渲染端
  agePolicy 拼缀「价」，词面取「限协议」（「⚠限协议价」，与「限卡
  支付→限卡支付价」同构）；与 nt=20 年龄限制并存时「·」拼接既有律。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15109b_fields.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.ctrip import CtripCrawler  # noqa: E402

_LOG = logging.getLogger("t109b")
_CT = CtripCrawler({}, _LOG)


def _ctrip_item(segs, policies):
    return {"mutilstn": segs, "policyinfo": policies}


def _ctrip_seg(dd, ad, flgno="CZ6981"):
    return {"dateinfo": {"ddate": dd, "adate": ad},
            "basinfo": {"flgno": flgno},
            "dportinfo": {"bsname": "", "aport": "URC"},
            "aportinfo": {"bsname": "T2", "aport": "SHA"}}


def _ctrip_policy(price=1200, ci=None, qty=5, fnotelst=None):
    p = {"tprice": price, "quantity": qty, "drate": 5.2}
    if ci is not None:
        p["classinfor"] = [ci]
    if fnotelst is not None:
        p["fnotelst"] = fnotelst
    return p


def _ctrip_one(item):
    rows = _CT._extract_ctrip_flights(json.dumps([item]))
    assert rows
    return rows[0]


def test_ctrip_free_rre_sole_carrier():
    """FreeRRE 独立在场（nt=10 中文缺席，dump 6 行形态）：labels 照出
    「航变免费退改」——独立载体不收即永久缺失的翻案形态。"""
    item = _ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        [_ctrip_policy(price=1200, ci={"cgrd": 0},
                       fnotelst=[{"notetype": 31,
                                  "notecnt": "FreeRRE,MergeBooking"}])])
    r = _ctrip_one(item)
    assert "航变免费退改" in r["labels"].split("·")


def test_ctrip_free_rre_with_cn_no_dup():
    """nt=10 中文真源与 nt=31 FreeRRE 同现（dump 66/66 主形态）：
    「航变免费退改」恰好一次，零重复拼接。"""
    item = _ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        [_ctrip_policy(price=1200, ci={"cgrd": 0},
                       fnotelst=[{"notetype": 10, "notecnt": "航变免费退改"},
                                 {"notetype": 31,
                                  "notecnt": "FreeRRE,FreeLuggage"}])])
    r = _ctrip_one(item)
    assert r["labels"].split("·").count("航变免费退改") == 1


def test_ctrip_free_rre_substring_safe():
    """含 FreeRRE 子串的相邻词面（FreeRRExxx 形态防呆）不误命中——
    逗号分隔等值匹配，与 FreeLuggage 同门纪律。"""
    item = _ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        [_ctrip_policy(price=1200, ci={"cgrd": 0},
                       fnotelst=[{"notetype": 31,
                                  "notecnt": "FreeRREXXX,MergeBooking"}])])
    assert "航变免费退改" not in _ctrip_one(item)["labels"].split("·")


def test_ctrip_agreement_age_gate():
    """classNoteList nt=3 LimitedAirlineAgreementID：agePolicy=「限协议」
    （渲染端拼「价」成「⚠限协议价」，词面不带价字）。"""
    item = _ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        [_ctrip_policy(price=1860,
                       ci={"cgrd": 0, "classNoteList": [
                           {"notetype": 3,
                            "notecnt": "LimitedAirlineAgreementID,"
                                       "AirlineAgreementIDLimit"}]})])
    assert _ctrip_one(item)["agePolicy"] == "限协议"


def test_ctrip_agreement_with_age_combined():
    """nt=20 限学生与 nt=3 协议并存：「·」拼接（年龄限制与资格限制
    并存既有律，同「限年龄·限航司会员」形态）。"""
    item = _ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        [_ctrip_policy(price=1860,
                       ci={"cgrd": 0, "classNoteList": [
                           {"notetype": 3,
                            "notecnt": "LimitedAirlineAgreementID"}]},
                       fnotelst=[{"notetype": 20,
                                  "notecnt": "2767_LimitedStudentPolicy"}])])
    assert _ctrip_one(item)["agePolicy"] == "限学生·限协议"


def test_ctrip_agreement_nonlowest_policy_ignored():
    """协议旗标挂非最低价政策：不采（随最低价政策配对，nt=3 与 nt=20
    同律——「你看到的最低价买不了」才构成决策信号）。"""
    item = _ctrip_item(
        [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        [_ctrip_policy(price=1200, ci={"cgrd": 0}),
         _ctrip_policy(price=1500,
                       ci={"cgrd": 0, "classNoteList": [
                           {"notetype": 3,
                            "notecnt": "LimitedAirlineAgreementID"}]})])
    r = _ctrip_one(item)
    assert "agePolicy" not in r or "限协议" not in (r.get("agePolicy") or "")
