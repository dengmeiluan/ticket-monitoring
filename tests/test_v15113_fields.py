# -*- coding: utf-8 -*-
"""数据层三案（渠道调研立案 + 复核裁决）：

1. ctrip aset「赠快速安检」（tcode=G_KMZZAJ）→ labels 白名单：
   中转快速安检服务承诺，三代独立 dump 复现、调研预设「复现且无
   文案即收编」条件满足；与专属休息/一次安检同族（服务承诺型稀疏
   权益词），不收则昆明中转行该权益永久缺失。

2. ctrip nt=3 资格旗标全段扫描：classinfor 元素按段舱位（冻结 dump
   cis 数==段数 222/223 直证，pid (price,grade) 段级分算佐证），资格
   旗标挂任意段都使整程不可购——首元素门在冻结 dump 旗标行漏采
   5/21（24%），「限协议」落地后零出勤的根因即旗标恒挂第二段元素。
   结构门：len(classinfor)==len(mutilstn) 才全元素扫，形态不符
   （1/223 未证形状）维持首元素宁缺勿错。词表增 LimitedPassengerNum
   →「限人数」（nt=20 载体 LimitedPassengerNumPolicy 同词既有，独立
   载体形态随同一门收编）。

3. qunar H5 行 airlineCode 派生补源：H5 无 shortCarrier（PC 专属），
   PC 软拒断供期消费面（搜索 hay/CSV 列/alerter 跨渠道补全白名单）
   航司维度全空。WB 实证 flightMark.carrier ≡ code 前缀（146/146）→
   从 code 派生（直飞首二字、中转各段首二字斜杠连写），iata2 守卫
   同律（PC shortCarrier 恢复后语义一致无需切换）。

样本形态取自生产冻结 dump（渠道调研与观测产物/
重放脚本）。运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15113_fields.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.ctrip import CtripCrawler  # noqa: E402
from crawlers.qunar import QunarCrawler  # noqa: E402

_LOG = logging.getLogger("t15113")
_CT = CtripCrawler({}, _LOG)


# ---- ctrip 样本助手（v15109b/v15105 同款形态） ----

def _ctrip_item(segs, policies, aset=None):
    it = {"mutilstn": segs, "policyinfo": policies}
    if aset is not None:
        it["aset"] = aset
    return it


def _ctrip_seg(dd, ad, flgno="CZ6981"):
    return {"dateinfo": {"ddate": dd, "adate": ad},
            "basinfo": {"flgno": flgno},
            "dportinfo": {"bsname": "", "aport": "URC"},
            "aportinfo": {"bsname": "T2", "aport": "SHA"}}


def _ci_plain(letter=None):
    cnl = [{"notetype": 2, "notecnt": letter}] if letter else []
    return {"cgrd": 0, "classNoteList": cnl}


def _ci_nt3(words):
    return {"cgrd": 0,
            "classNoteList": [{"notetype": 3, "notecnt": words}]}


def _ctrip_policy_cis(price, cis, qty=5, fnotelst=None):
    p = {"tprice": price, "quantity": qty, "drate": 5.2,
         "classinfor": cis}
    if fnotelst is not None:
        p["fnotelst"] = fnotelst
    return p


def _one(item):
    rows = _CT._extract_ctrip_flights(json.dumps([item]))
    assert rows
    return rows[0]


_D = ("2026-10-06 16:40:00", "2026-10-06 21:30:00")
_T = (("2026-10-06 16:40:00", "2026-10-06 19:20:00", "HU7518"),
      ("2026-10-06 21:10:00", "2026-10-07 00:55:00", "FM9398"))


# ---- 1. aset「赠快速安检」→ labels 白名单 ----

def test_aset_kmg_fast_security_label():
    """aset「赠快速安检」（tcode=G_KMZZAJ）→ labels：中转快速安检
    服务承诺词，与专属休息/一次安检同族白名单（tagcnt 精确等值，
    勿按 tcode 匹配以免疫换代）。"""
    aset = [{"tagarea": [{"tcode": "G_KMZZAJ", "tagcnt": "赠快速安检"}]}]
    r = _one(_ctrip_item([_ctrip_seg(*_D)],
                         [_ctrip_policy_cis(1200, [_ci_plain("Y")])],
                         aset=aset))
    assert "赠快速安检" in r["labels"]


def test_aset_kmg_with_existing_words_no_dup():
    """新词与既有白名单词同行并存：各自一次、零重复拼接。"""
    aset = [{"tagarea": [
        {"tcode": "G_KMZZAJ", "tagcnt": "赠快速安检"},
        {"tcode": "G_HETXXS", "tagcnt": "中转免费休息"}]}]
    r = _one(_ctrip_item([_ctrip_seg(*_D)],
                         [_ctrip_policy_cis(1200, [_ci_plain("Y")])],
                         aset=aset))
    ls = r["labels"].split("·")
    assert ls.count("赠快速安检") == 1
    assert ls.count("中转免费休息") == 1


# ---- 2. nt=3 资格旗标全段扫描 ----

def test_nt3_second_segment_agreement():
    """中转第二段元素挂 LimitedAirlineAgreementID：agePolicy「限协议」
    ——冻结 dump 直证旗标载体在第二段元素（HU7518/FM9398 行内最低
    票价互证），首元素门对该形态永不命中（前轮落地零出勤根因）。"""
    item = _ctrip_item(
        [_ctrip_seg(*_T[0]), _ctrip_seg(*_T[1])],
        [_ctrip_policy_cis(1890, [_ci_plain("U"),
                                  _ci_nt3("LimitedAirlineAgreementID,"
                                          "AirlineAgreementIDLimit")])])
    assert _one(item)["agePolicy"] == "限协议"


def test_nt3_second_segment_passenger_num():
    """第二段 LimitedPassengerNum →「限人数」：nt=20 载体
    （LimitedPassengerNumPolicy）同词既有，nt=3 独立载体随同一门
    收编（冻结 dump 实见 HU7518/MU8474 行）。"""
    item = _ctrip_item(
        [_ctrip_seg(*_T[0]), _ctrip_seg(*_T[1])],
        [_ctrip_policy_cis(1864, [_ci_plain("U"),
                                  _ci_nt3("LimitedCardType,"
                                          "LimitedPassengerNum,"
                                          "LimitedAge")])])
    assert _one(item)["agePolicy"] == "限年龄·限卡支付·限人数"


def test_nt3_both_segments_all_words_join():
    """两段各自旗标按段序「·」拼接；单元素内多映射词全收（每词独立
    硬门槛，词表序内敛、段序外扩）。"""
    item = _ctrip_item(
        [_ctrip_seg(*_T[0]), _ctrip_seg(*_T[1])],
        [_ctrip_policy_cis(2860, [
            _ci_nt3("LimitedCtripMemberShip,LimitedCardType"),
            _ci_nt3("LimitedAirlineMembership")])])
    assert _one(item)["agePolicy"] == "限携程会员·限卡支付·限航司会员"


def test_nt3_nt20_first_then_segments():
    """nt=20 年龄限制与两段 nt=3 并存：限学生在最前（既有律），
    段词随后按段序。"""
    item = _ctrip_item(
        [_ctrip_seg(*_T[0]), _ctrip_seg(*_T[1])],
        [_ctrip_policy_cis(
            1860,
            [_ci_plain("U"),
             _ci_nt3("LimitedAirlineAgreementID")],
            fnotelst=[{"notetype": 20,
                       "notecnt": "2767_LimitedStudentPolicy"}])])
    assert _one(item)["agePolicy"] == "限学生·限协议"


def test_nt3_same_word_across_segments_dedupe():
    """同词面两段重复：落一次（冻结 dump 同词跨段形态防重复拼接）。"""
    item = _ctrip_item(
        [_ctrip_seg(*_T[0]), _ctrip_seg(*_T[1])],
        [_ctrip_policy_cis(1864, [_ci_nt3("LimitedCardType"),
                                  _ci_nt3("LimitedCardType")])])
    assert _one(item)["agePolicy"] == "限卡支付"


def test_nt3_shape_mismatch_first_element_only():
    """结构门反例：cis 数 != 段数（直飞行双元素未证形状 1/223）——
    维持首元素门，第二元素旗标不采（宁缺勿错，防未证形状错挂）。"""
    item = _ctrip_item(
        [_ctrip_seg(*_D)],
        [_ctrip_policy_cis(1200, [_ci_plain("Y"),
                                  _ci_nt3("LimitedAirlineAgreementID")])])
    r = _one(item)
    assert "限协议" not in (r.get("agePolicy") or "")


def test_nt3_direct_single_element_unchanged():
    """直飞单元素既有行为零扰动（v15109b 同款回归钉）。"""
    item = _ctrip_item(
        [_ctrip_seg(*_D)],
        [_ctrip_policy_cis(1860,
                           [_ci_nt3("LimitedAirlineAgreementID")])])
    assert _one(item)["agePolicy"] == "限协议"


# ---- 3. qunar H5 airlineCode 派生补源 ----

def _h5_direct(code="9C8846"):
    return {"minPrice": 1200, "code": code,
            "mixFlightName": "春秋" + code,
            "binfo": {"depTime": "16:40", "arrTime": "21:30",
                      "depDate": "2026-10-06", "arrDate": "2026-10-06"},
            "extparams": "{}"}


def _h5_trans(code="HU7518/FM9398"):
    return {"minPrice": 1864, "code": code,
            "binfo1": {"depTime": "16:40", "arrTime": "23:55",
                       "depDate": "2026-10-06", "arrDate": "2026-10-06"},
            "binfo2": {"depTime": "21:10", "arrTime": "00:55",
                       "depDate": "2026-10-06", "arrDate": "2026-10-07"},
            "extparams": "{}"}


def test_qunar_h5_airlinecode_direct():
    """直飞行从 code 首二字派生（flightMark.carrier ≡ code 前缀
    146/146 实证的可派生性；iata2 守卫）。"""
    rows = QunarCrawler._extract_flights_obj([_h5_direct("9C8846")])
    assert rows[0]["airlineCode"] == "9C"


def test_qunar_h5_airlinecode_transfer_join():
    """中转行各段首二字斜杠连写（跨渠道键形态与 PC shortCarrier
    单值/其他渠道中转多值协议对齐）。"""
    rows = QunarCrawler._extract_flights_obj([_h5_trans()])
    assert rows[0]["airlineCode"] == "HU/FM"


def test_qunar_h5_airlinecode_guard():
    """iata2 守卫：非二字码前缀（小写/截断不足）落空串不落键值
    （宁缺勿错同律；键仍在，str 空串口径同邻键 depAirportCode）。"""
    rows = QunarCrawler._extract_flights_obj([_h5_direct("ab1234")])
    assert rows[0]["airlineCode"] == ""
