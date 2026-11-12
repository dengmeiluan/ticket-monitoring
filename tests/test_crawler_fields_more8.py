# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r307_fields.py
- tests/test_r339_fields.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import json
import logging
import os
import sys

from core.alerter import Alerter
from crawlers.ctrip import CtripCrawler
from crawlers.fliggy import FliggyCrawler


# ---- merged from tests/test_r307_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


# ---- merged from tests/test_r339_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("r339")
_CT = CtripCrawler({}, _LOG)


# ---- ctrip fixture（同构 r241/r307） ----

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


_DD = "2026-11-16 07:30"
_AD = "2026-11-16 12:00"


def _row(segs):
    item = _ctrip_item(segs, [_ctrip_policy()])
    return _CT._extract_ctrip_flights(json.dumps([item]))[0]


# ---- ctrip 中转二段机型 ----

def test_ctrip_plane2_transfer_second_seg():
    """两段机型真分化（r339a 实测 48/65）→ plane2/planeSize2 落二段
    值，plane/planeSize 首段语义不变。"""
    r = _row([
        _ctrip_seg(_DD, _AD, craft={"kind": 2, "cdisname": "波音737(中)"}),
        _ctrip_seg(_DD, _AD, craft={"kind": 1, "cdisname": "空客330(大)"},
                   flgno="CZ6982")])
    assert r.get("plane") == "波音737(中)", r
    assert r.get("planeSize") == "中型机", r
    assert r.get("plane2") == "空客330(大)", r
    assert r.get("planeSize2") == "大型机", r


def test_ctrip_plane2_direct_absent():
    """直飞行不落二段机型键（仅中转行落——无值不落键卫生律）。"""
    r = _row([_ctrip_seg(_DD, _AD,
                         craft={"kind": 2, "cdisname": "波音737(中)"})])
    assert "plane2" not in r and "planeSize2" not in r, r


def test_ctrip_plane2_missing_craftinfo_absent():
    """二段 craftinfo 缺席（dump 8/256 段 null 形态）→ 二段键不落，
    首段照常。"""
    r = _row([
        _ctrip_seg(_DD, _AD, craft={"kind": 2, "cdisname": "波音737(中)"}),
        _ctrip_seg(_DD, _AD, flgno="CZ6982")])
    assert "plane2" not in r and "planeSize2" not in r, r
    assert r.get("plane") == "波音737(中)", r


def test_ctrip_plane2_kind_missing_paren_fallback():
    """二段 kind 缺失 → cdisname 括号兜底（与首段同门同兜底）。"""
    r = _row([
        _ctrip_seg(_DD, _AD, craft={"kind": 1, "cdisname": "空客330(大)"}),
        _ctrip_seg(_DD, _AD, craft={"cdisname": "波音737(中)"},
                   flgno="CZ6982")])
    assert r.get("plane2") == "波音737(中)", r
    assert r.get("planeSize2") == "中型机", r


def test_ctrip_plane2_same_as_first_still_landed():
    """二段与首段相同（17/65 形态）照落——按行分化非恒值，「全程
    同机型」是确认信息。"""
    r = _row([
        _ctrip_seg(_DD, _AD, craft={"kind": 2, "cdisname": "波音737(中)"}),
        _ctrip_seg(_DD, _AD, craft={"kind": 2, "cdisname": "波音737(中)"},
                   flgno="CZ6982")])
    assert r.get("plane2") == "波音737(中)", r
    assert r.get("planeSize2") == "中型机", r


# ---- widebody_only 门按全程判 ----

def _f(plane_size=None, plane_size2=None):
    f = {"price": 900.0, "airline": "东航", "flight_no": "MU123",
         "planeSize": plane_size or ""}
    if plane_size2 is not None:
        f["planeSize2"] = plane_size2
    return f


def test_widebody_gate_second_seg_midsize_filtered():
    """widebody_only 中转行全段判：首段大型 + 二段中型 → 剔
    （全程坐什么飞机，二段非大型是否定证据）。"""
    out = Alerter._route_filters(
        [_f("大型机", "中型机"), _f("大型机", "大型机")],
        {"widebody_only": True})
    assert [f["planeSize2"] for f in out] == ["大型机"], out


def test_widebody_gate_absent_ps2_fail_open():
    """planeSize2 缺席（渠道未标注二段）→ 不剔（缺席不剔防整渠道
    误杀，与 planeSize 同律）。"""
    out = Alerter._route_filters(
        [_f("大型机"), _f("大型机", "大型机")],
        {"widebody_only": True})
    assert len(out) == 2, out


# ---- fliggy「共享」词面兜底 ----

def test_fliggy_share_fallback_label():
    """share_map 未命中（_SHARE_JS 漏采窗）+ 机型行含「共享」→
    labels 落「共享」兜底。"""
    txt = ("上航FM9251\n\n中型机 737 共享\n\n19:55\n\n01:25\n\n"
           "浦东T1\n\n海口美兰\n\n¥900\n订票")
    f = FliggyCrawler._parse_pc_text(txt, "2026-11-16", share_map={})[0]
    assert f.get("labels") == "共享", f
    assert "shareCarrier" not in f, f


def test_fliggy_share_hit_no_dup():
    """share_map 命中（常态轮）→ shareCarrier 承载，labels 不重复
    落「共享」。"""
    txt = ("上航FM9251\n\n中型机 737 共享\n\n19:55\n\n01:25\n\n"
           "浦东T1\n\n海口美兰\n\n¥900\n订票")
    f = FliggyCrawler._parse_pc_text(
        txt, "2026-11-16",
        share_map={"FM9251": "实际乘坐航班：上海航空FM9251"})[0]
    assert f.get("shareCarrier") == "实际乘坐航班：上海航空FM9251", f
    assert "共享" not in (f.get("labels") or ""), f


def test_fliggy_no_share_word_no_label():
    """机型行无「共享」词 → labels 不落（非共享行零污染）。"""
    txt = ("东航MU8369\n\n中型机 737 有餐食\n\n19:55\n\n01:25\n\n"
           "浦东T1\n\n乌鲁木齐\n\n¥2522\n订票")
    f = FliggyCrawler._parse_pc_text(txt, "2026-11-16", share_map={})[0]
    assert not f.get("labels"), f


# ---- 三端同轮：webui 投影白名单 + 渲染词面 ----

def test_webui_state_whitelist_carries_plane2():
    """/api/state extra 投影面（webui 后端白名单）带 plane2/planeSize2
    ——爬虫键落库后到不了前端=白名单漏接（三端同轮的中端）。"""
    mod = webui_full_src()
    assert '"plane2"' in mod and '"planeSize2"' in mod, \
        "webui state 白名单未接 plane2/planeSize2"


def test_webui_render_gate_carries_plane2():
    """明细次行渲染门带 planeSize2 词面（「全程坐什么飞机」读者判断
    的前端出口；CSV 机型列同轮）。"""
    mod = webui_full_src()
    assert "f.planeSize2" in mod, "webui 明细渲染门未接 planeSize2"
