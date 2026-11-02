# -*- coding: utf-8 -*-
"""本轮三案（调研 _scratch/r106_fields_a.md / r106_fields_b.md）：

N2 qunar：H5 priceBottomLabels 白名单追加「春秋绿翼会员专享丨超惠飞」
——PC 软拒后 H5 主路径白名单不含该词，DB 直证 09-29 起绿翼行落库归零
（词面全史 666 记录/1922 明细单一词面零漂移，41 明细=当轮最低价=比价
失真实锤）。全词精确匹配零误杀；勿用「会员专享」子串防带价 churn 词。

N1 ctrip：classNoteList nt=3 LimitedCardType（限指定卡类型支付资格价）
——三日在场 + 09-25 决策面两行最低价互证（MU5633/MU5699，tprice 即
行内最低有票价）。收编 agePolicy 词族映射「限卡支付」，全词精确匹配
零误杀；「你看到的最低价买不了」家族第 4 成员。

tongcheng：中转行 lay2dep（第二段起飞时刻）——fps[].ss[1].dt 段级
结构化真值，两代 dump 48/48 在场、53/53 与已采 layover 精确互证；
qunar/fliggy 同槽 100% 出勤而 tongcheng 24,925 中转行零覆盖（该渠道
唯一缺口）。守卫两条：len(segs)>=2（既有硬守卫）+ HH:MM 形校验，
解析失败不落键。webui/report 渲染门既有，落键即渲染。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15106_fields.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.ctrip import CtripCrawler  # noqa: E402
from crawlers.qunar import QunarCrawler  # noqa: E402
from crawlers.tongcheng import TongchengCrawler  # noqa: E402

_LOG = logging.getLogger("t15106")
_CT = CtripCrawler({}, _LOG)


# ---- N2 qunar：H5 labels 白名单追加春秋绿翼会员专享 ----

def test_qunar_h5_greenwing_label_whitelisted():
    """「春秋绿翼会员专享丨超惠飞」全词入白名单：H5 主路径时代
    绿翼资格价不再断供（PC 软拒期间该词唯一入口）。"""
    f = {"listLabel": {"priceBottomLabels": [
        {"text": "春秋绿翼会员专享丨超惠飞"}]}}
    out = QunarCrawler._h5_labels_of(f, {})
    assert "春秋绿翼会员专享丨超惠飞" in out


def test_qunar_h5_greenwing_with_ordinary_labels():
    """绿翼词与普通白名单词同列表：两词并出、词序保持。"""
    f = {"listLabel": {"priceBottomLabels": [
        {"text": "宠物友好"},
        {"text": "春秋绿翼会员专享丨超惠飞"}]}}
    out = QunarCrawler._h5_labels_of(f, {})
    assert "宠物友好" in out
    assert "春秋绿翼会员专享丨超惠飞" in out


def test_qunar_h5_price_churn_word_not_whitelisted():
    """「XX会员专享￥99」带价 churn 词不入（全词匹配防子串误入）。"""
    f = {"listLabel": {"priceBottomLabels": [
        {"text": "会员专享￥99"}]}}
    assert QunarCrawler._h5_labels_of(f, {}) == ""
    # 真实近失形态：白名单词「春秋绿翼会员专享丨超惠飞」的航司前缀
    # 带价变体（生产 dump 实锤 churn 词面）——词干/剥价前缀类收编
    # 变异（如取「丨」前词干做包含或前缀匹配）会被此断言打红
    f2 = {"listLabel": {"priceBottomLabels": [
        {"text": "春秋绿翼会员专享￥99"}]}}
    assert QunarCrawler._h5_labels_of(f2, {}) == ""


# ---- N1 ctrip：nt=3 LimitedCardType → agePolicy「限卡支付」 ----

def _ctrip_seg(dd, ad, flgno="MU5633"):
    return {"dateinfo": {"ddate": dd, "adate": ad},
            "basinfo": {"flgno": flgno},
            "dportinfo": {"bsname": "", "aport": "URC"},
            "aportinfo": {"bsname": "T2", "aport": "SHA"}}


def _ctrip_policy(price=1200, ci=None, qty=5):
    p = {"tprice": price, "quantity": qty, "drate": 5.2}
    if ci is not None:
        p["classinfor"] = [ci]
    return p


def _ctrip_one(item):
    rows = _CT._extract_ctrip_flights(json.dumps([item]))
    assert rows
    return rows[0]


def test_ctrip_limited_card_type():
    """nt=3 逗号串含 LimitedCardType：agePolicy=「限卡支付」——
    限指定卡类型支付的资格价，误购支付失败出不了票。"""
    ci = {"cgrd": 0,
          "classNoteList": [{"notetype": 3,
                             "notecnt": "LockPrice,LimitedCardType"}]}
    r = _ctrip_one({"pid": "", "mutilstn": [_ctrip_seg(
        "2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        "policyinfo": [_ctrip_policy(price=2410, ci=ci)]})
    assert r["agePolicy"] == "限卡支付"


def test_ctrip_limited_card_type_alone():
    """分元素形态（单 notecnt 即该词）：同收。"""
    ci = {"cgrd": 0,
          "classNoteList": [{"notetype": 3, "notecnt": "LimitedCardType"}]}
    r = _ctrip_one({"pid": "", "mutilstn": [_ctrip_seg(
        "2026-10-06 16:40:00", "2026-10-06 21:30:00")],
        "policyinfo": [_ctrip_policy(price=1200, ci=ci)]})
    assert r["agePolicy"] == "限卡支付"


# ---- tongcheng：中转行 lay2dep（第二段起飞时刻） ----

def _tc_fp(ss_extra=None):
    ss = [{"fn": "CZ6981", "dt": "2026-10-05 13:20",
           "at": "2026-10-05 16:05", "aat": "T3", "dac": "URC",
           "aac": "YZY"},
          {"fn": "MU5700", "dt": "2026-10-05 18:20",
           "at": "2026-10-05 21:30", "dat": "T5", "dac": "YZY",
           "aac": "PVG"}]
    if ss_extra is not None:
        ss = ss_extra
    return {"dt": "2026-10-05 13:20", "at": "2026-10-05 21:30",
            "sd": "2h45m", "td": "8h10m", "sc": "张掖", "ss": ss,
            "lps": [{"atp": 1800, "brs": [{"al": 3}]}]}


def _tc_rows(fp):
    rows = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp]}}))
    assert rows
    return rows[0]


def test_tongcheng_transfer_lay2dep():
    """ss[1].dt 段级真值 → lay2dep=「18:20」（HH:MM）：
    「第二段什么时候再飞」，与已采 layover（停多久）互补。"""
    r = _tc_rows(_tc_fp())
    assert r["lay2dep"] == "18:20"


def test_tongcheng_transfer_lay2dep_seconds_form():
    """dt 带秒尾巴（"2026-10-05 18:20:00" 形态）：切片后仍 18:20。"""
    fp = _tc_fp()
    fp["ss"][1]["dt"] = "2026-10-05 18:20:00"
    assert _tc_rows(fp)["lay2dep"] == "18:20"


def test_tongcheng_transfer_lay2dep_bad_shape_dropped():
    """dt 缺失/非时刻形：不落键（宁缺勿错）。"""
    fp = _tc_fp()
    del fp["ss"][1]["dt"]
    assert "lay2dep" not in _tc_rows(fp)
    fp2 = _tc_fp()
    fp2["ss"][1]["dt"] = "不合格"
    assert "lay2dep" not in _tc_rows(fp2)


# ---- 呈现词面钉（title 帮助文案与新词同步，防静默漂移） ----

def test_webui_agepolicy_title_mentions_card_type():
    """agePolicy ⚠ 徽标 title 词面覆盖「指定卡类型」：
    限卡支付资格价入 agePolicy 族后帮助文案同步。"""
    import webui
    assert "指定卡类型" in webui.PAGE


def test_webui_fltbtn_title_carries_legend():
    """≤540 图例隐藏后语义并入 fltBtn title：三档关键词在场。"""
    import webui
    assert "档位图例" in webui.PAGE
    assert "深绿=真达标" in webui.PAGE
    assert "琥珀=擦边" in webui.PAGE
