# -*- coding: utf-8 -*-
"""r307 数据层：ctrip 机型体量「小型机」补口（kind=3 / 括号「小」）。

r307 渠道调研唯一真候选（_scratch/r307_chA_report.md）：craftinfo
.kind=3（C909 支线机型，ctrip_xhr_2026-10-15 dump 1/325 段）现行
映射 {1:大型机,2:中型机} 缺 3、括号兜底正则 [大中] 缺「小」——
该段 planeSize 双路全空。tuniu/fliggy/tongcheng/qunar 四渠道同值
域均含「小型机」，ctrip 是五渠道唯一漏「小」的口；值域补齐后与
webui 机型体量口径一致。

样本夹具同构 test_r241_fields.py（_ctrip_item/_ctrip_seg 形态）。
运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r307_fields.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.ctrip import CtripCrawler  # noqa: E402

_LOG = logging.getLogger("r307")
_CT = CtripCrawler({}, _LOG)


def _ctrip_item(segs, policies):
    return {"mutilstn": segs, "policyinfo": policies}


def _ctrip_seg(dd, ad, craft=None, flgno="CZ6981"):
    s = {"dateinfo": {"ddate": dd, "adate": ad},
         "basinfo": {"flgno": flgno},
         "dportinfo": {"bsname": "", "aport": "URC"},
         "aportinfo": {"bsname": "T2", "aport": "SHA"}}
    if craft is not None:
        s["craftinfo"] = craft
    return s


def _ctrip_policy(price=1200, ci=None):
    p = {"tprice": price, "quantity": 5, "drate": 5.2}
    if ci is not None:
        p["classinfor"] = [ci]
    return p


_DD, _AD = "2026-10-15 16:40:00", "2026-10-15 21:30:00"


def test_ctrip_planesize_kind3_small_landed():
    """kind=3 结构化真值 → planeSize「小型机」（dump 实证形态
    C909(小)，与渠道括号词面对完全自洽）。"""
    item = _ctrip_item(
        [_ctrip_seg(_DD, _AD, craft={"kind": 3, "cdisname": "C909(小)"})],
        [_ctrip_policy()])
    row = _CT._extract_ctrip_flights(json.dumps([item]))[0]
    assert row.get("planeSize") == "小型机", row
    assert row.get("plane") == "C909(小)", row


def test_ctrip_planesize_paren_small_fallback():
    """kind 缺失段 → cdisname 括号兜底认「小」（与 qunar PC 正则
    [大中小] 同字符域；kind 在场时维持结构化真值优先现行序）。"""
    item = _ctrip_item(
        [_ctrip_seg(_DD, _AD, craft={"cdisname": "C909(小)"})],
        [_ctrip_policy()])
    row = _CT._extract_ctrip_flights(json.dumps([item]))[0]
    assert row.get("planeSize") == "小型机", row


def test_ctrip_planesize_kind_unknown_still_absent():
    """kind 出未知新值且无括号可兜底（C919 裸名）→ planeSize 不落
    （宁缺勿错；五渠道值域恒大/中/小三档，新值留观察哨不臆测映射。
    注意 kind=4 且括号带「大/中/小」的行会经既有括号兜底落键——
    本钉样本取裸名，锁的是「未知 kind 无兜底即不落」）。"""
    item = _ctrip_item(
        [_ctrip_seg(_DD, _AD, craft={"kind": 4, "cdisname": "C919"})],
        [_ctrip_policy()])
    row = _CT._extract_ctrip_flights(json.dumps([item]))[0]
    assert "planeSize" not in row, row


def test_ctrip_planesize_kind_wins_over_paren():
    """kind 与括号冲突时结构化真值优先（现行序：kind 在场不扫
    括号；kind=1 大型机 × cdisname「(小)」病理形态 → 落「大型机」，
    与 ctrip 直飞行「首段即真值」口径一致）。"""
    item = _ctrip_item(
        [_ctrip_seg(_DD, _AD, craft={"kind": 1, "cdisname": "B777(小)"})],
        [_ctrip_policy()])
    row = _CT._extract_ctrip_flights(json.dumps([item]))[0]
    assert row.get("planeSize") == "大型机", row


def test_ctrip_planesize_fullwidth_small_paren():
    """全角括号「（小）」形态兜底同认（正则字符类已含全形括号，
    小档随族覆盖；tongcheng/qunar 同形先例）。"""
    item = _ctrip_item(
        [_ctrip_seg(_DD, _AD, craft={"cdisname": "C909（小）"})],
        [_ctrip_policy()])
    row = _CT._extract_ctrip_flights(json.dumps([item]))[0]
    assert row.get("planeSize") == "小型机", row
