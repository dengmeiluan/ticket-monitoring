# -*- coding: utf-8 -*-
"""ctrip pid zstd 载荷的手提行李额接入（carryon 键）+ 三处零新键收编。

调研实证（两日 251/251 政策行）：
trlinfos[].policies.tag[] 恒 4 家族各 1——freeLuggageAmount_N（已采
baggage）之外，carryOnLuggageMaxWeight_N（KG，值域 5/7/8）与
carryOnLuggageMaxAmount_N（件，值域 1/2）100% 在场，前轮落 baggage
时孪生键漏落码。采集门与 baggage 完全同构：同一循环取值、双门
（price+grade）配对、仅直飞行；春秋 free=0 行恒 (7KG,1件)——「最低价
不含托运但有手提额」比价面补全。值域门 1-20KG/1-9 件（观测 5/7/8×1/2，
超界宁缺勿错）。

零新键三处：nt=20 第 5 词 LimitedPassengerNumPolicy→「限人数」（行内
aset「2-3人享￥1910」+资格价互证，与 qunar「限3-9人」同语义族）；
aset「中转免二次托运」→ transferBaggage direct 第 5 信号源（显式
「免二次托运=直挂」真值）；aset「中转免费休息」→ labels 白名单
（休息≠中转住宿，既有白名单不覆盖）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v204_fields.py -q
"""
import base64
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import zstandard  # noqa: E402

from crawlers.ctrip import CtripCrawler  # noqa: E402

_LOG = logging.getLogger("t204")
_CT = CtripCrawler({}, _LOG)


def _mk_pid(free_kg, price, grade="Y", extra_tag=None):
    tag = [f"freeLuggageAmount_{free_kg}"]
    if extra_tag:
        tag += extra_tag
    payload = {"trlinfos": [
        {"policies": {"price": price, "grade": grade, "tag": tag}}]}
    blob = zstandard.ZstdCompressor().compress(
        json.dumps(payload).encode("utf-8"))
    return "__Zstd__|" + base64.b64encode(blob).decode("ascii")


def _ctrip_seg(dd, ad, flgno="GS7529"):
    return {"dateinfo": {"ddate": dd, "adate": ad},
            "basinfo": {"flgno": flgno},
            "dportinfo": {"bsname": "", "aport": "URC"},
            "aportinfo": {"bsname": "T2", "aport": "SHA"}}


def _ctrip_policy(price=2457, ci=None, qty=5, fnotelst=None):
    p = {"tprice": price, "quantity": qty, "drate": 5.2}
    if ci is not None:
        p["classinfor"] = [ci]
    if fnotelst is not None:
        p["fnotelst"] = fnotelst
    return p


def _item(pid, policies, aset=None, transfer=False):
    segs = ([_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")]
            if not transfer else
            [_ctrip_seg("2026-10-06 16:40:00", "2026-10-06 19:10:00",
                        "GS7529"),
             _ctrip_seg("2026-10-06 20:30:00", "2026-10-06 23:30:00",
                        "MU5700")])
    it = {"pid": pid, "mutilstn": segs, "policyinfo": policies}
    if aset is not None:
        it["aset"] = aset
    return it


def _one(item):
    rows = _CT._extract_ctrip_flights(json.dumps([item]))
    assert rows
    return rows[0]


_CI_Y = {"cgrd": 0, "classNoteList": [{"notetype": 2, "notecnt": "Y"}]}


def test_carryon_matched_spring_free_zero():
    """春秋型（free=0 恒 7KG×1件，dump 实证 16 政策行）：baggage=
    「无免费托运」同时 carryon=「手提7KG·1件」——最低价不含托运的
    比价失真补全手提侧。"""
    pid = _mk_pid(0, 2457, "Y",
                  ["carryOnLuggageMaxWeight_7", "carryOnLuggageMaxAmount_1"])
    r = _one(_item(pid, [_ctrip_policy(price=2457, ci=_CI_Y)]))
    assert r["baggage"] == "无免费托运"
    assert r["carryon"] == "手提7KG·1件"


def test_carryon_wording_positive():
    """正额双值词面：「手提8KG·2件」（值域众数 8KG×2件）。"""
    pid = _mk_pid(20, 2457, "Y",
                  ["carryOnLuggageMaxWeight_8", "carryOnLuggageMaxAmount_2"])
    r = _one(_item(pid, [_ctrip_policy(price=2457, ci=_CI_Y)]))
    assert r["carryon"] == "手提8KG·2件"


def test_carryon_half_pair_not_set():
    """tag 家族缺一件数侧（渠道若改单发）：配对缺一不落，宁缺勿错。"""
    pid = _mk_pid(20, 2457, "Y", ["carryOnLuggageMaxWeight_7"])
    r = _one(_item(pid, [_ctrip_policy(price=2457, ci=_CI_Y)]))
    assert r["baggage"] == "免费托运20KG"
    assert "carryon" not in r


def test_carryon_value_guard():
    """值域门（KG 1-20 / 件 1-9）：超界形态不落（观测值域外宁缺）。"""
    for extra in (["carryOnLuggageMaxWeight_99", "carryOnLuggageMaxAmount_1"],
                  ["carryOnLuggageMaxWeight_7", "carryOnLuggageMaxAmount_0"],
                  ["carryOnLuggageMaxWeight_0", "carryOnLuggageMaxAmount_1"]):
        pid = _mk_pid(20, 2457, "Y", extra)
        r = _one(_item(pid, [_ctrip_policy(price=2457, ci=_CI_Y)]))
        assert "carryon" not in r


def test_carryon_transfer_row_not_set():
    """中转行不落（pid 是段级分算价，配对天然不中；托运/手提额属
    单件级字段，组合行继承有结构性风险——与 baggage 同门）。"""
    pid = _mk_pid(20, 2457, "Y",
                  ["carryOnLuggageMaxWeight_7", "carryOnLuggageMaxAmount_1"])
    r = _one(_item(pid, [_ctrip_policy(price=2457, ci=_CI_Y)],
                  transfer=True))
    assert "baggage" not in r
    assert "carryon" not in r


def test_carryon_mismatch_min_policy_not_set():
    """pid 政策非最低价：不落（错配即把高价政策的额挂到低价行）。"""
    pid = _mk_pid(20, 2500, "Y",
                  ["carryOnLuggageMaxWeight_7", "carryOnLuggageMaxAmount_1"])
    r = _one(_item(pid, [_ctrip_policy(price=2457, ci=_CI_Y),
                         _ctrip_policy(price=2500, ci=_CI_Y)]))
    assert "carryon" not in r
    assert "baggage" not in r


def test_nt20_passenger_num_policy():
    """nt=20 第 5 词 LimitedPassengerNumPolicy→「限人数」：成团人数
    硬性购买资格（dump 行内 aset「2-3人享￥1910」+资格价互证），
    词表白名单扩展零新键。"""
    fn = [{"notetype": 20, "notecnt": "1910_LimitedPassengerNumPolicy"}]
    r = _one(_item(_mk_pid(0, 2457, "Y"),
                   [_ctrip_policy(price=2457, ci=_CI_Y, fnotelst=fn)]))
    assert r["agePolicy"] == "限人数"


def test_nt20_existing_words_unchanged():
    """既有四词映射不受词表扩展扰动（同轮回归钉）。"""
    fn = [{"notetype": 20, "notecnt": "2767_LimitedYoungAgePolicy"}]
    r = _one(_item(_mk_pid(0, 2457, "Y"),
                   [_ctrip_policy(price=2457, ci=_CI_Y, fnotelst=fn)]))
    assert r["agePolicy"] == "限青年"


def test_aset_zzmt_second_transfer_direct():
    """aset「中转免二次托运」（tcode=G_HETZZMTY）：transferBaggage
    direct 第 5 信号源——显式「免二次托运=直挂」真值。"""
    aset = [{"tagarea": [{"tcode": "G_HETZZMTY", "tagcnt": "中转免二次托运"}]}]
    pid = _mk_pid(0, 2457, "Y")
    r = _one(_item(pid, [_ctrip_policy(price=2457, ci=_CI_Y)],
                   aset=aset, transfer=True))
    assert r["transferBaggage"] == "direct"


def test_aset_lounge_rest_label():
    """aset「中转免费休息」（tcode=G_HETXXS）→ labels 白名单：
    休息≠中转住宿，权益词不再永久缺失。"""
    aset = [{"tagarea": [{"tcode": "G_HETXXS", "tagcnt": "中转免费休息"}]}]
    pid = _mk_pid(0, 2457, "Y")
    r = _one(_item(pid, [_ctrip_policy(price=2457, ci=_CI_Y)],
                   aset=aset))
    assert "中转免费休息" in r["labels"]
