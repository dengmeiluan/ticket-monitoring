# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r237_fields.py
- tests/test_r247_fields.py
- tests/test_r275_fields.py
- tests/test_v15114_fields.py
- tests/test_v1556_fields.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import json
import logging
import os
import sys

from crawlers.ctrip import CtripCrawler
from crawlers.fliggy import FliggyCrawler
from crawlers.qunar import QunarCrawler
from crawlers.tongcheng import TongchengCrawler


# ---- merged from tests/test_r237_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("r237")
_QC = QunarCrawler({}, _LOG)


def _h5_f(texts):
    """H5 行最小载体：listLabel.priceBottomLabels 词面列表。"""
    return {"listLabel": {"priceBottomLabels": [{"text": t} for t in texts]}}


def test_h5_whitelist_free_wifi():
    """「免费上网」服务承诺型权益随 H5 白名单采入 labels。"""
    out = QunarCrawler._h5_labels_of(_h5_f(["免费上网"]))
    assert "免费上网" in out


def test_h5_whitelist_marketing_churn_still_excluded():
    """白名单增词不放松营销 churn 面：比价/降价类词与资格价词的
    变体/带价形态静默不采（全词精确匹配，子串放宽会放进 churn 词）。
    注意：变体钉是收编前置闸而非永拒钉——渠道未来真出「老会员专享」
    等新资格价词时，携 dump 证据链（家族律+跨轮复现）同轮收编并改钉。
    r322 改写：「可再减¥N」携三要素证据链（频率形态 205-241/份→
    1/442 稀疏+数值自洽 2204=2350−146+页面公开承诺）翻案收编为
    透明标记（正则臂精确形态），移出本排除清单——其排除面由
    test_r322_fields 变体钉承接。"""
    out = QunarCrawler._h5_labels_of(
        _h5_f(["比直飞省¥30", "精选低价",
               "老会员专享", "黑钻会员专享", "新会员专享价",
               "体验价·限时"]))
    assert out == ""


def test_h5_whitelist_member_and_trial_price():
    """「新会员专享」「体验价」资格价词随 H5 白名单采入 labels：
    同槽「春秋绿翼会员专享丨超惠飞」家族先例在采；资格价互证形态
    （同班双价行/五价背离）在全部存量 dump 零在场=该载荷结构性
    不携带，按家族律+跨轮独立复现双要件收编（ctrip「老客专享」
    同族）；载体行恒为行内最低价，不采则读者把活动价当全民价。"""
    assert "新会员专享" in QunarCrawler._h5_labels_of(_h5_f(["新会员专享"]))
    assert "体验价" in QunarCrawler._h5_labels_of(_h5_f(["体验价"]))


def test_h5_whitelist_member_price_priority_over_service_word():
    """资格价词与既有白名单词同行共存：按渠道原序入 2 槽，无挤出异常。"""
    out = QunarCrawler._h5_labels_of(
        _h5_f(["免费上网", "体验价"]))
    assert out == "免费上网·体验价"


def _pc_flight(b1=None, b2=None, **top):
    """PC wbdflightlist 行最小载体（data.flights 普通数组形态）。"""
    f = {"minPrice": 1200, "code": "MU2772",
         "binfo1": dict({"depTime": "08:00", "arrTime": "11:30",
                         "date": "2026-10-05", "shortCarrier": "MU",
                         "airCode": "2772"}, **(b1 or {})),
         "binfo2": b2 or {}}
    f.update(top)
    return f


def _pc_text(flights):
    import json as _json
    return _json.dumps({"data": {"flights": flights}}, ensure_ascii=False)


def test_pc_stoptime_empty_not_landed():
    """PC 行 stopTime 无值不落键（直飞行无经停概念）：H5 段
    `if stop_time:` 门同族——PC 复活首日 397 行空串平铺的卫生收口。"""
    rows = QunarCrawler._parse_pc_flights(_pc_text([_pc_flight()]), "2026-10-05")
    assert rows and "stopTime" not in rows[0]


def test_pc_stoptime_valued_still_landed():
    """经飞行 stopTime 有值照落（门不得误杀真值）。"""
    rows = QunarCrawler._parse_pc_flights(
        _pc_text([_pc_flight(b1={"stopTime": "1小时5分"})]), "2026-10-05")
    assert rows and rows[0].get("stopTime") == "1小时5分"


def test_pc_avgdelay_minus1_is_true_value():
    """avgDelay -1 真值族备案钉：PC 复活后 lateTime 连续值域
    -37~+17 在场，-1=历史平均提前 1 分钟（嵌在 -3/-2 之间），
    非 0 式占位——防未来「卫生化」按负值占位误吞真值。"""
    rows = QunarCrawler._parse_pc_flights(
        _pc_text([_pc_flight(b1={"lateTime": "-1"})]), "2026-10-05")
    assert rows and rows[0].get("avgDelay") == -1


# ---- merged from tests/test_r247_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


# ---- merged from tests/test_r275_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("r275")
_TC = TongchengCrawler({}, _LOG)
_CT = CtripCrawler({}, _LOG)


# ---- TC-1：trendHoliday 裸班/休词面 ----

def _tc_flight(**kw):
    f = {"fn": "CZ6981", "asn": "南航",
         "dt": "2026-10-06 18:30", "at": "2026-10-06 23:40",
         "td": "5h10m",
         "lps": [{"atp": 1500, "brs": [{"al": 5}]}]}
    f.update(kw)
    return f


def test_tc_trend_holiday_bare_tag_landed():
    """TC-1：holidayName 空 + tag='班'/'休' 点位 → 裸 tag 词面落
    trendHoliday（调休班日/休息日的价格解释变量）；带名点位原词面
    （名·tag / 裸名）与无标注点位（键不落）零回归。"""
    data = {"fl": [_tc_flight()],
            "pc": [{"dd": "2026-10-10", "lp": 840, "isHoliday": True,
                    "holidayName": "", "tag": "班"},
                   {"dd": "2026-10-06", "lp": 700, "isHoliday": True,
                    "holidayName": "", "tag": "休"},
                   {"dd": "2026-09-27", "lp": 916, "isHoliday": True,
                    "holidayName": "中秋节", "tag": "休"},
                   {"dd": "2026-09-28", "lp": 900}]}
    rows = _TC._extract_flights(json.dumps({"data": data}))
    assert rows and rows[0].get("trendGo"), rows
    assert rows[0]["trendHoliday"] == [["10-10", "班"],
                                       ["10-06", "休"],
                                       ["09-27", "中秋节·休"]], rows[0]


def test_tc_trend_holiday_no_annotated_points_absent():
    """全部点位无班/休/名标注 → 键不落（无值不落键律不回归）。"""
    data = {"fl": [_tc_flight()],
            "pc": [{"dd": "2026-09-28", "lp": 900},
                   {"dd": "2026-09-29", "lp": 910, "tag": ""}]}
    rows = _TC._extract_flights(json.dumps({"data": data}))
    assert rows and "trendHoliday" not in rows[0], rows


# ---- TC-2：connection 段级共享旗标 isf ----

def _tc_fp(**kw):
    fp = {"dt": "2026-10-05 13:20", "at": "2026-10-05 21:30",
          "sd": "2h45m", "td": "8h10m", "sc": "张掖",
          "ss": [{"fn": "CZ6981", "dt": "2026-10-05 13:20",
                  "at": "2026-10-05 16:05"},
                 {"fn": "SC5414", "dt": "2026-10-05 18:20",
                  "at": "2026-10-05 21:30"}],
          "lps": [{"atp": 1500, "brs": [{"al": 5}],
                   "pts": [{"td": "6.8折经济舱"}]}]}
    fp.update(kw)
    return fp


def _fps(fp):
    return json.dumps({"data": {"fps": [fp]}}, ensure_ascii=False)


def test_tc_conn_seg_shared_flag_label():
    """TC-2：二段 ss[].isf='True' → labels 含「二段共享承运」（词面
    按段序；dump 实证 SC5414 形态）。"""
    fp = _tc_fp()
    fp["ss"][1]["isf"] = "True"
    rows = _TC._extract_transfer_flights(_fps(fp), "")
    assert rows, "样本应产出至少一行"
    ls = (rows[0].get("labels") or "").split("·")
    assert "二段共享承运" in ls, rows[0].get("labels")


def test_tc_conn_seg_shared_false_absent():
    """isf='False'（10-15 代 42 处主流形态）→ labels 零共享词不落
    （无值不落键律）。"""
    fp = _tc_fp()
    fp["ss"][0]["isf"] = "False"
    fp["ss"][1]["isf"] = "False"
    rows = _TC._extract_transfer_flights(_fps(fp), "")
    assert rows and "labels" not in rows[0], rows[0]


def test_tc_conn_seg_shared_first_seg_word():
    """一段 True → 词面「一段共享承运」按段序生成（渠道对段位静默
    扩展时词面自动正确，不出现错挂的「二段」）。"""
    fp = _tc_fp()
    fp["ss"][0]["isf"] = "True"
    rows = _TC._extract_transfer_flights(_fps(fp), "")
    assert rows, "样本应产出至少一行"
    ls = (rows[0].get("labels") or "").split("·")
    assert "一段共享承运" in ls, rows[0].get("labels")
    assert "二段共享承运" not in ls, rows[0].get("labels")


def test_tc_conn_seg_shared_third_seg_word():
    """三段 True → 词面「三段共享承运」（段序表边界内最深档；
    更深段位宁缺勿错不生成词面）。"""
    fp = _tc_fp()
    fp["ss"].append({"fn": "MU5700", "dt": "2026-10-05 22:00",
                     "at": "2026-10-06 01:00", "isf": "True"})
    fp["ss"][0]["isf"] = "True"
    fp["ss"][1]["isf"] = "True"
    rows = _TC._extract_transfer_flights(_fps(fp), "")
    assert rows, "样本应产出至少一行"
    ls = (rows[0].get("labels") or "").split("·")
    assert "一段共享承运" in ls and "二段共享承运" in ls \
        and "三段共享承运" in ls, rows[0].get("labels")


def test_tc_conn_shared_precedes_fwbqs():
    """共享承运与服务承诺并存：承运商信息（决策级）在前、fwbqs 服务
    承诺在后；isf 非 'True' 精确值（'true' 小写/其余）不触发。"""
    fp = _tc_fp()
    fp["ss"][1]["isf"] = "True"
    fp["lps"][0]["fwbqs"] = [{"td": "第1程：免费上网"}]
    rows = _TC._extract_transfer_flights(_fps(fp), "")
    assert rows, "样本应产出至少一行"
    ls = (rows[0].get("labels") or "").split("·")
    assert ls.index("二段共享承运") < ls.index("第1程：免费上网"), ls
    fp2 = _tc_fp()
    fp2["ss"][1]["isf"] = "true"   # 渠道实证形态恒 'True' 首字母大写
    rows2 = _TC._extract_transfer_flights(_fps(fp2), "")
    assert "labels" not in rows2[0] or "共享承运" not in rows2[0]["labels"], \
        rows2[0].get("labels")


# ---- CT-1：ctrip aset 地域品牌词第四件 ----

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


def test_ct_aset_wanmei_lounge_label():
    """CT-1：aset「享“皖美中转”休息室服务」（G_HFEZZXXS）→ labels：
    地域品牌词第四件（郑州/昆明/兰州同族对称），载体行读者只见通用
    fcode 词，品牌词零出口则永久缺失。"""
    aset = [{"tagarea": [{"tcode": "G_HFEZZXXS",
                          "tagcnt": "享“皖美中转”休息室服务"}]}]
    r = _one(_item(_TWO, [_policy(1200)], aset=aset))
    assert "享“皖美中转”休息室服务" in r["labels"], r.get("labels")


def test_ct_wanmei_blocks_fcode_lounge_dupe():
    """皖美词含「休息室」子串 → fcode _5「赠中转休息室」不重拼
    （同义近域去重门既有行为随新词复验）。"""
    aset = [{"tagarea": [{"tcode": "G_HFEZZXXS",
                          "tagcnt": "享“皖美中转”休息室服务"}]}]
    r = _one(_item(_TWO, [_policy(1200)], aset=aset,
                   fcode="transitServiceId_5"))
    ls = r["labels"].split("·")
    assert ls.count("享“皖美中转”休息室服务") == 1, ls
    assert "赠中转休息室" not in ls, ls


# ---- merged from tests/test_v15114_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t15114")


# ---- 样本助手（v15110 同款形态） ----

def _tc_direct(ac="MU"):
    f = {"fn": "MU5700", "dt": "2026-10-05 13:20",
         "at": "2026-10-05 16:05", "asn": "东方航空",
         "lps": [{"atp": 1500, "brs": [{"al": 5}],
                  "pts": [{"td": "6.8折经济舱"}]}]}
    if ac is not None:
        f["ac"] = ac
    return {"data": {"fl": [f]}}


def _tc_direct_rows(payload):
    rows = TongchengCrawler._extract_flights(json.dumps(payload))
    assert rows
    return rows[0]


def _tc_trans_fp(ss):
    return {"dt": "2026-10-05 13:20", "at": "2026-10-05 21:30",
            "sd": "2h45m", "td": "8h10m", "sc": "张掖", "ss": ss,
            "lps": [{"atp": 1500, "brs": [{"al": 5}],
                     "pts": [{"td": "6.8折经济舱"}]}]}


def _tc_trans_rows(fp):
    rows = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp]}}))
    assert rows
    return rows[0]


# ---- 直飞 book1：fl[].ac ----

def test_tc_direct_airlinecode():
    """直飞行 ac → airlineCode（与 dasn/aasn 同层独立键）。"""
    r = _tc_direct_rows(_tc_direct("MU"))
    assert r["airlineCode"] == "MU"


def test_tc_direct_airlinecode_digit_carrier():
    """数字参位航司二字码合法（3U 川航/G5 华夏，iata2 值域）。"""
    r = _tc_direct_rows(_tc_direct("3U"))
    assert r["airlineCode"] == "3U"


def test_tc_direct_guard_dirty_values():
    """iata2 守卫：小写/三位/缺键/None 一律落空串不占位
    （键仍在，str 空串口径同邻键 depAirportCode）。"""
    assert _tc_direct_rows(_tc_direct("mu"))["airlineCode"] == ""
    assert _tc_direct_rows(_tc_direct("MU5"))["airlineCode"] == ""
    assert _tc_direct_rows(_tc_direct(None))["airlineCode"] == ""


# ---- 中转 connection：ss[0].ac 首段 ----

def test_tc_trans_airlinecode_first_segment():
    """中转行取 ss[0].ac（首段出发=整体出发航司，与 code=ss[].fn
    联接、asn 取首段同律）；段序抖动时首段仍是主承运语义。"""
    ss = [{"fn": "CZ6981", "dt": "2026-10-05 13:20",
           "at": "2026-10-05 16:05", "ac": "CZ"},
          {"fn": "MU5700", "dt": "2026-10-05 18:20",
           "at": "2026-10-05 21:30", "ac": "MU"}]
    r = _tc_trans_rows(_tc_trans_fp(ss))
    assert r["airlineCode"] == "CZ"


def test_tc_trans_guard_missing_ac():
    """中转段无 ac（历史 dump 形态守卫反例）：落空串不占位。"""
    ss = [{"fn": "CZ6981", "dt": "2026-10-05 13:20",
           "at": "2026-10-05 16:05"},
          {"fn": "MU5700", "dt": "2026-10-05 18:20",
           "at": "2026-10-05 21:30", "ac": "MU"}]
    r = _tc_trans_rows(_tc_trans_fp(ss))
    assert r["airlineCode"] == ""


# ---- merged from tests/test_v1556_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t1556")
_CT = CtripCrawler({}, _LOG)


# ---- qunar：binfo.name 机型补采 ----

def _h5_direct(**binfo):
    f = {"minPrice": 1200, "code": "9C8846", "mixFlightName": "春秋9C8846",
         "binfo": {"depTime": "16:40", "arrTime": "21:30",
                   "depDate": "2026-10-06", "arrDate": "2026-10-06"},
         "extparams": "{}"}
    f["binfo"].update(binfo)
    return f


def test_qunar_h5_plane_from_binfo_name():
    """binfo.name[1] 是 JSON 真值机型「波音737(中)」（dump 直飞 83%
    在场、值域 4 种干净形态）；体量括号同步落 planeSize。"""
    rows = QunarCrawler._extract_flights_obj(
        [_h5_direct(name=["春秋", "波音737(中)"])])
    assert rows[0]["plane"] == "波音737(中)"
    assert rows[0]["planeSize"] == "中型机"
    rows2 = QunarCrawler._extract_flights_obj(
        [_h5_direct(name=["南航", "空客330(大)"])])
    assert rows2[0]["plane"] == "空客330(大)"
    assert rows2[0]["planeSize"] == "大型机"


def test_qunar_h5_plane_rejects_dirty_forms():
    """fullmatch 锚定：无体量形态「空客330」/带尾缀「737-800」「波音
    737MAX8」/共享行实际承运号「HO1256」一律不落（宁缺勿错）。"""
    for dirty in (["南航", "空客330"], ["厦航", "737-800"],
                  ["吉祥", "HO1256"], ["春秋", "波音737MAX8"],
                  ["春秋"], None):
        rows = QunarCrawler._extract_flights_obj(
            [_h5_direct(name=dirty)])
        # r242 收口后脏形=整键缺席（旧钉钉的是空串落库形态）
        assert "plane" not in rows[0], (dirty, rows[0])
        assert "planeSize" not in rows[0], dirty


def test_qunar_h5_labels_age_limit_tops():
    """年龄限制硬性购买资格置顶收（限N 岁买错无法值机），正则 ^限\\d
    变体整句透传；截断 [:2] 下不被营销词挤掉。"""
    f = _h5_direct()
    f["listLabel"] = {"priceBottomLabels": [
        {"text": "已优惠￥7"},
        {"text": "限55岁(含)以上的旅客购买"},
        {"text": "出票后2小时内错购退票"}]}
    rows = QunarCrawler._extract_flights_obj([f])
    assert rows[0]["labels"].startswith("限55岁")
    assert "出票后2小时内错购退票" in rows[0]["labels"]
    # 变体：限N-N人·且需N周岁 / 限16-23(含)周岁预定
    f2 = _h5_direct()
    f2["listLabel"] = {"priceBottomLabels": [
        {"text": "限16-23(含)周岁的旅客预定"}]}
    rows2 = QunarCrawler._extract_flights_obj([f2])
    assert rows2[0]["labels"] == "限16-23(含)周岁的旅客预定"


def test_qunar_h5_labels_zhengzhou_rights():
    """「郑州机场中转权益」服务承诺词入白名单（dump 5-9 次/份中转行）；
    非白名单营销词维持不采。"""
    f = _h5_direct()
    f["listLabel"] = {"priceBottomLabels": [
        {"text": "中转低价"}, {"text": "郑州机场中转权益"}]}
    rows = QunarCrawler._extract_flights_obj([f])
    assert rows[0]["labels"] == "郑州机场中转权益"


# ---- tongcheng：段级换乘楼配对 + 改期日历 ----

def test_tongcheng_transfer_terminals_pair():
    """中转楼=ss[0].aat（段级真值，fp 层是整行口径）、二段出发楼=
    ss[1].dat 配对成换乘路径；ss[1].dat 空串（张掖例）无值不落键。"""
    fp = {"dt": "2026-10-06 08:00", "at": "2026-10-07 18:00",
          "sd": "2h15m", "td": "9h30m", "sc": "西安",
          "ss": [{"fn": "CZ6981", "aat": "T3"},
                 {"fn": "MU5700", "dat": "T5"}],
          "lps": [{"atp": 1800, "brs": [{"al": 3}]}]}
    rows = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp]}}))
    assert rows[0]["transTerminal"] == "T3"
    assert rows[0]["transDepTerminal"] == "T5"
    fp2 = dict(fp, ss=[{"fn": "CZ6981", "aat": "T1"},
                       {"fn": "MU5700", "dat": ""}])
    rows2 = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp2]}}))
    assert rows2[0]["transTerminal"] == "T1"
    assert "transDepTerminal" not in rows2[0]


def test_tongcheng_trendgo_mounts_on_lowest():
    """data.pc[] 改期日历按 qunar trendGo 同协议落当轮最低价行：坏点
    （dd 形态/价越界）弃；[[MM-DD,价],…] 形态。r254 起 hlp 翻案采入
    同槽落 trendBiz（原「语义未证不采」备案被 inHighCabin 三点全等
    推翻）——样本含 hlp 时同行必带 trendBiz（孤儿键转正钉面翻转律）。"""
    fl = [{"fn": "9C8846", "dt": "2026-10-06 16:40", "at": "2026-10-06 21:30",
           "atp": 2200, "lps": [{"atp": 2200, "brs": [{"al": 3}]}]},
          {"fn": "CZ6981", "dt": "2026-10-06 08:00", "at": "2026-10-06 12:00",
           "atp": 1800, "lps": [{"atp": 1800, "brs": [{"al": 3}]}]}]
    pc = [{"dd": "2026-09-29", "lp": 750, "hlp": 2350},
          {"dd": "2026-10-6", "lp": 800},          # 坏点：dd 非零补形态
          {"dd": "2026-10-07", "lp": 20},          # 坏点：价越界
          {"dd": "2026-10-08"},                    # 坏点：缺 lp
          {"dd": "2026-10-06", "lp": 1800}]
    rows = TongchengCrawler._extract_flights(json.dumps(
        {"data": {"fl": fl, "pc": pc}}))
    lo = min(rows, key=lambda f: f["price"])
    assert lo["code"] == "CZ6981"
    assert lo["trendGo"] == [["09-29", 750], ["10-06", 1800]]
    assert lo["trendBiz"] == [["09-29", 2350]]
    hi = next(r for r in rows if r["code"] == "9C8846")
    assert "trendGo" not in hi
    assert "trendBiz" not in hi


# ---- fliggy：无餐食标签 + 中转行一期解析 ----

def test_fliggy_meal_negative_label():
    """机型行同行尾「无餐食」负向标签（has-food-label，出现即真）落
    meal 既有键；无标签行不落（有餐食不打标）。"""
    txt = ("春秋9C7006\n中型机 320 无餐食\n15:15\n21:30\n"
           "乌鲁木齐天山国际机场\n虹桥国际机场T1\n¥620 5.0折")
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-05")
    hit = [r for r in rows if r.get("code") == "9C7006"]
    assert hit and hit[0]["meal"] == "无餐食"
    txt2 = "东航MU8369\n中型机 737\n15:15\n16:10\n" \
           "乌鲁木齐天山国际机场\n虹桥国际机场T1\n¥920 5.0折"
    rows2 = FliggyCrawler._parse_pc_text(txt2, "2026-10-05")
    assert rows2 and "meal" not in rows2[0]


def test_fliggy_transfer_row_full_parse():
    """中转块一期：二段行头+机型行 → 4 条日期时刻行 → 出发机场 →
    「城市中转」定证 → 到达机场 → 价/税/余票。合并 code「A/B」、
    时刻取 _dtl 首末、衔接=首段落−二段起（transInfo 真值豁免）、
    跨天按日期差、机建燃油行不夺主价。"""
    txt = "\n".join([
        "春秋9C7006", "中型机 320",          # 首段（pend）
        "春秋9C7310", "中型机 320 无餐食",   # 二段（cur）
        "10月05日 15:15", "10月05日 19:05",  # 首段起/落
        "10月06日 06:05", "10月06日 07:55",  # 二段起/落
        "乌鲁木齐天山国际机场", "石家庄中转", "虹桥国际机场T1",
        "100.0%", "约17小时",
        "¥2060 5.0折", "¥240机建燃油", "少量", "订票",
    ])
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-05")
    assert len(rows) == 1, rows
    r = rows[0]
    assert r["code"] == "9C7006/9C7310"
    assert r["name"] == "春秋9C7006"
    assert r["depTime"] == "15:15" and r["arrTime"] == "07:55"
    assert r["depDate"] == "2026-10-05" and r["arrDate"] == "2026-10-06"
    assert r["crossDayDesc"] == "+1天"
    assert r["transCity"] == "石家庄"
    assert r["layover"] == 660 and r["layoverSrc"] == "transInfo"
    assert r["lay2dep"] == "06:05"
    assert r["price"] == 2060 and r["transferTax"] == 240
    assert r["fewTicket"] == "少量"
    assert r["meal"] == "无餐食"
    assert r["depAirport"] == "乌鲁木齐天山国际机场"
    assert r["arrAirport"] == "虹桥国际机场" and r["arrTerminal"] == "T1"


def test_fliggy_transfer_tax_guard_not_alt_price():
    """税行守卫：越界值（<60）不落 transferTax，且不得被价格分支当
    副价 min 吞（¥50 若落入比价支，主价 2060→50 即脏价）。"""
    txt = "\n".join([
        "春秋9C7006", "中型机 320",
        "春秋9C7310", "中型机 320",
        "10月05日 15:15", "10月05日 19:05",
        "10月06日 06:05", "10月06日 07:55",
        "乌鲁木齐天山国际机场", "石家庄中转", "虹桥国际机场T1",
        "¥2060 5.0折", "¥50机建燃油", "订票",
    ])
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-05")
    assert len(rows) == 1
    assert rows[0]["price"] == 2060
    assert "transferTax" not in rows[0]


def test_fliggy_direct_rows_unaffected():
    """直飞行既有行为回归：双价行/余票/折扣/准点率分支在新分支共存下
    行为不变（中转块新分支只对「N月N日 HH:MM」「XX中转」两种新形态
    放行，直飞裸 HH:MM 序列零接触）。"""
    txt = "\n".join([
        "东航MU8369", "中型机 737", "16:40", "21:30 第2天",
        "乌鲁木齐天山国际机场", "虹桥国际机场T2", "94.5%",
        "¥920 5.0折", "少量",
    ])
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-05")
    assert len(rows) == 1
    r = rows[0]
    assert r["depTime"] == "16:40" and r["arrTime"] == "21:30"
    assert r["crossDayDesc"] == "+1天"
    assert r["prate"] == "94" and r["fewTicket"] == "少量"
    assert r["arrTerminal"] == "T2"
    assert "transCity" not in r


# ---- ctrip：aset 权益词扩充 ----

def _ctrip_item(segs, policies, aset=None):
    item = {"mutilstn": segs, "policyinfo": policies}
    if aset is not None:
        item["aset"] = aset
    return item


def _ctrip_seg(dd, ad, flgno="CZ6981"):
    return {"dateinfo": {"ddate": dd, "adate": ad},
            "basinfo": {"flgno": flgno},
            "dportinfo": {"bsname": "", "aport": "URC"},
            "aportinfo": {"bsname": "T2", "aport": "SHA"}}


def _ctrip_policy(price=1200):
    return {"tprice": price, "quantity": 5, "drate": 5.2}


def test_ctrip_labels_new_rights_words():
    """第八批扩充：中转餐饮/免费市区班车/宠物进客舱入 labels；地域
    品牌词三件已凭「载体行 0 并现+纯词无价格」复验收编（r226：不收
    则权益词永久缺失，qunar 同族先例在案——原 churn 排除依据针对
    带价营销词，与本组纯词形态不同）；中转住宿与政策级 nt=10
    同义不重复（hotel_free 既有出口）。"""
    aset = [{"tagarea": [{"tagcnt": t} for t in (
        "中转餐饮", "免费市区班车", "宠物进客舱",
        "经兰飞如意行权益", "享“豫转豫好”免费服务", "中转住宿")]}]
    item = _ctrip_item([_ctrip_seg("2026-10-06 16:40:00",
                                   "2026-10-06 21:30:00")],
                       [_ctrip_policy()], aset=aset)
    r = _CT._extract_ctrip_flights(json.dumps([item]))[0]
    assert "中转餐饮" in r["labels"]
    assert "免费市区班车" in r["labels"]
    assert "宠物进客舱" in r["labels"]
    assert "经兰飞如意行权益" in r["labels"]
    assert "享“豫转豫好”免费服务" in r["labels"]
    assert "中转住宿" not in r["labels"]   # policy 级 nt=10 既有出口


# ---- 哨兵：qunar|plane 移出死键表 + tongcheng|tterm 入白名单 ----

def test_sentinel_qunar_plane_now_observed(monkeypatch, tmp_path):
    """qunar|plane H5 有源（移出死键表）：供给基线语义（r316）——
    命中轮写供给不告警、断链轮归零告警（比率观测 <10%），键死静默
    回归 tx→td 事故有观测兜底。"""
    from types import SimpleNamespace as _NS
    import main as _m
    monkeypatch.setattr(_m, "_SENT_PATH", str(tmp_path / "sent.json"))
    monkeypatch.setattr(_m, "_ROW_HIST", {})
    _m._SENT_LAST.clear()
    _m._SENT_CNT.clear()
    _m._SENT_SUPPLIED.clear()
    seen = []

    class _L:
        def warning(self, *a, **k):
            seen.append(a)

        def info(self, *a, **k):
            pass

    alive = [{"price": 1000, "cabin": "经济舱", "plane": "波音737(中)"}
             for _ in range(30)]
    _m._field_sentinel([_NS(platform="qunar", extra=json.dumps(alive))], _L())
    assert not any("plane" in str(a) for a in seen), seen   # 供给轮健康
    seen.clear()
    dead = [{"price": 1000, "cabin": "经济舱"} for _ in range(30)]
    _m._field_sentinel([_NS(platform="qunar", extra=json.dumps(dead))], _L())
    assert any("qunar" in str(a) and "plane" in str(a) for a in seen), seen


def test_sentinel_tongcheng_tterm_whitelisted(monkeypatch, tmp_path):
    """tongcheng|tterm 入白名单恒 0 观测：供给基线语义（r316）——
    带值轮写供给不告警、断链轮（中转行 ≥20 且换乘楼全灭）告警
    （中转行 <20 门槛不报——供给侧稀疏非键死）。"""
    from types import SimpleNamespace as _NS
    import main as _m
    monkeypatch.setattr(_m, "_SENT_PATH", str(tmp_path / "sent.json"))
    monkeypatch.setattr(_m, "_ROW_HIST", {})
    _m._SENT_LAST.clear()
    _m._SENT_CNT.clear()
    _m._SENT_SUPPLIED.clear()
    seen = []

    class _L:
        def warning(self, *a, **k):
            seen.append(a)

        def info(self, *a, **k):
            pass

    alive = [{"price": 1000, "transCity": "西安", "transTerminal": "T2"}
             for _ in range(20)]
    alive += [{"price": 1000} for _ in range(10)]
    _m._field_sentinel([_NS(platform="tongcheng", extra=json.dumps(alive))],
                       _L())
    assert not any("tterm" in str(a) or "transTerminal" in str(a)
                   for a in seen), seen
    seen.clear()
    dead = [{"price": 1000, "transCity": "西安"}
            for _ in range(20)]
    dead += [{"price": 1000} for _ in range(10)]
    _m._field_sentinel([_NS(platform="tongcheng", extra=json.dumps(dead))],
                       _L())
    assert any("tterm" in str(a) or "transTerminal" in str(a)
               for a in seen), seen


# ---- 修复回归 ----

def test_fliggy_double_transfer_block_dropped():
    """三段两转异形块宁缺勿错整行弃（实跑复现：二次定证曾
    覆写 transCity/中转机场错占 arr 位/pend 顶成二段，产出多字段错值
    行看似正常入库）。"""
    txt = "\n".join([
        "春秋9C7006", "中型机 320",
        "春秋9C7310", "中型机 320",
        "春秋9C8801", "中型机 320",
        "10月05日 15:15", "10月05日 19:05",
        "10月06日 06:05", "10月06日 09:05",
        "10月06日 12:05", "10月06日 14:05",
        "乌鲁木齐天山国际机场", "石家庄中转", "正定国际机场",
        "郑州中转", "虹桥国际机场T1",
        "¥2060 5.0折", "订票",
    ])
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-05")
    assert rows == [], rows


def test_fliggy_transfer_truth_survives_phantom_guard():
    """低价中转真值豁免 0.5x 中位幻影锚（¥900 中转 vs 直飞
    群 2020 曾被误杀弃行——layoverSrc=transInfo 是渠道结构化真值非页面
    猜测，守卫只服务猜测值）。"""
    direct = ("东航MU836%d\n中型机 737\n1%d:1%d\n1%d:2%d\n"
              "乌鲁木齐天山国际机场\n虹桥国际机场T2\n¥1980 5.0折")
    blocks = [direct % (i, 6 + i, i, 7 + i, i) for i in range(4)]
    trans = "\n".join([
        "春秋9C7006", "中型机 320",
        "春秋9C7310", "中型机 320",
        "10月05日 15:15", "10月05日 19:05",
        "10月06日 06:05", "10月06日 07:55",
        "乌鲁木齐天山国际机场", "石家庄中转", "虹桥国际机场T1",
        "¥900 5.0折", "¥240机建燃油", "订票",
    ])
    txt = "\n".join(blocks + [trans])
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-05")
    codes = [r["code"] for r in rows]
    assert "9C7006/9C7310" in codes, codes
    tr = next(r for r in rows if r["code"] == "9C7006/9C7310")
    assert tr["price"] == 900 and tr["transferTax"] == 240
