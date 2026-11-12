# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r236_fields.py
- tests/test_r243_fields.py
- tests/test_r244_fields.py
- tests/test_r245_fields.py
- tests/test_r255_fields.py
- tests/test_r265_fields.py
- tests/test_r285_fields.py
- tests/test_r286_fields.py
- tests/test_r309_fields.py
- tests/test_r310_fields.py
- tests/test_r318_fields.py
- tests/test_r322_fields.py
- tests/test_r331_fields.py
- tests/test_v15110_fields.py
- tests/test_v15126_fields.py
- tests/test_v1563_fields.py
- tests/test_v162_fields.py
- tests/test_v178_fields.py
- tests/test_v181_fields.py
- tests/test_v191_fields.py
- tests/test_v199_fields.py
- tests/test_v200_fields.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import copy
import json
import logging
import os
import pytest
import sys

from core import flightnorm
from core.flightnorm import cross_days as _xd
from crawlers.ctrip import CtripCrawler
from crawlers.fliggy import FliggyCrawler
from crawlers.qunar import QunarCrawler, _meal_from_addons
from crawlers.tongcheng import TongchengCrawler
from crawlers.tuniu import TuniuCrawler


# ---- merged from tests/test_r236_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("r236")
_CT = CtripCrawler({}, _LOG)


def _ctrip_item(segs, policies, aset=None):
    it = {"mutilstn": segs, "policyinfo": policies}
    if aset is not None:
        it["aset"] = aset
    return it


def _ctrip_seg(dd, ad, flgno="CZ5640"):
    return {"dateinfo": {"ddate": dd, "adate": ad},
            "basinfo": {"flgno": flgno},
            "dportinfo": {"bsname": "", "aport": "URC"},
            "aportinfo": {"bsname": "T3", "aport": "SHA"}}


def _ci_plain(letter="Y"):
    return {"cgrd": 0,
            "classNoteList": [{"notetype": 2, "notecnt": letter}]}


def _ctrip_policy_cis(price, cis, qty=5):
    return {"tprice": price, "quantity": qty, "drate": 5.2,
            "classinfor": cis}


def _one(item):
    rows = _CT._extract_ctrip_flights(json.dumps([item]))
    assert rows
    return rows[0]


_D = ("2026-10-06 08:30:00", "2026-10-06 13:50:00")


def test_aset_meal_lounge_label():
    """aset「赠餐食、休息厅」（tcode=G_ALLDRZZZFWB）→ labels：中转
    服务承诺词随白名单收编（tagcnt 精确等值匹配，勿按 tcode 匹配
    以免疫换代——「老客专享」先例同律）。"""
    aset = [{"tagarea": [{"tcode": "G_ALLDRZZZFWB",
                          "tagcnt": "赠餐食、休息厅"}]}]
    r = _one(_ctrip_item([_ctrip_seg(*_D)],
                         [_ctrip_policy_cis(1200, [_ci_plain()])],
                         aset=aset))
    assert "赠餐食、休息厅" in r["labels"]


def test_aset_meal_lounge_with_existing_words_no_dup():
    """新词与既有白名单词同行并存：各自一次、零重复拼接（aset 同词
    去重纪律的并存回归钉）。"""
    aset = [{"tagarea": [
        {"tcode": "G_ALLDRZZZFWB", "tagcnt": "赠餐食、休息厅"},
        {"tcode": "G_KMZZAJ", "tagcnt": "赠快速安检"}]}]
    r = _one(_ctrip_item([_ctrip_seg(*_D)],
                         [_ctrip_policy_cis(1200, [_ci_plain()])],
                         aset=aset))
    ls = r["labels"].split("·")
    assert ls.count("赠餐食、休息厅") == 1
    assert ls.count("赠快速安检") == 1


# ---- merged from tests/test_r243_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _qn_trans_f(code="3U1599/MU2161", b1=None, b2=None, **top):
    """W-1 标本形态：中转行 code 含 /、info=binfo1、binfo2 带二段到达。"""
    f = {
        "minPrice": 1200, "code": code,
        "binfo1": dict({"depTime": "08:00", "arrTime": "11:30",
                        "depDate": "2026-10-05", "arrDate": "2026-10-05",
                        "codeShare": 1,
                        "mainCarrierSimpleNameAndNo": ""}, **(b1 or {})),
        "binfo2": dict({"arrTime": "18:20", "arrDate": "2026-10-05"},
                       **(b2 or {})),
        "extparams": "{}",
    }
    f.update(top)
    return f


def _qn_one(f):
    rows = QunarCrawler._extract_flights_obj([f])
    assert rows, "样本应产出至少一行"
    return rows[0]


def test_qunar_trans_share_selfref_blocked():
    """末行兜底自引用门：末行号 ∈ 段号集（首段共享+二段常规）→ 不落。

    W-1 标本：mainCarrier 缺席、mixCodeShare=1、末行「东航MU2161」
    恰是本行第二段号——自引用词面宁缺勿落（DB 12/799 误导实证）。"""
    r = _qn_one(_qn_trans_f(
        mixCodeShare=1, mixFlightName="三亚→乌市中转\n东航MU2161"))
    assert "shareCarrier" not in r, r.get("shareCarrier")


def test_qunar_trans_share_maincarrier_truth_wins():
    """真值源：binfo1.mainCarrier='CZ6305'（≠段号集）在主源空时落
    真值——首段实际承运恢复（同班 PC 行先例形态）。"""
    r = _qn_one(_qn_trans_f(
        b1={"mainCarrier": "CZ6305"},
        mixCodeShare=1, mixFlightName="三亚→乌市中转\n东航MU2161"))
    assert r["shareCarrier"] == "CZ6305", r.get("shareCarrier")


def test_qunar_trans_share_maincarrier_own_seg_guarded():
    """真值源自飞防呆：mainCarrier=本行段号（挂自身 id）→ 不落，
    且不回落自引用末行（双门齐拦，对齐 PC 直飞 m4 家族律）。"""
    r = _qn_one(_qn_trans_f(
        b1={"mainCarrier": "3U1599"},
        mixCodeShare=1, mixFlightName="三亚→乌市中转\n东航MU2161"))
    assert "shareCarrier" not in r, r.get("shareCarrier")


def test_qunar_trans_share_second_leg_truth_still_landed():
    """真二段承运保留：末行号 ∉ 段号集（NS8266/MU8801 行末行
    「东航MU2533」）→ 照落（v1590 立案的合法形态，自引用门勿误杀）。"""
    r = _qn_one(_qn_trans_f(
        code="NS8266/MU8801",
        mixCodeShare=1, mixFlightName="河北航NS8266\n\n东航MU2533"))
    assert r["shareCarrier"] == "东航MU2533", r.get("shareCarrier")


def test_qunar_trans_share_named_source_priority_unchanged():
    """主源优先不变：mainCarrierSimpleNameAndNo 有值时压过真值源与
    末行兜底（v1590 既有语义，三档档序锚）。"""
    r = _qn_one(_qn_trans_f(
        b1={"mainCarrierSimpleNameAndNo": "重庆航OQ2311",
            "mainCarrier": "OQ2311"},
        mixCodeShare=1, mixFlightName="三亚→乌市中转\n东航MU2161"))
    assert r["shareCarrier"] == "重庆航OQ2311", r.get("shareCarrier")


def test_qunar_trans_share_non_mixcode_untouched():
    """非 mixCodeShare 行为不变：codeShare 无任何可落源时宁缺
    （v1590「不凭空造源」语义跨档序保留）。"""
    assert "shareCarrier" not in _qn_one(_qn_trans_f())


def test_qunar_trans_share_last_line_no_fno_blocked():
    """兜底门防御档：末行提取不到任何航班号（纯中文词面）同样不落
    ——无法排除自引用，宁缺（旧行为无条件落，防御收紧须有钉）。"""
    r = _qn_one(_qn_trans_f(
        mixCodeShare=1, mixFlightName="三亚→乌市中转\n华夏航空直飞"))
    assert "shareCarrier" not in r, r.get("shareCarrier")


def test_qunar_direct_share_maincarrier_truth_lands():
    """真值档对直飞行同样生效（三档链直飞/中转共路）：code 单段、
    binfo.mainCarrier='FM9224' ≠ code → 落真值（PC 直飞 m4 家族
    同向，回归钉防后续收窄）。"""
    f = {"minPrice": 1200, "code": "MU2771",
         "binfo": {"depTime": "08:00", "arrTime": "11:30",
                   "depDate": "2026-10-05", "arrDate": "2026-10-05",
                   "codeShare": 1, "mainCarrierSimpleNameAndNo": "",
                   "mainCarrier": "FM9224"},
         "extparams": "{}"}
    assert _qn_one(f)["shareCarrier"] == "FM9224"


def test_qunar_direct_share_maincarrier_own_code_guarded():
    """直飞真值档自飞防呆：mainCarrier=本班 code（挂自身 id）→
    不落（对齐 PC 直飞 m4 门「mainCarrier≠airCode」）。"""
    f = {"minPrice": 1200, "code": "MU2771",
         "binfo": {"depTime": "08:00", "arrTime": "11:30",
                   "depDate": "2026-10-05", "arrDate": "2026-10-05",
                   "codeShare": 1, "mainCarrierSimpleNameAndNo": "",
                   "mainCarrier": "MU2771"},
         "extparams": "{}"}
    assert "shareCarrier" not in _qn_one(f)


# ---- merged from tests/test_r244_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _h5_trans(**top):
    """H5 中转行最小形态：info=binfo1、顶层 transTime 英文词面（缺陷态）。"""
    f = {
        "minPrice": 1200, "code": "3U1599/MU2161",
        "transTime": "25h40m",
        "binfo1": {"depTime": "08:00", "arrTime": "11:30",
                   "depDate": "2026-10-05", "arrDate": "2026-10-05"},
        "binfo2": {"arrTime": "18:20", "arrDate": "2026-10-05"},
        "extparams": "{}",
    }
    f.update(top)
    return f


def _h5_one(f):
    rows = QunarCrawler._extract_flights_obj([f])
    assert rows, "样本应产出至少一行"
    return rows[0]


# ---- H5 出口：词面归一 ----

def test_qunar_h5_td_en_word_normalized():
    """中转行顶层 transTime='25h40m'（本代 416/416 缺陷态）→ 归一
    '25时40分'（与 binfo1.transTime 中文真值逐行值等形异）。"""
    assert _h5_one(_h5_trans())["totalDuration"] == "25时40分"


def test_qunar_h5_td_whole_hour_normalized():
    """整小时形 '5h'（观测窗 27 条）→ '5时00分'（fmt_dur 统一形态）。"""
    assert _h5_one(_h5_trans(transTime="5h"))["totalDuration"] == "5时00分"


def test_qunar_h5_td_unparseable_preserved():
    """unparseable 词面原样保留（归一只换形不造值：'1天2时' 渠道口径
    _dur_min 不认 → 透传，宁存原词勿丢值）。"""
    assert _h5_one(_h5_trans(transTime="1天2时"))["totalDuration"] == "1天2时"


def test_qunar_h5_td_absent_not_landed():
    """无值不落语义跨归一保留：transTime 与 info.totalDuration 双缺
    → 键不落（r241 空串收口钉回归）。"""
    f = _h5_trans()
    f.pop("transTime")
    assert "totalDuration" not in _h5_one(f)


def test_qunar_h5_td_chinese_unpadded_padded():
    """中文非填充形 '3时5分' → 统一 '3时05分'（直飞行已是中文词面，
    归一对齐 PC 重建/DOM 兜底路径的 fmt_dur 形态）。"""
    assert _h5_one(_h5_trans(transTime="3时5分"))["totalDuration"] == "3时05分"


# ---- PC 出口：直飞/经停分支整小时词面 ----

def _pc_direct(flight_time):
    return __import__("json").dumps({
        "ret": True, "data": {"flights": [
            {"code": "FM9223", "minPrice": "2472", "transCity": "",
             "transTime": "",
             "binfo": {"airCode": "FM9223", "shortName": "上航",
                       "name": "上海航空", "depTime": "19:55",
                       "arrTime": "01:25", "date": "2026-10-05",
                       "arrDate": "2026-10-06",
                       "flightTime": flight_time}},
        ]}}, ensure_ascii=False)


def test_qunar_pc_direct_whole_hour_normalized():
    """PC 直飞行 flightTime='5h'（窗内 340 item 缺陷态）→ '5时00分'
    （旧 re.sub 不命中原样透传英文词面）。"""
    out = QunarCrawler._parse_pc_flights(_pc_direct("5h"), "2026-10-05")
    assert out and out[0]["totalDuration"] == "5时00分", out


def test_qunar_pc_direct_standard_unchanged():
    """标准形 '5h30m' 行为不变（旧 re.sub 已归一的形态，回归钉）。"""
    out = QunarCrawler._parse_pc_flights(_pc_direct("5h30m"), "2026-10-05")
    assert out and out[0]["totalDuration"] == "5时30分"


def test_qunar_pc_direct_garbage_flighttime_dropped():
    """flightTime 不可解析词面 → 不落键（旧 re.sub 透传垃圾词面落库；
    归一后 _fd(_dm(garbage))='' 走无值不落，宁缺勿错）。"""
    out = QunarCrawler._parse_pc_flights(_pc_direct("N/A"), "2026-10-05")
    assert out and "totalDuration" not in out[0]


# ---- merged from tests/test_r245_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t245")

_TRANSFER_TXT = "\n".join([
    "奥凯BK2776", "中型机 738",          # 首段（pend）
    "上航FM9402", "中型机 738",          # 二段（cur）
    "10月05日 15:15", "10月05日 19:05",
    "10月06日 06:05", "10月06日 07:55",
    "乌鲁木齐天山国际机场", "长沙中转", "黄花国际机场T1",
    "¥2060 5.0折", "订票",
])


def test_fliggy_trans_dep_terminal_pairing():
    """跨航站楼中转：transfer_map 双 p1 → transDepTerminal 落键
    （剥「起飞」尾与「国际机场/机场」后缀，对齐 qunar「正定T5」
    同形值域）；transTerminal 现行语义零变化。"""
    rows = FliggyCrawler._parse_pc_text(
        _TRANSFER_TXT, "2026-10-05",
        transfer_map={"BK2776": ("黄花机场T1", "黄花机场T2 起飞")})
    assert rows[0]["transTerminal"] == "黄花T1"
    assert rows[0]["transDepTerminal"] == "黄花T2"


def test_fliggy_trans_dep_terminal_absent_on_single():
    """单楼中转（无第二 p1）：只落 transTerminal，transDepTerminal
    无值不落键（宁缺勿错族律，对齐 r230 四写点纪律）。"""
    rows = FliggyCrawler._parse_pc_text(
        _TRANSFER_TXT, "2026-10-05",
        transfer_map={"BK2776": ("黄花机场T1", "")})
    assert rows[0]["transTerminal"] == "黄花T1"
    assert "transDepTerminal" not in rows[0]


def test_fliggy_transfer_map_legacy_str_form():
    """协议守卫（Soldier P2-1）：transfer_map 旧单值 str 形态按
    「单到达楼」语义容错收编为 (str, '')——不许被当序列下标产出
    脏值（str 形态 _tt[0]='黄'、_tt[1]='花' 的静默脏字面）。"""
    rows = FliggyCrawler._parse_pc_text(
        _TRANSFER_TXT, "2026-10-05",
        transfer_map={"BK2776": "黄花国际机场T1"})
    assert rows[0]["transTerminal"] == "黄花T1"
    assert "transDepTerminal" not in rows[0]


def test_fliggy_transfer_js_collects_dual_p1():
    """_TRANSFER_JS 采集面：matchAll 全量取 transfer-p1（match 单发
    是跨楼事实丢失的根因）+ 三元组返回（[号, 到达楼, 二段起飞楼]）。
    源码钉锁采集面。"""
    src = open("crawlers/fliggy.py", encoding="utf-8").read()
    assert "matchAll(/transfer-p1" in src
    assert "ms[0]" in src and "ms[1]" in src


# ---- merged from tests/test_r255_fields.py ----

def _tc_direct(**kw):
    fl = {"fn": "9C6117", "asn": "春秋航空",
          "dt": "2026-10-15 19:00", "at": "2026-10-15 23:40",
          "td": "4h40m", "afn": "空客A320(中)",
          "lps": [{"atp": 670, "brs": [{"al": 3}],
                   "pts": [{"tt": 2, "td": "超惠飞"}],
                   "fs": [{"ft": 7, "fcs": ["3", "6", "7"]}]}]}
    fl.update(kw)
    return json.dumps({"data": {"fl": [fl]}}, ensure_ascii=False)


def test_tongcheng_chaohuifei_label_direct():
    """直飞 9C 班 pts[].td="超惠飞" → labels 含「超惠飞」（生产
    dump 实证形态：独占 tt=2 元素，舱位/折扣正则均不命中的旁路
    词面）；产品形态词排 clct 舒适词之前（行李语义优先呈现）。"""
    text = _tc_direct(
        lps=[{"atp": 670, "brs": [{"al": 3}],
              "pts": [{"tt": 2, "td": "超惠飞"}],
              "fs": [{"ft": 7, "fcs": ["3", "6", "7"]}],
              "clct": [{"tt": 1, "td": "大机型"}]}])
    out = TongchengCrawler._extract_flights(text)
    assert len(out) == 1
    f = out[0]
    assert f["price"] == 670, f
    assert "超惠飞" in f.get("labels", ""), f
    assert f["labels"].index("超惠飞") < f["labels"].index("大机型"), f


def test_tongcheng_chaohuifei_absent_on_normal_policy():
    """对照班（舱位词面政策）labels 不含「超惠飞」——白名单精确
    匹配，非超惠飞词面零污染。"""
    text = _tc_direct(
        lps=[{"atp": 1500, "brs": [{"al": 3}],
              "pts": [{"tt": 2, "td": "6.8折经济舱"}]}])
    out = TongchengCrawler._extract_flights(text)
    f = out[0]
    assert f["cabin"] == "经济舱", f
    assert "超惠飞" not in f.get("labels", ""), f


def test_tongcheng_chaohuifei_label_transfer():
    """中转路径同槽同轮：lps[].pts[].td="超惠飞" → labels 含
    （同白名单词，中转 9C 段在场即捕获；无值不落键律随 labels
    既有出口）。"""
    fp = {"dt": "2026-10-15 13:20", "at": "2026-10-15 21:30",
          "td": "8h10m", "sc": "兰州",
          "ss": [{"fn": "9C6117", "dt": "2026-10-15 13:20",
                  "at": "2026-10-15 16:05"},
                 {"fn": "MU5700", "dt": "2026-10-15 18:20",
                  "at": "2026-10-15 21:30"}],
          "lps": [{"atp": 820, "brs": [{"al": 3}],
                   "pts": [{"tt": 2, "td": "超惠飞"}]}]}
    rows = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp]}}, ensure_ascii=False), "")
    assert rows, "中转样本应产出至少一行"
    assert "超惠飞" in rows[0].get("labels", ""), rows[0]


def test_tongcheng_chaohuifei_transfer_absent_keeps_service_labels():
    """中转无超惠飞时 labels 维持服务承诺原形——白名单并链不得
    挤掉既有 fw_txt 档（第二段服务承诺）。"""
    fp = {"dt": "2026-10-15 13:20", "at": "2026-10-15 21:30",
          "td": "8h10m", "sc": "兰州",
          "ss": [{"fn": "CZ6981", "dt": "2026-10-15 13:20",
                  "at": "2026-10-15 16:05"},
                 {"fn": "MU5700", "dt": "2026-10-15 18:20",
                  "at": "2026-10-15 21:30"}],
          "lps": [{"atp": 1500, "brs": [{"al": 5}],
                   "pts": [{"td": "6.8折经济舱"}]}]}
    rows = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp]}}, ensure_ascii=False), "")
    assert rows
    assert "超惠飞" not in rows[0].get("labels", ""), rows[0]


# ---- Soldier P1-1/P1-2：随最低价政策复位（脏携带复现钉） ----

def test_tongcheng_chaohuifei_no_carryover_direct():
    """Soldier P1-1：直飞多政策 [超惠飞@670, 普通经济舱@500]——
    500 行成为最低价时 chaofei 必须随政策复位，「超惠飞」不得
    脏携带到普通舱行 labels（ Soldiery 探针场景）。"""
    text = _tc_direct(
        lps=[{"atp": 670, "brs": [{"al": 3}],
              "pts": [{"tt": 2, "td": "超惠飞"}]},
             {"atp": 500, "brs": [{"al": 3}],
              "pts": [{"tt": 2, "td": "5.4折经济舱"}]}])
    out = TongchengCrawler._extract_flights(text)
    assert len(out) == 1
    f = out[0]
    assert f["price"] == 500, f
    assert "超惠飞" not in f.get("labels", ""), f


def test_tongcheng_chaohuifei_no_carryover_transfer():
    """Soldier P1-2：中转多政策 [超惠飞@820(带WiFi), 普通@600(无fwbqs)]
    ——600 行成为最低价时超惠飞与服务承诺双双复位，陈旧 fw_txt
    通道不得把上一政策的词面残留到新最低价行。"""
    fp = {"dt": "2026-10-15 13:20", "at": "2026-10-15 21:30",
          "td": "8h10m", "sc": "兰州",
          "ss": [{"fn": "9C6117", "dt": "2026-10-15 13:20",
                  "at": "2026-10-15 16:05"},
                 {"fn": "MU5700", "dt": "2026-10-15 18:20",
                  "at": "2026-10-15 21:30"}],
          "lps": [{"atp": 820, "brs": [{"al": 3}],
                   "pts": [{"tt": 2, "td": "超惠飞"}],
                   "fwbqs": [{"td": "第2程：免费上网"}]},
                  {"atp": 600, "brs": [{"al": 3}],
                   "pts": [{"tt": 2, "td": "6.8折经济舱"}]}]}
    rows = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp]}}, ensure_ascii=False), "")
    assert rows
    f = rows[0]
    assert f.get("price") == 600, f
    assert "超惠飞" not in f.get("labels", ""), f
    assert "免费上网" not in f.get("labels", ""), f


def test_tongcheng_chaohuifei_exact_match_only():
    """Soldier Minor-2：白名单精确匹配的值域免疫——近形词面
    （「超惠飞X」子串变异）不得命中。"""
    text = _tc_direct(
        lps=[{"atp": 670, "brs": [{"al": 3}],
              "pts": [{"tt": 2, "td": "超惠飞X"}]}])
    out = TongchengCrawler._extract_flights(text)
    f = out[0]
    assert "超惠飞" not in f.get("labels", ""), f


# ---- merged from tests/test_r265_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t265")

# 双中转块：块 1 定证行带「换航站楼」后缀（渠道 change-terminal label
# 与城市 label 同 div 兄弟，10-15 dump 行文本实证为「西安中转 换航站楼」
# ——两 label 间空白节点渲染成单空格）；块 2 正常行——修复前块 1 整行
# 丢失、其孤儿首段污染块 2 的合并配对（生产 13 轮嵌合实录）。
_CHANGE_TERMINAL_TXT = "\n".join([
    # 块 1：BK2776 + FM9402，长沙中转（跨楼行）
    "奥凯BK2776", "中型机 738",
    "上航FM9402", "中型机 738",
    "10月15日 15:15", "10月15日 19:05",
    "10月16日 06:05", "10月16日 07:55",
    "乌鲁木齐天山国际机场", "长沙中转 换航站楼", "黄花国际机场T1",
    "¥2060 5.0折", "订票",
    # 块 2：HU7149 + MF8215，兰州中转（正常形态）
    "海航HU7149", "中型机 738",
    "春运MF8215", "中型机 738",
    "10月15日 20:15", "10月15日 22:45",
    "10月16日 09:05", "10月16日 11:05",
    "黄花国际机场T2", "兰州中转", "中川国际机场",
    "¥1870 4.2折", "订票",
])


def _codes(rows):
    return [r.get("code") for r in rows]


def test_fliggy_change_terminal_block_recovered():
    """带「换航站楼」后缀的中转定证行照常定证入库：块 1 行找回
    （code=A/B 合串、transCity=长沙），块 2 不受污染，无第三行。"""
    rows = FliggyCrawler._parse_pc_text(_CHANGE_TERMINAL_TXT, "2026-10-15")
    assert _codes(rows) == ["BK2776/FM9402", "HU7149/MF8215"], _codes(rows)
    assert rows[0]["transCity"] == "长沙"
    assert rows[1]["transCity"] == "兰州"


def test_fliggy_change_terminal_cross_terminal_landed():
    """跨楼真值找回：transfer_map 双 p1 配对照常落 transTerminal/
    transDepTerminal（该 label 是 transDepTerminal 唯一载体）。"""
    rows = FliggyCrawler._parse_pc_text(
        _CHANGE_TERMINAL_TXT, "2026-10-15",
        transfer_map={"BK2776": ("黄花机场T1", "黄花机场T2 起飞")})
    assert rows[0]["transTerminal"] == "黄花T1"
    assert rows[0]["transDepTerminal"] == "黄花T2"


def test_fliggy_change_terminal_suffix_not_landed():
    """「换航站楼」词面零增量不落键：跨楼事实由 transTerminal≠
    transDepTerminal 派生（既有出口承载），不新增词面键。
    （配套性质声明：本钉为卫生钉非回归检测钉——回退修复时该行
    整行丢弃、词面同样不入行，本钉不红；行找回的回归检测由
    test_fliggy_change_terminal_block_recovered 承载。）"""
    rows = FliggyCrawler._parse_pc_text(
        _CHANGE_TERMINAL_TXT, "2026-10-15",
        transfer_map={"BK2776": ("黄花机场T1", "黄花机场T2 起飞")})
    assert "换航站楼" not in str(rows[0])


def test_fliggy_change_terminal_glued_variant():
    """无空格拼行变体（两 label 间无空白节点的渲染形态）同样定证：
    后缀容忍空白可有可无，两种词形都不得断锚。"""
    txt = _CHANGE_TERMINAL_TXT.replace("长沙中转 换航站楼",
                                       "长沙中转换航站楼")
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-15")
    assert _codes(rows) == ["BK2776/FM9402", "HU7149/MF8215"], _codes(rows)
    assert rows[0]["transCity"] == "长沙"


# R1 第二断锚（dump origin-no=36 行级实证）：中转二段行头带「经停」
# 后缀（「吉祥HO1068 经停」）——_RE_FNO 行尾 $ 前不容后缀 → 二段行头
# 不识别 → cur 停留首段 → 「兰州中转」定证合并 pend(孤儿)/cur(首段)
# 产嵌合（修复前与断锚一复合成生产 13 轮脏行），无孤儿时产首段单段
# 半截行（DB 存量 158 元素慢性族根因，fliggy 特有、tongcheng 同形为 0）。
_STOPOVER_LEG_TXT = "\n".join([
    "春秋9C7372", "中型机 320 无餐食",
    "吉祥HO1068 经停", "中型机 320 有餐食",
    "10月15日 15:00", "10月15日 18:00",
    "10月15日 19:45", "10月16日 00:30",
    "乌鲁木齐天山国际机场", "兰州中转", "浦东国际机场T2",
    "¥822 2.0折", "订票",
])


def test_fliggy_stopover_suffix_second_leg_pairing():
    """二段行头「经停」后缀照常识别行头：A/B 配对成中转行（code 合串/
    transCity/时刻链/餐食仲裁全链真值），stopover 落键与机型行经停
    同值域（True）。"""
    rows = FliggyCrawler._parse_pc_text(_STOPOVER_LEG_TXT, "2026-10-15")
    assert _codes(rows) == ["9C7372/HO1068"], _codes(rows)
    r = rows[0]
    assert r["transCity"] == "兰州"
    assert r["stopover"] is True
    assert r["depTime"] == "15:00" and r["arrTime"] == "00:30"
    assert r["lay2dep"] == "19:45"
    assert r["meal"] == "无餐食"   # 两段异值保守仲裁（L471-475 既有语义）


def test_fliggy_stopover_suffix_direct_leg():
    """直飞行头带「经停」后缀同样识别：stopover 落键，行不丢。"""
    txt = "\n".join([
        "川航3U8880 经停", "中型机 320 有餐食",
        "08:00", "12:30",
        "乌鲁木齐天山国际机场", "上海虹桥国际机场T2",
        "¥980 3.2折", "订票",
    ])
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-15")
    assert len(rows) == 1 and rows[0]["code"] == "3U8880"
    assert rows[0]["stopover"] is True


# ---- merged from tests/test_r285_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


# ---- merged from tests/test_r286_fields.py ----

def _h5_flight(add_names, code="HO1087"):
    """真实 dump 形态：HO 系小食班次 additionInfos 全集按 01-29 报文。"""
    return {
        "minPrice": 1760, "code": code,
        "flightAddInfoIntegration": {"flightAdditionInfos": [
            {"name": nm, "icon": "i"} for nm in add_names]},
        "binfo": {"depTime": "08:15", "arrTime": "11:05",
                  "depDate": "2027-01-29", "arrDate": "2027-01-29"},
    }


def test_meal_gate_recognizes_snack():
    """提取门认「小食」：现行门（餐/点心）不命中 → meal 缺席；
    补词后返回「小食」原文。"""
    integ = {"flightAdditionInfos": [
        {"name": "小食", "icon": "i"},
        {"name": "免费托运20KG", "icon": "j"}]}
    meal, baggage = _meal_from_addons(integ)
    assert meal == "小食", meal
    assert baggage == "免费托运20KG", baggage


def test_meal_gate_snack_not_shadowed_by_placeholder_words():
    """占位词不在场时不误抬：仅托运+监控占位词的行 meal 仍缺席。"""
    integ = {"flightAdditionInfos": [
        {"name": "免费托运20KG", "icon": "i"},
        {"name": "廊桥登机率--", "icon": "j"},
        {"name": "WiFi未知", "icon": "k"}]}
    meal, baggage = _meal_from_addons(integ)
    assert meal == "", meal
    assert baggage == "免费托运20KG", baggage


def test_h5_parse_meal_snack_lands():
    """全链路：解析出口 meal='小食' 落键（dump 实证形态 6/221 行）。"""
    text = json.dumps({"data": {"flights": [
        _h5_flight(["小食", "免费托运20KG", "廊桥登机率--",
                    "起飞准点率--", "平均延误--", "WiFi未知"]),
        # 对照行：真无餐食词的行键仍缺席（无值不落键收口不回退）
        _h5_flight(["免费托运20KG", "WiFi未知"], code="HO1273"),
    ]}})
    rows = QunarCrawler._parse_response_flights(text)
    assert rows[0]["meal"] == "小食", rows[0]
    assert "meal" not in rows[1], rows[1]


# ---- merged from tests/test_r309_fields.py ----

def _transfer_txt(seg1_plane: str, seg2_plane: str) -> str:
    """中转块文本（r265 _STOPOVER_LEG_TXT 同构在产形态）。"""
    lines = ["国航CA8347"]
    if seg1_plane:
        lines.append(seg1_plane)
    lines += ["深航ZH8993"]
    if seg2_plane:
        lines.append(seg2_plane)
    lines += [
        "10月15日 15:00", "10月15日 18:00",
        "10月15日 19:45", "10月16日 00:30",
        "乌鲁木齐天山国际机场", "兰州中转", "浦东国际机场T2",
        "¥822 2.0折", "订票",
    ]
    return "\n".join(lines)


def test_fliggy_seg_plane_label_when_legs_differ():
    """两段机型异值（dump 实证最高频对 321/320NEO）：labels 落
    「首段321」，主槽 plane 保持二段 320NEO 现状。"""
    rows = FliggyCrawler._parse_pc_text(
        _transfer_txt("中型机 321", "中型机 320NEO"), "2026-10-15")
    assert len(rows) == 1
    r = rows[0]
    assert r["code"] == "CA8347/ZH8993"
    assert r["plane"] == "320NEO"          # 主槽=二段（现状不动）
    assert r["labels"] == "首段321"


def test_fliggy_seg_plane_label_same_value_not_set():
    """两段机型同值：主槽已代表全程，labels 不落（无值不落键族律）。"""
    rows = FliggyCrawler._parse_pc_text(
        _transfer_txt("中型机 737", "中型机 737"), "2026-10-15")
    assert len(rows) == 1
    r = rows[0]
    assert r["plane"] == "737"
    assert "labels" not in r


def test_fliggy_seg_plane_label_when_second_leg_missing():
    """二段机型行缺席（折叠异形块 2/45）：首段机型顶主槽
    （setdefault 零冲突）且 labels 带段位词面消歧，信息不静默丢。"""
    rows = FliggyCrawler._parse_pc_text(
        _transfer_txt("中型机 737", None), "2026-10-15")
    assert len(rows) == 1
    r = rows[0]
    assert r["plane"] == "737"
    assert r["labels"] == "首段737"


def test_fliggy_seg_plane_label_when_first_leg_missing():
    """首段机型行缺席：无可落词面，行照常入库（现状行为不变）。"""
    rows = FliggyCrawler._parse_pc_text(
        _transfer_txt(None, "中型机 320NEO"), "2026-10-15")
    assert len(rows) == 1
    r = rows[0]
    assert r["plane"] == "320NEO"
    assert "labels" not in r


# ---- merged from tests/test_r310_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t_r310")
_CT = CtripCrawler({}, _LOG)


def _parse(extend):
    seg = {"basinfo": {"flgno": "MU5137"},
           "dateinfo": {"ddate": "2026-10-15 08:00:00",
                        "adate": "2026-10-15 11:30:00"},
           "aportinfo": {"city": "上海"}}
    ci = {"cgrd": 0, "prate": 96, "meal": "有餐食",
          "extendinfos": extend}
    obj = {"fltitem": [{"mutilstn": [seg],
                        "policyinfo": [{"tprice": 1200, "quantity": 1,
                                        "classinfor": [ci]}]}]}
    rows = _CT._extract_ctrip_flights(json.dumps(obj, ensure_ascii=False))
    assert rows
    return rows[0]


def test_avgdelay_no_content_no_key():
    """extendinfos 无「平均延误N分钟」content → avgDelay 键不落。"""
    r = _parse([{"content": "机龄8年"}])
    assert "avgDelay" not in r, r.get("avgDelay")


def test_avgdelay_int_and_zero_fall():
    """有 content 落 int；0 分钟是渠道显式真值照落（!= "" 门非 truthy）。"""
    r = _parse([{"content": "平均延误21分钟"}])
    assert r["avgDelay"] == 21
    r0 = _parse([{"content": "平均延误0分钟"}])
    assert r0["avgDelay"] == 0


def test_planeage_no_content_no_key():
    """extendinfos 无机龄 content → planeAge 键不落。"""
    r = _parse([{"content": "平均延误21分钟"}])
    assert "planeAge" not in r, r.get("planeAge")


def test_planeage_falls_and_zero_year_kept():
    """有 content 落词面；机龄 0 年照落（truthy 门会吞「0」）。"""
    r = _parse([{"content": "机龄8年5个月"}])
    assert r["planeAge"] == "8.4"
    r0 = _parse([{"content": "机龄0年"}])
    assert r0["planeAge"] == "0"


def test_both_absent_empty_extendinfos():
    """extendinfos=[] → 两键双双不落（空串占位平铺收口主形态）。"""
    r = _parse([])
    assert "avgDelay" not in r, r.get("avgDelay")
    assert "planeAge" not in r, r.get("planeAge")


def test_scheduler_misfire_grace_pinned():
    """接力调度器必须带 misfire 宽限窗：满载外邻作业窗口内 due 轮
    被 misfire 丢弃后，显式接力无人排定=调度链静默死亡（进程活、
    端口听、零扫描）。宽限窗让迟到轮照跑、接力链自愈。"""
    from core import scheduler as sch

    added = {}

    class FakeSched:
        def __init__(self, timezone=None):
            pass

        def add_job(self, fn, **kw):
            added.update(kw)
            added["fn"] = fn

        def modify_job(self, *a, **k):
            pass

        def get_job(self, _):
            return object()

        def start(self):
            pass

    orig = sch.BlockingScheduler
    sch.BlockingScheduler = FakeSched
    try:
        sch.run_scheduler(lambda: None,
                          {"interval_minutes": 5, "jitter_minutes": 0},
                          run_on_start=False)
    finally:
        sch.BlockingScheduler = orig
    assert added.get("misfire_grace_time", 0) >= 300, added
    assert added.get("coalesce") is True


# ---- merged from tests/test_r318_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t_r318")
_CT = CtripCrawler({}, _LOG)


def _parse(extend):
    seg = {"basinfo": {"flgno": "MU5137"},
           "dateinfo": {"ddate": "2026-10-15 08:00:00",
                        "adate": "2026-10-15 11:30:00"},
           "aportinfo": {"city": "上海"}}
    ci = {"cgrd": 0, "prate": 96, "meal": "有餐食",
          "extendinfos": extend}
    obj = {"fltitem": [{"mutilstn": [seg],
                        "policyinfo": [{"tprice": 1200, "quantity": 1,
                                        "classinfor": [ci]}]}]}
    rows = _CT._extract_ctrip_flights(json.dumps(obj, ensure_ascii=False))
    assert rows
    return rows[0]


def test_planeage_bare_five_quarantined():
    """机龄整 5 年（恒档下发形态）→ planeAge 键不落（读层置空）。"""
    r = _parse([{"content": "机龄5年"}])
    assert "planeAge" not in r, r.get("planeAge")


def test_planeage_five_with_months_still_lands():
    """「机龄5年11个月」→'5.9' 照落：月成分形态非恒档下发值。"""
    r = _parse([{"content": "机龄5年11个月"}])
    assert r["planeAge"] == "5.9", r.get("planeAge")


def test_planeage_other_years_still_land():
    """非 5 整年照落（守卫零外溢）：8 年→'8'、0 年→'0' 显式真值。"""
    r = _parse([{"content": "机龄8年"}])
    assert r["planeAge"] == "8", r.get("planeAge")
    r0 = _parse([{"content": "机龄0年"}])
    assert r0["planeAge"] == "0", r0.get("planeAge")


# ---- 解析哨兵×恒档守卫的口径适配（守卫置空非断链） ----

class _CapLog:
    def __init__(self):
        self.seen = []

    def info(self, *a, **k):
        pass

    def warning(self, msg, *a, **k):
        self.seen.append(msg % a if a else str(msg))


def _sent_reset(_m):
    _m._SENT_LAST.clear()
    _m._SENT_CNT.clear()
    _m._SENT_SUPPLIED.clear()


def test_field_sentinel_ctrip_page_exempt():
    """供给基线在场的归零轮：守卫在岗时 ctrip planeAge 置空不再误报
    「键名失效/渠道改版」——置空是 _PLANEAGE_COARSE 守卫的预期行为，
    断链监测责任移交守卫观察哨（撤守卫条件=逐日 '5' 占比回落），
    哨兵退出 (ctrip, page) 观测。"""
    import json as _json
    from types import SimpleNamespace as _NS
    import main as _m
    lg = _CapLog()
    _sent_reset(_m)
    supply = [{"price": 1000 + i, "plane": "空客321(中)",
               "planeSize": "中型机", "planeAge": "6.3"}
              for i in range(30)]
    _m._field_sentinel([_NS(platform="ctrip",
                            extra=_json.dumps(supply))], lg)
    assert lg.seen == [], lg.seen          # 供给轮零告警
    guarded = [{"price": 1000 + i, "plane": "空客321(中)",
                "planeSize": "中型机"} for i in range(30)]
    _m._field_sentinel([_NS(platform="ctrip",
                            extra=_json.dumps(guarded))], lg)
    assert not any("planeAge" in s for s in lg.seen), lg.seen


def test_field_sentinel_other_page_still_observed():
    """豁免只及 (ctrip, page)：源码钉锁「ctrip 退出、tongcheng/tuniu
    保留」——防豁免扩面弱化断链防线，也防 page 观测面被整表清空。"""
    import os as _os
    from pathlib import Path as _Path
    src = _Path(_os.path.join(_os.path.dirname(
        _os.path.dirname(_os.path.abspath(__file__)),
    ), "main.py")).read_text(encoding="utf-8")
    assert '("ctrip", "page"),' not in src, "ctrip page 豁免未落地"
    assert '("tongcheng", "page"),' in src and '("tuniu", "page")' in src


# ---- merged from tests/test_r322_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("r322")
_QC = QunarCrawler({}, _LOG)


def _h5_f(texts):
    """H5 行最小载体：listLabel.priceBottomLabels 词面列表。"""
    return {"listLabel": {"priceBottomLabels": [{"text": t} for t in texts]}}


def test_h5_reduce_label_collected():
    """「可再减¥146」透明标记采入 labels（案 GS6549/KN2918 实锤形态）。"""
    out = QunarCrawler._h5_labels_of(_h5_f(["可再减¥146"]))
    assert "可再减¥146" in out, out


def test_h5_reduce_label_variants_still_excluded():
    """正则臂精确形态：裸词/起字变体/非 ¥ 计价形态仍拒。"""
    out = QunarCrawler._h5_labels_of(
        _h5_f(["可再减", "可再减¥20起", "可再减20", "再减¥20"]))
    assert out == "", out


def test_h5_marketing_churn_family_still_excluded():
    """营销 churn 族不随本臂放宽：比直飞省/精选低价族维持排除。"""
    out = QunarCrawler._h5_labels_of(
        _h5_f(["比直飞省¥30", "精选低价", "当日达低价", "中转-耗时最短"]))
    assert out == "", out


def test_h5_reduce_label_with_service_words_order_kept():
    """与服务承诺词共存：渠道原序、3 槽上限内正常编排。"""
    out = QunarCrawler._h5_labels_of(
        _h5_f(["免费上网", "可再减¥146"]))
    assert out == "免费上网·可再减¥146", out


# ---- merged from tests/test_r331_fields.py ----

def _resp():
    b1 = {"depTime": "15:00", "arrTime": "00:25",
          "depDate": "2026-10-06", "arrDate": "2026-10-08",
          "totalDuration": "33h25m", "transCity": "兰州",
          "stopsCitys": ",陇南", "stop": True}
    f = {"code": "9C7372/HO1108", "transCity": "兰州", "minPrice": 2502,
         "binfo1": b1,
         "binfo2": dict(b1),
         "extparams": json.dumps({"stopFlight": True, "lowPrice": 2502})}
    return json.dumps({"data": {"flights": [f]}})


def test_qunar_transfer_row_stops_city_lands():
    rows = QunarCrawler._parse_response_flights(_resp())
    assert len(rows) == 1
    r = rows[0]
    assert r.get("stopCitys") == "陇南"
    assert r.get("stopFlight") is True


def test_qunar_transfer_row_stop_city_normalizes():
    from core.flightnorm import normalize
    rows = QunarCrawler._parse_response_flights(_resp())
    f = normalize(rows[0], "2026-10-06")
    assert f.get("stopCity") == "陇南"
    assert f.get("stopover") is True


# ---- merged from tests/test_v15110_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t15110")


# ---- T-N1 tongcheng：conn 中转免费托运（bag_fc 跨报文线程） ----

def _tc_bag_fp(policies=None):
    """最低价政策带 fs[ft=7].fcs=["11"] 的 conn 中转样本
    （fp 形态与 test_v15106 _tc_fp 同构，lps 换双政策）。"""
    ss = [{"fn": "CZ6981", "dt": "2026-10-05 13:20",
           "at": "2026-10-05 16:05"},
          {"fn": "MU5700", "dt": "2026-10-05 18:20",
           "at": "2026-10-05 21:30"}]
    if policies is None:
        policies = [{"atp": 1500, "brs": [{"al": 5}],
                     "pts": [{"td": "6.8折经济舱"}],
                     "fs": [{"ft": 7, "fcs": ["11"]}]}]
    return {"dt": "2026-10-05 13:20", "at": "2026-10-05 21:30",
            "sd": "2h45m", "td": "8h10m", "sc": "张掖", "ss": ss,
            "lps": policies}


def _tc_bag_rows(fp, bag_fc="11"):
    rows = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp]}}), bag_fc)
    assert rows
    return rows[0]


def test_tc_conn_baggage_with_mapping():
    """最低价政策 fs[ft=7].fcs 含码 11 + bag_fc="11"：
    baggage=「免费托运」——中转裸价的行李语义随最低价政策落键。"""
    r = _tc_bag_rows(_tc_bag_fp())
    assert r["baggage"] == "免费托运"


def test_tc_conn_baggage_no_mapping_no_key():
    """码表缺席（bag_fc=""，book1 不在场/无 cfs 键）：行级码命中也
    不落键——码义映射缺席不落键（宁缺勿错，防码漂移后把无行李
    政策误标有行李）。"""
    r = _tc_bag_rows(_tc_bag_fp(), bag_fc="")
    assert "baggage" not in r


def test_tc_conn_baggage_follows_lowest_policy():
    """行李随最低价有票政策配对：最低价政策无码、次低价政策有码
    → 不落（监控按最低价告警，推出的裸价不得虚标行李）。"""
    ps = [{"atp": 1500, "brs": [{"al": 5}], "pts": [{"td": "经济舱"}]},
          {"atp": 1600, "brs": [{"al": 3}], "pts": [{"td": "6.8折经济舱"}],
           "fs": [{"ft": 7, "fcs": ["11"]}]}]
    r = _tc_bag_rows(_tc_bag_fp(ps))
    assert "baggage" not in r


def test_tc_conn_baggage_fc_drift_silent():
    """fc 漂移（码表给 12 而政策挂 11）：静默不并——码义与行级码
    不一致说明渠道改了码表语义，硬对会误标。"""
    r = _tc_bag_rows(_tc_bag_fp(), bag_fc="12")
    assert "baggage" not in r


def test_tc_conn_baggage_not_transfer_direct():
    """baggage「免费托运」≠ 直挂：doc 双图例并存（direct_only=False）
    且无 stss 行级证据时 transferBaggage 不落键——免费托运不参与
    直挂三态推断（语义留给行级证据守卫；空串键已按无值不落键
    族律退役，消费端 ==direct 判定缺键等价）。"""
    r = _tc_bag_rows(_tc_bag_fp())
    assert "transferBaggage" not in r


def test_tc_bag_fc_helper_single_source():
    """book1 cfs 码表提取抽单源 helper：conn 跨报文线程与 book1
    内联解析共用同一取值函数（防两份同逻辑漂移）。"""
    data = {"cfs": [{"ft": 7,
                     "fis": [{"fd": "免费托运行李", "fc": " 11 "}]}]}
    assert TongchengCrawler._bag_fc(data) == "11"
    assert TongchengCrawler._bag_fc({}) == ""
    assert TongchengCrawler._bag_fc({"cfs": [{"ft": 8, "fis": [
        {"fd": "免费托运行李", "fc": "11"}]}]}) == ""
    assert TongchengCrawler._bag_fc({"cfs": [{"ft": 7, "fis": [
        {"fd": "免费退改", "fc": "11"}]}]}) == ""


def test_tc_bag_fc_from_captured():
    """fetch 跨报文线程的 captured 提取纯函数（可测面）：book1 在场
    取码 / 缺席空串 / 坏 JSON 空串——映射缺席 conn 行级码命中也不落。"""
    _bag = TongchengCrawler._bag_fc_from_captured
    ok = [{"url": "https://m.ly.com/flightbffv2/book1/flights",
           "text": json.dumps({"data": {"cfs": [{"ft": 7, "fis": [
               {"fd": "免费托运行李", "fc": "11"}]}]}})}]
    assert _bag(ok) == "11"
    assert _bag([{"url": "https://x/connection/flights",
                  "text": "{}"}]) == ""
    assert _bag([{"url": "https://m.ly.com/flightbffv2/book1/flights",
                  "text": "not-json"}]) == ""
    assert _bag([]) == ""


# ---- merged from tests/test_v15126_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t15126")
_CT = CtripCrawler({}, _LOG)


# ---- ctrip aset 地域中转权益词 ----

def _ct_item(aset_words):
    """最小 ctrip 行：单政策 + aset[].tagarea[].tagcnt 词组。"""
    return {"mutilstn": [{"basinfo": {"flgno": "MU1234"},
                          "dateinfo": {"ddate": "2026-10-05 08:30:00",
                                       "adate": "2026-10-05 11:20:00"},
                          "craftinfo": {"cdisname": "空客320(中)"}}],
            "policyinfo": [{"quantity": 1, "tprice": 1000.0,
                            "drate": 5.0}],
            "aset": [{"tagarea": [{"tcode": "G_X", "tagcnt": w}
                                   for w in aset_words]}]}


def _ct_run(item):
    resp = {"fltitem": [item]}
    rows = _CT._extract_ctrip_flights(
        json.dumps(resp, ensure_ascii=False))
    assert len(rows) == 1
    return rows[0]


def test_ctrip_aset_region_word_cgo():
    """郑州中转权益词「享“豫转豫好”免费服务」：纯词无价格不随价
    churn，白名单收编（0 并现实证不收则永久缺失）。"""
    row = _ct_run(_ct_item(['享“豫转豫好”免费服务']))
    assert '享“豫转豫好”免费服务' in row["labels"]


def test_ctrip_aset_region_word_kmg():
    """昆明长水中转住宿权益品牌词「晚安长水」同行仅既有「赠快速
    安检」出口，住宿权益词无承载。"""
    row = _ct_run(_ct_item(["晚安长水"]))
    assert "晚安长水" in row["labels"]


def test_ctrip_aset_region_word_lhw():
    """兰州「经兰飞如意行权益」稀疏 1 行（同结构槽同族推证链：
    纯词+0 并现+qunar 同族先例）。"""
    row = _ct_run(_ct_item(["经兰飞如意行权益"]))
    assert "经兰飞如意行权益" in row["labels"]


def test_ctrip_aset_churn_marketing_word_still_absent():
    """带价 churn 词不因白名单扩充而混入：「优质中转·耗时短」
    营销词维持不收。"""
    row = _ct_run(_ct_item(["优质中转·耗时短"]))
    assert "优质中转·耗时短" not in row.get("labels", "")


# ---- tuniu 舱位写入端清污 + 补全源过门 ----

def _tj_fare(policies):
    """fare 形态：policies=[(baseFare, cabinTypeName)]。"""
    fpl = []
    for base, cab in policies:
        pr = {"fareBreakdownList": [{"baseFare": base,
                                     "psgType": "ADT"}]}
        if cab:
            pr["priceJourneyCabinList"] = [
                {"priceFlightCabinList": [{"cabinTypeName": cab}]}]
        fpl.append(pr)
    return {"flightOptions": [{"flightNos": "3U1953"}],
            "flightPriceList": fpl}


def test_tuniu_cabin_write_side_clean():
    """渠道在 detail 层下发高档舱名（与低价政策错配——DB 近 7 天
    BAD 行形态同构：cabin=公务舱、price<bizPrice、cabinCode 在场，
    3U1953 price=3570 biz=8340）：写入端 offer.cabin 过 cabin_clean
    同判据清污（price<bizPrice 高档词置空），DB 不再落脏值（消费端
    渲染门已挡，此门管落库面）。"""
    fare = {"flightOptions": [{"flightNos": "3U1953"}],
            "flightPriceList": [
                {"fareBreakdownList": [{"baseFare": 3570,
                                        "psgType": "ADT"}]},
                {"fareBreakdownList": [{"baseFare": 8340,
                                        "psgType": "ADT"}],
                 "priceJourneyCabinList": [
                     {"priceFlightCabinList": [
                         {"cabinTypeName": "公务舱",
                          "cabinCode": "J"}]}]}]}
    raw = {"data": {"fareList": [fare],
                    "flightList": {"3U1953#2026-10-06#URC#SHA": {
                        "airlineCompany": "川航",
                        "departureTime": "10:10",
                        "arrivalTime": "15:00",
                        "departureDate": "2026-10-06",
                        "arrivalDate": "2026-10-06",
                        "flightTime": "290",
                        # 渠道 detail 层下发高档舱名（与选中低价政策
                        # 错配的串舱源）
                        "cabinTypeName": "公务舱"}}}}
    offers = TuniuCrawler._parse_offers(raw)
    assert len(offers) == 1
    assert offers[0]["cabin"] == ""
    assert offers[0]["bizPrice"] == 8340   # 高档舱参考价记账不受影响


def test_tuniu_cabin_genuine_business_kept():
    """真高档选中行（price==bizPrice）：cabin 原值保留——清污门
    只杀价位矛盾形态，不误杀真公务舱。"""
    fare = _tj_fare([(8340, "公务舱")])
    raw = {"data": {"fareList": [fare],
                    "flightList": {"3U1953#2026-10-06#URC#SHA": {
                        "airlineCompany": "川航",
                        "departureTime": "10:10",
                        "arrivalTime": "15:00",
                        "departureDate": "2026-10-06",
                        "arrivalDate": "2026-10-06",
                        "flightTime": "290"}}}}
    offers = TuniuCrawler._parse_offers(raw)
    assert offers[0]["cabin"] == "公务舱"


def test_propagate_cabin_source_cleaned():
    """补全源过清污门：tuniu 行假「公务舱」（价位矛盾）不得作为
    补全源传给同物理班无 bizPrice 的行（渲染门对无 bizPrice 行
    「不可内证放行」——传染即假高档词上推送）。"""
    from core.alerter import Alerter
    bad = {"code": "3U1953", "depDate": "2026-10-06",
           "depTime": "10:10", "arrTime": "15:00",
           "arrDate": "2026-10-06", "platform": "tuniu",
           "price": 3310.0, "cabin": "公务舱", "bizPrice": 8340.0}
    victim = {"code": "3U1953", "depDate": "2026-10-06",
              "depTime": "10:10", "arrTime": "15:00",
              "arrDate": "2026-10-06", "platform": "ctrip",
              "price": 3310.0}
    Alerter._propagate_fields([bad, victim])
    assert victim.get("cabin", "") == ""


def test_propagate_cabin_genuine_still_propagates():
    """真高档舱名（price==bizPrice）补全照常——补全物理属性的
    机制本身不受影响。"""
    from core.alerter import Alerter
    good = {"code": "MU1234", "depDate": "2026-10-06",
            "depTime": "08:30", "arrTime": "11:20",
            "arrDate": "2026-10-06", "platform": "ctrip",
            "price": 8340.0, "cabin": "公务舱", "bizPrice": 8340.0}
    victim = {"code": "MU1234", "depDate": "2026-10-06",
              "depTime": "08:30", "arrTime": "11:20",
              "arrDate": "2026-10-06", "platform": "qunar",
              "price": 8340.0}
    Alerter._propagate_fields([good, victim])
    assert victim.get("cabin") == "公务舱"


# ---- 恒空死键不落 ----

def test_tuniu_dterminal_empty_no_key():
    """dTerminal 渠道恒空串（46/46）：depTerminal 不落键（无值
    不落键族律）；有值照落。"""
    fare = _tj_fare([(1500, "经济舱")])
    det_base = {"airlineCompany": "川航",
                "departureTime": "10:10", "arrivalTime": "15:00",
                "departureDate": "2026-10-06",
                "arrivalDate": "2026-10-06", "flightTime": "290"}
    raw = {"data": {"fareList": [fare],
                    "flightList": {"3U1953#2026-10-06#URC#SHA":
                                   dict(det_base)}}}
    offers = TuniuCrawler._parse_offers(raw)
    assert "depTerminal" not in offers[0]

    raw2 = {"data": {"fareList": [fare],
                     "flightList": {"3U1953#2026-10-06#URC#SHA":
                                    dict(det_base, aTerminal="T2")}}}
    offers2 = TuniuCrawler._parse_offers(raw2)
    assert offers2[0].get("arrTerminal") == "T2"


def test_tuniu_terminal_empty_no_key_row_layer():
    """行层（DB extra 面）同守无值不落键：offer 层不落键后，行层
    str(o.get(...)) 恒产空串、空串键照落=卫生项半落地（审查 P2-1）。
    全链 _parse_offers→_offers_to_flights 断键不在；aTerminal 有值
    照落（同族对照：tongcheng transferBaggage 条件展开就在最终行）。"""
    fare = _tj_fare([(1500, "经济舱")])
    det_base = {"airlineCompany": "川航",
                "departureTime": "10:10", "arrivalTime": "15:00",
                "departureDate": "2026-10-06",
                "arrivalDate": "2026-10-06", "flightTime": "290"}
    raw = {"data": {"fareList": [fare],
                    "flightList": {"3U1953#2026-10-06#URC#SHA":
                                   dict(det_base)}}}
    rows = TuniuCrawler._offers_to_flights(TuniuCrawler._parse_offers(raw))
    assert rows
    assert "depTerminal" not in rows[0]
    assert "arrTerminal" not in rows[0]

    raw2 = {"data": {"fareList": [fare],
                     "flightList": {"3U1953#2026-10-06#URC#SHA":
                                    dict(det_base, aTerminal="T2")}}}
    rows2 = TuniuCrawler._offers_to_flights(
        TuniuCrawler._parse_offers(raw2))
    assert rows2[0].get("arrTerminal") == "T2"


def test_tc_transfer_baggage_empty_no_key():
    """transferBaggage 三态外的行恒空串：不落空串键（消费端
    ==direct 判定缺键等价，flightnorm setdefault 兜内存形态）。"""
    ss = [{"fn": "CZ6981", "dt": "2026-10-05 13:20",
           "at": "2026-10-05 16:05"},
          {"fn": "MU5700", "dt": "2026-10-05 18:20",
           "at": "2026-10-05 21:30"}]
    fp = {"dt": "2026-10-05 13:20", "at": "2026-10-05 21:30",
          "sd": "2h45m", "td": "8h10m", "sc": "张掖", "ss": ss,
          "lps": [{"atp": 1500, "brs": [{"al": 5}],
                   "pts": [{"td": "6.8折经济舱"}]}]}
    rows = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp]}}), "11")
    assert rows
    assert "transferBaggage" not in rows[0]


# ---- merged from tests/test_v1563_fields.py ----

_PC_DATE = "2026-10-06"


def _pc(**kw):
    b2 = {
        "depTime": "06:50", "arrTime": "09:10",
        "arrDate": "2026-10-07",
        "depTerminal": "T5", "depAirport": "咸阳机场",
    }
    b2.update(kw.pop("b2", {}))
    flight = {
        "minPrice": 2000, "code": kw.pop("code", "GS7495/9C6178"),
        "transCity": kw.pop("transCity", "西安"),
        "binfo1": {
            "depTime": "19:25", "arrTime": "21:40",
            "date": _PC_DATE, "arrTerminal": "T3",
            "arrAirport": "咸阳机场",
        },
        "binfo2": b2,
    }
    flight.update(kw)
    return json.dumps({"data": {"flights": [flight]}}, ensure_ascii=False)


def test_pc_lay2dep_independent():
    """真独立二段起飞（≠整体起飞）落 HH:MM；直飞行无值不落键
    （r234 收口：空串曾 ×276 落库，与 ctrip/tongcheng 缺席口径对齐）。"""
    out = QunarCrawler._parse_pc_flights(_pc(), _PC_DATE)
    t = out[0]
    assert t["lay2dep"] == "06:50"
    assert t["layover"] > 0  # 衔接与二段起飞配对自洽

    direct = json.dumps({"data": {"flights": [{
        "minPrice": 2000, "code": "9C8866",
        "binfo": {"depTime": "08:00", "arrTime": "11:30",
                  "date": _PC_DATE, "arrDate": _PC_DATE},
    }]}})
    d = QunarCrawler._parse_pc_flights(direct, _PC_DATE)[0]
    assert "lay2dep" not in d and "transDepTerminal" not in d


def test_pc_lay2dep_copy_guard():
    """H5 防复制态守卫同律：b2.depTime==整体起飞 → 不落
    （防渠道复制态回潮吐假「二段」时刻）。"""
    out = QunarCrawler._parse_pc_flights(
        _pc(b2={"depTime": "19:25"}), _PC_DATE)
    assert "lay2dep" not in out[0]
    # 缺键同样不落
    out = QunarCrawler._parse_pc_flights(
        _pc(b2={"depTime": ""}), _PC_DATE)
    assert "lay2dep" not in out[0]


def test_pc_trans_dep_terminal_cross_building():
    """真跨楼（T3 到 T5 出）落「咸阳T5」：depAirport 剥「机场」后缀
    +楼号，与 trans_term「咸阳T3」同型配对。"""
    out = QunarCrawler._parse_pc_flights(_pc(), _PC_DATE)
    t = out[0]
    assert t["transTerminal"] == "咸阳T3"
    assert t["transDepTerminal"] == "咸阳T5"


def test_pc_trans_dep_terminal_same_building_dropped():
    """H5 同律「与到达楼同楼无增量不落」；空串/缺键同不落键。"""
    same = _pc(b2={"depTerminal": "T3"})
    assert "transDepTerminal" not in QunarCrawler._parse_pc_flights(
        same, _PC_DATE)[0]
    empty = _pc(b2={"depTerminal": ""})
    assert "transDepTerminal" not in QunarCrawler._parse_pc_flights(
        empty, _PC_DATE)[0]


# ---- merged from tests/test_v162_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---- qunar PC：binfo2 经停两键回退（挂起④阈值 ≥3/144 触发，
# 调研样本 GS7511/HO1108 二段停陇南；binfo2.stopTime 键级不存在，
# 挂起三元组缩两键——stopTime 维持 binfo 层现状） ----

def _pc_flight(**kw):
    f = {"code": "GS7511/HO1108", "minPrice": "2472", "transCity": "兰州",
         "binfo1": {"airCode": "HO1108", "shortName": "吉祥",
                    "depTime": "08:00", "arrTime": "10:30",
                    "date": "2026-10-06", "arrDate": "2026-10-06",
                    "stopCitys": [], "stopAirports": []},
         "binfo2": {"depTime": "12:30", "arrTime": "14:40",
                    "arrDate": "2026-10-06",
                    "stopCitys": [], "stopAirports": []}}
    f.update(kw)
    return f


def _pc_text(*flights):
    return json.dumps({"ret": True, "code": 0,
                       "data": {"flights": list(flights)}})


def test_qunar_pc_stopcitys_binfo2_fallback():
    """b1 空数组时回退 binfo2（中转二段经停真值位，13:20/13:21 dump
    3/144：GS7511/HO1108 二段停陇南）；b1 有值优先不回退；直飞行
    （无 binfo2）行为零变化；join 后剥前导/尾部分隔符伪影（H5
    「,庆阳」同型卫生）。"""
    f = _pc_flight()
    f["binfo2"]["stopCitys"] = ["陇南"]
    f["binfo2"]["stopAirports"] = ["陇南成县机场"]
    fl = QunarCrawler._parse_pc_flights(_pc_text(f), "2026-10-06")
    assert fl[0]["stopCitys"] == "陇南"
    # stopAirports 退役（r224 载荷卫生）：输入侧形态保留（dump 实存），
    # 钉面翻转=不得随行出解析器（零消费孤儿键）
    assert "stopAirports" not in fl[0], fl[0]
    # b1 有值优先
    f2 = _pc_flight()
    f2["binfo1"]["stopCitys"] = ["张掖"]
    fl2 = QunarCrawler._parse_pc_flights(_pc_text(f2), "2026-10-06")
    assert fl2[0]["stopCitys"] == "张掖"
    # 直飞行（binfo 形态、无 binfo2）b1 值照采、空数组落空串
    direct = {"code": "FM9223", "minPrice": "2472", "transCity": "",
              "binfo": {"airCode": "FM9223", "shortName": "上航",
                        "depTime": "19:55", "arrTime": "01:25",
                        "date": "2026-10-06", "arrDate": "2026-10-07",
                        "stopCitys": ["银川"], "stopAirports": []}}
    fl3 = QunarCrawler._parse_pc_flights(_pc_text(direct), "2026-10-06")
    assert fl3[0]["stopCitys"] == "银川"
    # 数组含空串元素（渠道「,庆阳」变体）：join 出「;庆阳」剥成「庆阳」
    f4 = _pc_flight()
    f4["binfo2"]["stopCitys"] = ["", "庆阳"]
    fl4 = QunarCrawler._parse_pc_flights(_pc_text(f4), "2026-10-06")
    assert fl4[0]["stopCitys"] == "庆阳"
    # b1 全空元素不阻断回退（：join 真值判「;」曾吃掉 b2 真值）
    f5 = _pc_flight()
    f5["binfo1"]["stopCitys"] = [""]
    f5["binfo2"]["stopCitys"] = ["陇南"]
    fl5 = QunarCrawler._parse_pc_flights(_pc_text(f5), "2026-10-06")
    assert fl5[0]["stopCitys"] == "陇南"


# ---- qunar PC：binfo.transNotice 并入 labels（H5 层级修复
# 同款信号，PC _labels_of 只读 priceLabel 漏读，4/144 且 3/4 行
# priceLabel 为空=背书整行丢失） ----

def test_qunar_pc_labels_transnotice_merged():
    """「华夏联程」航司自营联程背书：b1 层（binfo/binfo1）主源、顶层
    兜底，「转/停」占位排除——与 H5 _h5_labels_of 同律；去重；
    _LABEL_MAX=3 容量不足时不挤掉 priceLabel 现有名。"""
    f = _pc_flight()
    f["binfo1"]["transNotice"] = "华夏联程"
    fl = QunarCrawler._parse_pc_flights(_pc_text(f), "2026-10-06")
    assert fl[0]["labels"] == "华夏联程"
    # 与 priceLabel 共存：去重联接
    f["priceLabel"] = [{"name": "联程航班服务"}]
    fl2 = QunarCrawler._parse_pc_flights(_pc_text(f), "2026-10-06")
    assert fl2[0]["labels"] == "联程航班服务·华夏联程"
    # 占位排除：顶层「转」不采（PC 顶层若下发占位形态）
    f["binfo1"]["transNotice"] = ""
    f["transNotice"] = "转"
    fl3 = QunarCrawler._parse_pc_flights(_pc_text(f), "2026-10-06")
    assert fl3[0]["labels"] == "联程航班服务"
    # 容量 3 满时不挤掉既有名（priceLabel 全决策词优先）
    f["transNotice"] = "华夏联程"
    f["priceLabel"] = [
        {"name": "取消延误免费改"}, {"name": "宠物友好"}, {"name": "免费上网"}]
    fl4 = QunarCrawler._parse_pc_flights(_pc_text(f), "2026-10-06")
    assert fl4[0]["labels"] == "取消延误免费改·宠物友好·免费上网"


# ---- qunar H5：stopCitys 前导「;」伪影（渠道「,庆阳」经 
# 逗号归一成「;庆阳」，strip(";") 判空放行了前导分隔符，DB 99 行） ----

def _h5_row(**extra):
    f = {"minPrice": 1200, "code": "HO1068/CZ6798",
         "mixFlightName": "吉祥HO1068", "transCity": "庆阳",
         "binfo": {"depTime": "16:40", "arrTime": "21:30",
                   "depDate": "2026-10-06", "arrDate": "2026-10-06"},
         "extparams": "{}"}
    f.update(extra)
    return f


def test_qunar_h5_stopcitys_leading_separator():
    """「,庆阳」→ 归一「;庆阳」→ 剥前导分隔符「庆阳」；尾分隔符同律；
    纯分隔符「,」无值不落（r241 残留族收口，口径不回退）；
    多城真值不受影响。"""
    cases = ((",庆阳", "庆阳"), ("庆阳,", "庆阳"),
             ("西安,库尔勒", "西安;库尔勒"), (",", ""))
    for raw, want in cases:
        f = _h5_row(binfo={"depTime": "16:40", "arrTime": "21:30",
                           "depDate": "2026-10-06", "arrDate": "2026-10-06",
                           "stopsCitys": raw, "stopsAirPort": raw})
        rows = QunarCrawler._extract_flights_obj([f])
        if want:
            assert rows[0]["stopCitys"] == want, raw
        else:
            assert "stopCitys" not in rows[0], (raw, rows[0])
        # stopsAirPort 半边退役（r224）：输入保留、输出不得携带
        assert "stopAirports" not in rows[0], (raw, rows[0])


# ---- tongcheng：行级直挂证据（stss ServiceType=LUGGAGE 双门 →
# transferBaggage='direct'；现版页面级 doc 图例五词恒全并存，
# direct_only 恒 False → 全库 direct=0 真实信息损失，DB 44 行/日） ----

def _tc_transfer_fp(stss=None, doc=None):
    fp = {"dt": "2026-10-06 08:00", "at": "2026-10-07 18:00",
          "sd": "2h15m", "td": "9h30m", "sc": "兰州",
          "ss": [{"fn": "GS7511", "aat": "T3"},
                 {"fn": "HO1108", "dat": "T5"}],
          "lps": [{"atp": 1800, "brs": [{"al": 3}]}]}
    if stss is not None:
        fp["stss"] = stss
    _doc = {"luggageSelf": 1, "luggageAgain": 1}  # 两日 dump 恒全并存形态
    if doc:
        _doc.update(doc)
    return json.dumps({"data": {"fps": [fp], "doc": _doc}})


def _tc_bag(text):
    rows = TongchengCrawler._extract_transfer_flights(text)
    # 空串键已按「无值不落键」退役（r226）：非 direct 行缺键
    return rows[0].get("transferBaggage")


def test_tongcheng_transfer_baggage_row_evidence():
    """行级双门：ServiceType=='LUGGAGE' 且 ServiceName 白名单（行李
    直达/免提取托运行李）才置 direct；LUGGAGE_DEPOSIT（免费行李寄存）
    与缺 ServiceType 不混入（宁缺勿错）。"""
    assert _tc_bag(_tc_transfer_fp(stss=[
        {"ServiceType": "LUGGAGE", "ServiceName": "行李直达"}])) == "direct"
    assert _tc_bag(_tc_transfer_fp(stss=[
        {"ServiceType": "LUGGAGE", "ServiceName": "免提取托运行李"}])) == "direct"
    assert _tc_bag(_tc_transfer_fp(stss=[
        {"ServiceType": "LUGGAGE_DEPOSIT",
         "ServiceName": "免费行李寄存"}])) is None
    assert _tc_bag(_tc_transfer_fp(stss=[
        {"ServiceName": "行李直达"}])) is None
    assert _tc_bag(_tc_transfer_fp(stss=[
        {"ServiceType": "TRANSFER_HOTEL", "ServiceName": "免费住宿"}])) is None


def test_tongcheng_transfer_baggage_lcc_guard():
    """任段廉航不落（flightnorm「春秋大概率不直挂」同律）：9C 段+
    行级证据不置 direct；全干线照置。"""
    fp = {"dt": "2026-10-06 08:00", "at": "2026-10-07 18:00",
          "sd": "2h15m", "td": "9h30m", "sc": "兰州",
          "ss": [{"fn": "9C7372", "aat": "T3"},
                 {"fn": "HO1068", "dat": "T5"}],
          "stss": [{"ServiceType": "LUGGAGE", "ServiceName": "行李直达"}],
          "lps": [{"atp": 1800, "brs": [{"al": 3}]}]}
    text = json.dumps({"data": {"fps": [fp],
                                "doc": {"luggageSelf": 1,
                                        "luggageAgain": 1}}})
    assert _tc_bag(text) is None


def test_tongcheng_transfer_baggage_luggage_pass_s6():
    """S6 三门（LUGGAGE_PASS 类目 /「享行李直挂」词面）：10-16 济南中转
    SC8714/SC1163 两个独立抓取轮复现同串 ServiceId，SC 非廉航不挡、
    反例 0——既有 LUGGAGE 双门不认此新形态，直挂信息以 transferService
    词面在场而二值标记缺席。同族守卫不变：LUGGAGE_DEPOSIT 不混入、
    廉航任段不落。"""
    assert _tc_bag(_tc_transfer_fp(stss=[
        {"ServiceType": "LUGGAGE_PASS", "ServiceName": "享行李直挂"}])) == "direct"
    assert _tc_bag(_tc_transfer_fp(stss=[
        {"ServiceName": "享行李直挂"}])) == "direct"
    # 同类目不混入与缺类型门形态维持（宁缺勿错）
    assert _tc_bag(_tc_transfer_fp(stss=[
        {"ServiceType": "LUGGAGE_DEPOSIT",
         "ServiceName": "免费行李寄存"}])) is None
    assert _tc_bag(_tc_transfer_fp(stss=[
        {"ServiceName": "行李直达"}])) is None


def test_tongcheng_transfer_baggage_lcc_guard_s6():
    """廉航任段不落对新门同样生效：9C 段 + LUGGAGE_PASS 证据不置 direct。"""
    fp = {"dt": "2026-10-16 08:00", "at": "2026-10-16 18:00",
          "sd": "2h15m", "td": "9h30m", "sc": "济南",
          "ss": [{"fn": "9C7372", "aat": "T3"},
                 {"fn": "SC1163", "dat": "T5"}],
          "stss": [{"ServiceType": "LUGGAGE_PASS",
                    "ServiceName": "享行李直挂"}],
          "lps": [{"atp": 1800, "brs": [{"al": 3}]}]}
    text = json.dumps({"data": {"fps": [fp],
                                "doc": {"luggageSelf": 1,
                                        "luggageAgain": 1}}})
    assert _tc_bag(text) is None


def test_tongcheng_transfer_baggage_legacy_legend_path():
    """图例唯一含 luggageSelf（无 luggageAgain）→ direct（    既有路径零回退）；图例全并存+行级证据 → direct（行级证据救回）。"""
    assert _tc_bag(_tc_transfer_fp(
        doc={"luggageSelf": 1, "luggageAgain": 0})) == "direct"
    assert _tc_bag(_tc_transfer_fp(stss=[
        {"ServiceType": "LUGGAGE", "ServiceName": "行李直达"}],
        doc={"luggageSelf": 1, "luggageAgain": 1})) == "direct"
    # 图例全并存+无行级证据维持缺键（三态「缺=未知」语义不破；
    # 空串形态已按无值不落键退役，消费端 ==direct 判定缺键等价）
    assert _tc_bag(_tc_transfer_fp()) is None


# ---- merged from tests/test_v178_fields.py ----

# ---- cross_days 双信号降信守卫（observe_v178 §1b qunar PC 毒形态） ----

def _f(**kw):
    base = {"depDate": "2026-10-05", "arrDate": "2026-10-05",
            "depTime": "20:35", "arrTime": "20:50",
            "crossDayDesc": "+1天", "totalDuration": "24时15分"}
    base.update(kw)
    return base


def test_pc_poison_arrdate_outvoted():
    """qunar PC 经停行毒形态（实证 G581O1J：arrDate=当日，desc=+1天、
    时长 24时15分 双信号一致指 +1）→ 降信 arrDate 取 1。"""
    assert _xd(_f()) == 1


def test_arrdate_holds_single_signal():
    """仅 desc 矛盾（时长重算无匹配档）：arrDate 仍优先——单信号不降信，
    防「携程中转只给首段时长」类误杀（layoverSrc 先例反向）。"""
    assert _xd(_f(totalDuration="2时00分")) == 0


def test_arrdate_holds_signals_agree():
    """desc/时长与 arrDate 一致：原行为不变。"""
    assert _xd(_f(arrDate="2026-10-06")) == 1


def test_arrdate_outvoted_two_days():
    """双信号一致指 +2：同规则外推。"""
    assert _xd(_f(crossDayDesc="+2天", totalDuration="48时15分")) == 2


def _pl(black=None, plain=None, disc="6.7折"):
    """构造 flightPriceList：supportBlack true/false 各一政策。"""

    def _pr(sb, fare):
        return {"supportBlack": sb,
                "fareBreakdownList": [
                    {"psgType": "ADT", "baseFare": fare, "discount": disc}]}

    out = []
    if black is not None:
        out.append(_pr(True, black))
    if plain is not None:
        out.append(_pr(False, plain))
    return out


def test_black_min_price_flagged():
    """选中最低价来自黑卡政策 → 价格不变、blackCard=True。"""
    p, d, black, _std, _cab, _code = TuniuCrawler._adt_fare(
        _pl(black=2900, plain=4730))
    assert p == 2900.0 and d == "6.7折" and black is True


def test_plain_min_price_unflagged():
    """最低价来自普通政策 → 不落 blackCard 旗标。"""
    p, d, black, _std, _cab, _code = TuniuCrawler._adt_fare(
        _pl(black=5000, plain=4730))
    assert p == 4730.0 and black is False


def test_only_black_policies_flagged():
    """42/117 报价单仅有黑卡政策：价格保持黑卡价 + 旗标（勿丢行）。"""
    p, d, black, _std, _cab, _code = TuniuCrawler._adt_fare(_pl(black=2900))
    assert p == 2900.0 and black is True


def test_tie_prefers_plain():
    """黑卡/普通同价：按普通政策算（无旗标价优先，标记零误报）。"""
    p, d, black, _std, _cab, _code = TuniuCrawler._adt_fare(
        _pl(black=4730, plain=4730))
    assert p == 4730.0 and black is False


def test_empty_policy_list():
    """无政策：六元组 (None, '', False, None, '', '') 不变。"""
    assert TuniuCrawler._adt_fare([]) == (None, "", False, None, "", "")


def test_offer_row_carries_blackcard():
    """offer→row 透传：黑卡旗标行落 extra.blackCard=True（有值才落）。"""
    rows = TuniuCrawler._offers_to_flights([{
        "airline": "东方航空", "flight_no": "MU5634",
        "depart_time": "08:30", "arrive_time": "11:50",
        "dep_date": "2026-10-05", "arr_date": "2026-10-05",
        "price": 2900.0, "blackCard": True,
    }, {
        "airline": "东方航空", "flight_no": "MU5635",
        "depart_time": "09:30", "arrive_time": "12:50",
        "dep_date": "2026-10-05", "arr_date": "2026-10-05",
        "price": 4730.0,
    }])
    assert rows[0]["blackCard"] is True
    assert "blackCard" not in rows[1]


# ---- merged from tests/test_v181_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---- 样本基座（同 v1554 PC 预案样本形态） ----

_PC_BASE = {
    "code": "FM9223", "minPrice": "2472", "transCity": "",
    "extparams": {"childPrice": 0, "infantPrice": None},
    "binfo": {"airCode": "FM9223", "shortName": "上航",
              "depTime": "19:55", "arrTime": "01:25",
              "date": "2026-10-04", "arrDate": "2026-10-05",
              "flightTime": "5h30m",
              "depTerminal": "", "arrTerminal": "T2",
              "depAirport": "乌鲁木齐天山", "arrAirport": "虹桥机场",
              "planeFullType": "空客330(大)"},
}


def _pc_raw(refund_rule=None, latetime=None):
    fl = copy.deepcopy(_PC_BASE)
    if refund_rule is not None:
        fl["extparams"]["refundChangeRule"] = refund_rule
    if latetime is not None:
        # 生产 dump 真实结构：lateTime 在 binfo 分段层（顶层恒缺，
        # v1.5.82 B1 读层修复时实证——自造顶层形态=假镜像教训）
        fl["binfo"]["lateTime"] = latetime
    return json.dumps({"ret": True, "code": 0,
                       "data": {"flights": [fl]}})


# ---- D-1 退改费结构化双键：PC 路径 ----

def test_qunar_pc_refund_fee_int_keys():
    fl = QunarCrawler._parse_pc_flights(
        _pc_raw(refund_rule='{"returnFee":366,"changeFee":0}'),
        "2026-10-04")
    f = fl[0]
    assert f["returnFee"] == 366 and isinstance(f["returnFee"], int)
    assert f["changeFee"] == 0 and isinstance(f["changeFee"], int)
    # 原 JSON 串键保持不动（既有消费兼容）
    assert f["refundChange"] == '{"returnFee":366,"changeFee":0}'


def test_qunar_pc_refund_fee_minus1_change_kept():
    # changeFee=-1 渠道「不可改」语义如实保留（与 refundChange 串同协议）
    fl = QunarCrawler._parse_pc_flights(
        _pc_raw(refund_rule='{"returnFee":430,"changeFee":-1}'),
        "2026-10-04")
    f = fl[0]
    assert f["returnFee"] == 430
    assert f["changeFee"] == -1


def test_qunar_pc_refund_fee_absent_not_set():
    # 规则缺失/空串不落键（宁缺勿错，无值不占位）
    fl = QunarCrawler._parse_pc_flights(_pc_raw(), "2026-10-04")
    assert "returnFee" not in fl[0]
    assert "changeFee" not in fl[0]


def test_qunar_pc_refund_fee_bad_json_not_set():
    fl = QunarCrawler._parse_pc_flights(
        _pc_raw(refund_rule='not-json'), "2026-10-04")
    assert "returnFee" not in fl[0]


# ---- D-1 退改费结构化双键：H5 路径 ----

_H5_BASE = {
    "code": "GS7587", "price": 800, "minPrice": 800,
    "crossDayDesc": "+1天", "transCity": "石家庄",
    "transTime": "17时25分",
    "binfo1": {"depTime": "14:30", "arrTime": "00:20",
               "depDate": "2026-10-06", "arrDate": "2026-10-07",
               "codeShare": False, "depTerminal": "", "arrTerminal": "T2"},
}


def _h5_raw(refund_rule=None):
    fl = copy.deepcopy(_H5_BASE)
    if refund_rule is not None:
        fl["extparams"] = json.dumps(
            {"refundChangeRule": refund_rule}, ensure_ascii=False)
    return json.dumps({"ret": True, "data": json.dumps(
        {"flights": [fl]})})


def test_qunar_h5_refund_fee_int_keys():
    fl = QunarCrawler._parse_response_flights(
        _h5_raw('{"returnFee":199,"changeFee":199}'))
    f = fl[0]
    assert f["returnFee"] == 199 and isinstance(f["returnFee"], int)
    assert f["changeFee"] == 199 and isinstance(f["changeFee"], int)
    assert f["refundChange"] == '{"returnFee":199,"changeFee":199}'


def test_qunar_h5_refund_fee_absent_not_set():
    fl = QunarCrawler._parse_response_flights(_h5_raw())
    assert "returnFee" not in fl[0]


# ---- D-2 lateTime→avgDelay 出口键统一：PC 路径 ----

def test_qunar_pc_latetime_to_avgdelay():
    fl = QunarCrawler._parse_pc_flights(_pc_raw(latetime="-10"),
                                        "2026-10-04")
    f = fl[0]
    assert f["avgDelay"] == -10 and isinstance(f["avgDelay"], int)


def test_qunar_pc_latetime_invalid_not_set():
    fl = QunarCrawler._parse_pc_flights(_pc_raw(latetime="abc"),
                                        "2026-10-04")
    assert "avgDelay" not in fl[0]


def test_qunar_pc_latetime_absent_not_set():
    fl = QunarCrawler._parse_pc_flights(_pc_raw(), "2026-10-04")
    assert "avgDelay" not in fl[0]


# ---- merged from tests/test_v191_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t1591")


# ---- fliggy：has-food-label 双态 ----

def test_fliggy_meal_positive_label():
    """机型行同行尾「有餐食」正向标签落 meal 既有键，值与负向同槽；
    无标签行仍不落（不打标）。"""
    txt = ("南航CZ6917\n中型机 737 有餐食\n09:15\n13:50\n"
           "乌鲁木齐天山国际机场\n虹桥国际机场T2\n¥920 5.0折")
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-05")
    hit = [r for r in rows if r.get("code") == "CZ6917"]
    assert hit and hit[0]["meal"] == "有餐食", rows


def test_fliggy_meal_negative_label_unregressed():
    """负向「无餐食」行为不变（双态扩充零回归）。"""
    txt = ("春秋9C7006\n中型机 320 无餐食\n15:15\n21:30\n"
           "乌鲁木齐天山国际机场\n虹桥国际机场T1\n¥620 5.0折")
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-05")
    hit = [r for r in rows if r.get("code") == "9C7006"]
    assert hit and hit[0]["meal"] == "无餐食", rows


def test_fliggy_meal_transfer_second_leg_positive():
    """中转块二段机型行「有餐食」随 pend 搬运进合并行（与负向同值
    域同路径），首段已标时不覆盖（setdefault）。"""
    txt = "\n".join([
        "南航CZ8232", "中型机 73N",           # 首段（pend，无标签）
        "南航CZ8232", "中型机 73N 有餐食",    # 二段（cur，正向）
        "10月06日 08:00", "10月06日 11:05",   # 首段起/落
        "10月06日 12:20", "10月06日 14:30",   # 二段起/落
        "乌鲁木齐天山国际机场", "兰州中转", "虹桥国际机场T2",
        "100.0%", "约7小时",
        "¥1180 5.5折", "¥120机建燃油", "订票",
    ])
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-06")
    hit = [r for r in rows if r.get("code") == "CZ8232/CZ8232"]
    assert hit and hit[0].get("meal") == "有餐食", rows


# ---- tuniu：discount 空串占位键卫生（观测 before：35/611≈5.7% 空串
# 落键，avgDelay 无值不落键同族） ----

_TN_FLIGHT = {
    "airlineCompany": "东航",
    "departureTime": "20:20", "arrivalTime": "01:15",
    "departureDate": "2026-10-06", "arrivalDate": "2026-10-07",
    "flightTime": "295",
}


def _tn_row_disc(fare_discount):
    d = dict(_TN_FLIGHT)
    raw = {"data": {"fareList": [{
        "flightOptions": [{"flightNos": "MU8370"}],
        "flightPriceList": [{"fareBreakdownList": [
            {"baseFare": 3600, "psgType": "ADT",
             "discount": fare_discount}]}],
    }], "flightList": {"MU8370#2026-10-06#URC#SHA": d}}}
    rows = TuniuCrawler._offers_to_flights(TuniuCrawler._parse_offers(raw))
    assert rows
    return rows[0]


def test_tuniu_discount_value_kept():
    """有值「6.7折」照落（正路零变化）。"""
    assert _tn_row_disc("6.7折")["discount"] == "6.7折"


def test_tuniu_discount_empty_no_key():
    """空串：无值不落键（avgDelay 同族键卫生）。"""
    assert "discount" not in _tn_row_disc("")


def test_tuniu_discount_zero_placeholder_no_key():
    """「0」占位：_adt_fare 既有过滤后落空串——一并转无键。"""
    assert "discount" not in _tn_row_disc("0")


def test_tuniu_discount_missing_no_key():
    """报文无 discount 字段：不落键（原空串占位形态关闭）。"""
    d = dict(_TN_FLIGHT)
    raw = {"data": {"fareList": [{
        "flightOptions": [{"flightNos": "MU8370"}],
        "flightPriceList": [{"fareBreakdownList": [
            {"baseFare": 3600, "psgType": "ADT"}]}],
    }], "flightList": {"MU8370#2026-10-06#URC#SHA": d}}}
    rows = TuniuCrawler._offers_to_flights(TuniuCrawler._parse_offers(raw))
    assert rows and "discount" not in rows[0]


def test_fliggy_meal_transfer_conflict_conservative():
    """中转两段餐食标签相反：合并行保守仲裁为「无餐食」（一段无
    餐食=全程存在无餐食段，正向优先会掩蔽该事实）。"""
    txt = "\n".join([
        "南航CZ6646", "中型机 32N 无餐食",    # 首段（pend）负向
        "南航CZ6646", "中型机 32N 有餐食",    # 二段（cur）正向（掩蔽场景）
        "10月06日 08:00", "10月06日 11:05",   # 首段起/落
        "10月06日 12:20", "10月06日 14:30",   # 二段起/落
        "乌鲁木齐天山国际机场", "兰州中转", "虹桥国际机场T2",
        "100.0%", "约7小时",
        "¥1180 5.5折", "¥120机建燃油", "订票",
    ])
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-06")
    hit = [r for r in rows if r.get("code") == "CZ6646/CZ6646"]
    assert hit and hit[0].get("meal") == "无餐食", rows


# ---- merged from tests/test_v199_fields.py ----

# ==================== L1: ctrip 衔接真值豁免标记 ====================

class TestCtripLayoverTruthExempt:
    """ctrip 两段起降差衔接=结构化真值，带 layoverSrc="times" 标记
    后 flightnorm 1440 击杀区豁免；物理守卫照杀不豁免。"""

    @staticmethod
    def _parse(item):
        from crawlers.ctrip import CtripCrawler
        return CtripCrawler._extract_ctrip_flights(
            CtripCrawler, json.dumps({"fltitem": [item]},
                                     ensure_ascii=False))

    @staticmethod
    def _transfer_item():
        """CZ6909/CZ8882 同构：首段 08:00→11:30，停 21h，次段
        08:30→11:00（+1天）——lay=1260、dur=1620，(lay+dur)%1440=0
        落击杀区。"""
        seg = lambda fn, dp, ap, dd, ad: {
            "basinfo": {"flgno": fn},
            "dateinfo": {"ddate": dd, "adate": ad},
            "dportinfo": {"city": dp}, "aportinfo": {"city": ap}}
        return {"mutilstn": [
            seg("CZ6909", "乌鲁木齐", "西安",
                "2026-10-05 08:00:00", "2026-10-05 11:30:00"),
            seg("CZ8882", "西安", "上海",
                "2026-10-06 08:30:00", "2026-10-06 11:00:00")],
            "policyinfo": [{"tprice": 1500, "quantity": 3,
                            "classinfor": [
                                {"cgrd": 0, "prate": 96, "meal": ""}]}]}

    def test_row_carries_truth_mark(self):
        rows = self._parse(self._transfer_item())
        assert rows, "夹具应产出中转行"
        assert rows[0].get("layover") == 1260, \
            f"衔接真值应原样落键：{rows[0].get('layover')!r}"
        assert rows[0].get("layoverSrc") == "times", \
            "真值行缺 layoverSrc 标记（1440 启发式将误杀）"

    def test_truth_survives_normalize(self):
        row = self._parse(self._transfer_item())[0]
        flightnorm.normalize(row, "2026-10-05")
        assert row.get("layoverT") == "21:00", \
            f"真衔接被启发式击杀置空：{row.get('layoverT')!r}"
        assert row.get("layoverM") == 1260

    def test_physical_guard_not_exempted(self):
        """豁免只挡 1440 启发式：衔接≥全程/飞行剩余<60 分的物理
        守卫照杀（真值标记不得复活渠道分段错值）。"""
        row = self._parse(self._transfer_item())[0]
        row["layover"] = 1700          # ≥ 全程 1620
        row["layoverSrc"] = "times"
        flightnorm.normalize(row, "2026-10-05")
        assert row.get("layoverM") == 0 and row.get("layoverT") == ""

    def test_direct_row_no_mark(self):
        """直飞行无衔接不落标记（有值才落，宁缺勿错）。"""
        it = {"mutilstn": [{"basinfo": {"flgno": "MU5137"},
                            "dateinfo": {"ddate": "2026-10-05 08:00:00",
                                         "adate": "2026-10-05 11:30:00"},
                            "aportinfo": {"city": "上海"}}],
              "policyinfo": [{"tprice": 1200, "quantity": 3,
                              "classinfor": [
                                  {"cgrd": 0, "prate": 96, "meal": ""}]}]}
        rows = self._parse(it)
        assert rows and "layoverSrc" not in rows[0]


# ==================== L2: AIRPORT_CN 补录 ====================

class TestAirportCnSupplement:
    """中转城市裸码补录（7 天 DB 实测 MIG 58/YBP 4 行原样落库），
    WDS/UYN/LYA/YCU 先例同律。"""

    def test_mig_ybp_mapped(self):
        assert flightnorm.AIRPORT_CN.get("MIG") == "绵阳"
        assert flightnorm.AIRPORT_CN.get("YBP") == "宜宾"

    def test_normalize_rewrites_transcity(self):
        row = flightnorm.normalize({"transCity": "MIG"}, "2026-10-05")
        assert row["transCity"] == "绵阳"
        row = flightnorm.normalize({"transCity": "YBP"}, "2026-10-05")
        assert row["transCity"] == "宜宾"


# ---- merged from tests/test_v200_fields.py ----

def _offer(on_time_rate):
    return {
        "price": 1200, "dep_date": "2026-10-06", "arr_date": "2026-10-06",
        "depart_time": "08:30", "arrive_time": "13:10",
        "flight_no": "MU8370", "airline": "东方航空",
        "onTimeRate": on_time_rate,
    }


def test_list_path_prate20_placeholder_purged():
    rows = TuniuCrawler._offers_to_flights([_offer("20%")])
    assert len(rows) == 1
    # v1.5.104 卫生改：占位置空后无值不落键（同族 avgDelay/discount 律），
    # 守卫语义不变——拦的形态从「空串落键」收紧为「无键」
    assert "prate" not in rows[0]


def test_list_path_prate20_bare_number_purged():
    rows = TuniuCrawler._offers_to_flights([_offer("20")])
    assert "prate" not in rows[0]


def test_list_path_prate20_decimal_and_int_purged():
    # "20.0"/数字 20 形态同族（详情页 _prate 已守的窄面，列表路径同口径）
    assert "prate" not in TuniuCrawler._offers_to_flights([_offer("20.0")])[0]
    assert "prate" not in TuniuCrawler._offers_to_flights([_offer(20)])[0]


def test_list_path_prate_truth_kept():
    rows = TuniuCrawler._offers_to_flights([_offer("94%")])
    assert rows[0]["prate"] == "94"


def test_list_path_prate_missing_empty():
    rows = TuniuCrawler._offers_to_flights([_offer(None)])
    assert "prate" not in rows[0]
