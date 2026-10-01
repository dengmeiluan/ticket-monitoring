# -*- coding: utf-8 -*-
"""r247 数据层（渠道调研两采案收编）：

C-A1 ctrip fltitem.fcode「transitServiceId_5」→ labels 白名单静态
映射「赠中转休息室」：ch1「英文内部码不采」的排除依据被渠道自带
filterlst 字典部分证伪——_5 载体行（GS7728/HU7849/HU7859 两代际
6 行）既有出口仅「享"豫转豫好"」地域品牌词，「休息室」服务内容无处
承载，不收则永久缺失（LESSONS 廿四§10 排除依据复验实锤）。不引根级
字典防漂移（_4 被撤即先例）；与「赠餐食、休息厅」同义近域互斥
（labels 已含休息厅/休息室子串不重拼）。

C-A2 ctrip aset「行李免费转运」（tcode=G_KWEBAG202311，昆航中转
2 行）→ labels 白名单 + 三态优先级收口：载体行 nt=31 FreeLuggage
旗标推断与显式转运词信号矛盾，按「显式真值 > 推断」律（「行李代
转运」→recheck 同门），显式转运词在场时旗标推断让位 recheck——
直挂筛选语义下「把需转运当直挂」的决策伤害大于「把直挂当需转运」
（五·产品律同构）。

样本形态取自生产冻结 dump（debug/ctrip_xhr_2026-10-05）。运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r247_fields.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.ctrip import CtripCrawler  # noqa: E402

_LOG = logging.getLogger("r247")
_CT = CtripCrawler({}, _LOG)


def _seg(dd, ad, flgno="GS7728"):
    return {"dateinfo": {"ddate": dd, "adate": ad},
            "basinfo": {"flgno": flgno},
            "dportinfo": {"bsname": "", "aport": "URC"},
            "aportinfo": {"bsname": "T3", "aport": "SHA"}}


def _ci_plain(letter="Y"):
    return {"cgrd": 0,
            "classNoteList": [{"notetype": 2, "notecnt": letter}]}


def _policy(price, fnotelst=None):
    p = {"tprice": price, "quantity": 5, "drate": 5.2,
         "classinfor": [_ci_plain()]}
    if fnotelst is not None:
        p["fnotelst"] = fnotelst
    return p


def _item(segs, policies, aset=None, fcode=None):
    it = {"mutilstn": segs, "policyinfo": policies}
    if aset is not None:
        it["aset"] = aset
    if fcode is not None:
        it["fcode"] = fcode
    return it


def _one(item):
    rows = _CT._extract_ctrip_flights(json.dumps([item]))
    assert rows, "解析零行"
    return rows[0]


_D1 = ("2026-10-06 08:30:00", "2026-10-06 11:50:00")
_D2 = ("2026-10-06 13:30:00", "2026-10-06 17:50:00")
_TWO = [_seg(*_D1), _seg(*_D2, flgno="HU7849")]


# ---- C-A1：fcode 静态白名单「赠中转休息室」 ----

def test_fcode_lounge_label():
    """fcode=transitServiceId_5 → labels「赠中转休息室」：载体行
    休息室服务信息的唯一可承载出口（地域品牌词不展开服务内容）。"""
    r = _one(_item(_TWO, [_policy(1200)], fcode="transitServiceId_5"))
    assert "赠中转休息室" in r["labels"], r.get("labels")


def test_fcode_lounge_with_meal_lounge_mutual_exclusive():
    """互斥门：同行 aset 已有「赠餐食、休息厅」（休息厅子串词）时
    fcode 词不重拼——同义近域重复拼接防（LESSONS 廿四§10 同词面
    重复拼接去重律的近域变体）。"""
    aset = [{"tagarea": [{"tcode": "G_ALLDRZZZFWB",
                          "tagcnt": "赠餐食、休息厅"}]}]
    r = _one(_item(_TWO, [_policy(1200)], aset=aset,
                   fcode="G_DRD,transitServiceId_5"))
    ls = r["labels"].split("·")
    assert ls.count("赠餐食、休息厅") == 1
    assert "赠中转休息室" not in ls, ls


def test_fcode_outside_whitelist_ignored():
    """白名单外 fcode（含已撤字典词 _4 与非 transitServiceId 值域
    SmartSort/城市码）不进 labels——静态映射不引根级字典防漂移。"""
    for fc in ("transitServiceId_4", "SmartSort", "CTU",
               "transitServiceId_3,transitServiceId_4"):
        r = _one(_item(_TWO, [_policy(1200)], fcode=fc))
        assert "赠中转休息室" not in (r.get("labels") or ""), (fc, r["labels"])


# ---- C-A2：「行李免费转运」labels + 三态优先级 ----

def test_aset_free_transfer_label():
    """aset「行李免费转运」（G_KWEBAG202311）→ labels：昆航中转
    行唯一行李服务承诺词，行内零既有出口承载。"""
    aset = [{"tagarea": [{"tcode": "G_KWEBAG202311",
                          "tagcnt": "行李免费转运"}]}]
    r = _one(_item(_TWO, [_policy(1200)], aset=aset))
    assert "行李免费转运" in r["labels"], r.get("labels")


def test_free_transfer_overrides_freelug_inference():
    """三态优先级收口：nt=31 FreeLuggage 旗标（推断）+ 显式转运词
    并存——显式真值压过推断，transferBaggage=recheck（旧行为 direct
    赢=把需转运行放进直挂筛选，决策伤害面在筛选语义）。"""
    fnotes = [{"notetype": 31, "notecnt": "FreeLuggage"}]
    aset = [{"tagarea": [{"tcode": "G_KWEBAG202311",
                          "tagcnt": "行李免费转运"}]}]
    r = _one(_item(_TWO, [_policy(1200, fnotes)], aset=aset))
    assert r.get("transferBaggage") == "recheck", r.get("transferBaggage")


def test_freelug_alone_still_direct():
    """无转运词时旗标推断律不回归：单独 nt=31 FreeLuggage →
    transferBaggage=direct（r223 收编行为保持）。"""
    fnotes = [{"notetype": 31, "notecnt": "FreeLuggage"}]
    r = _one(_item(_TWO, [_policy(1200, fnotes)]))
    assert r.get("transferBaggage") == "direct", r.get("transferBaggage")


def test_explicit_direct_beats_recheck_unchanged():
    """政策级显式直挂（nt=10 行李直达）压过显式转运词：显式>显式
    按源权威序（政策级>item 层），现行行为保持。"""
    fnotes = [{"notetype": 10, "notecnt": "航变免费退改|行李直达"}]
    aset = [{"tagarea": [{"tcode": "G_KWEBAG202311",
                          "tagcnt": "行李免费转运"}]}]
    r = _one(_item(_TWO, [_policy(1200, fnotes)], aset=aset))
    assert r.get("transferBaggage") == "direct", r.get("transferBaggage")


def test_legacy_recheck_word_not_in_labels():
    """「行李代转运」基座行为保持：不进 labels（Soldier P2-1——合并
    分支曾把基座词一并带进 labels，与「联程值机，行李直挂」并现行
    产出矛盾词面同屏，dump 3 行实锤）。徽标语义：item 层直挂词并现
    时 direct 赢（显式>显式按层内裁决），「需转运」徽标不在场。"""
    aset = [{"tagarea": [
        {"tcode": "G_HETZZMTY", "tagcnt": "行李代转运"},
        {"tcode": "G_KWEBAG202311", "tagcnt": "联程值机，行李直挂"}]}]
    r = _one(_item(_TWO, [_policy(1200)], aset=aset))
    assert r.get("transferBaggage") == "direct"
    assert "行李代转运" not in (r.get("labels") or ""), r.get("labels")


def test_free_transfer_word_in_labels():
    """「行李免费转运」新词进 labels（与基座词分属两档：免费是
    服务承诺增量）且 _recheck 同置——双词并存各走各的出口。"""
    aset = [{"tagarea": [
        {"tcode": "G_HETZZMTY", "tagcnt": "行李代转运"},
        {"tcode": "G_KWEBAG202311", "tagcnt": "行李免费转运"}]}]
    r = _one(_item(_TWO, [_policy(1200)], aset=aset))
    assert r.get("transferBaggage") == "recheck"
    ls = (r.get("labels") or "").split("·")
    assert "行李免费转运" in ls and "行李代转运" not in ls, ls
