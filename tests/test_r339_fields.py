# -*- coding: utf-8 -*-
"""r339 数据层：ctrip 中转二段机型 plane2/planeSize2 + fliggy「共享」词面兜底。

r339a 调研唯一新采真增量（_scratch/r339a_report.md 候选 A）：
fltitem[].mutilstn[1].craftinfo 65/65 中转行在场、48/65 二段机型≠首段，
现出口 plane/planeSize 只落首段（craft 循环首段齐值即 break）——
widebody_only 筛选与「全程坐什么飞机」读者判断只反映首段。
落键门：仅中转行、无值不落键、kind∈{1,2,3} 缺失时 cdisname 括号兜底
（与首段同门同兜底）。

fliggy「共享」词面兜底（r339b F1）：机型行「共享」词与 share 载荷
（a.J_Content[data-content="实际乘坐航班：…"]）同 DOM 元素渲染，
share_map 漏采窗（_SHARE_JS evaluate 异常被吞/按屏漏采）时该行共享
事实静默丢失——兜底落 labels「共享」（shareCarrier 命中时零增量
不重复落）。

样本夹具同构 test_r307_fields.py（_ctrip_item/_ctrip_seg 形态）与
test_goal_fields.py（fliggy 行文本形态）。
运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r339_fields.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.ctrip import CtripCrawler  # noqa: E402
from crawlers.fliggy import FliggyCrawler  # noqa: E402
from core.alerter import Alerter  # noqa: E402

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
    mod = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "webui.py"), encoding="utf-8").read()
    assert '"plane2"' in mod and '"planeSize2"' in mod, \
        "webui state 白名单未接 plane2/planeSize2"


def test_webui_render_gate_carries_plane2():
    """明细次行渲染门带 planeSize2 词面（「全程坐什么飞机」读者判断
    的前端出口；CSV 机型列同轮）。"""
    mod = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "webui.py"), encoding="utf-8").read()
    assert "f.planeSize2" in mod, "webui 明细渲染门未接 planeSize2"
