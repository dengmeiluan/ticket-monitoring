# -*- coding: utf-8 -*-
"""r275 数据层（渠道调研三采案收编）：

TC-1 tongcheng trendHoliday 裸班/休词面：data.pc[] tag（'班'/'休'）
在 holidayName 空点位的词面（多代 dump 复现：10-15 URC-SHA
{"dd":"2026-10-10","lp":840,"isHoliday":true,"holidayName":"","tag":"班"}、
10-04 休×8）——现行 if hn: 门把未命名班/休日全漏，「调休班日为什么
贵」的价格解释变量零出口。落法 if hn or tag:（零新键，trendHoliday
白名单与消费端 webui 改期窗口柱图 title 已在案零改动）。

TC-2 tongcheng connection 段级共享旗标 isf：fps[].ss[].isf='True'
（10-15 代新增键 42 处、True 恰 1 例 SC5414 段级；与 book1 直飞侧
icsf 同族语义、跨渠道互证 ctrip ishared=True）——connection 行现行
零共享覆盖（shareCarrier 仅直飞路径）。落 labels 词面「N段共享承运」
（段序中文，渠道对段位静默扩展时词面自动正确），实际承运号 ss[] 无
源不落（宁缺勿错）。

CT-1 ctrip aset 地域品牌词第四件「享“皖美中转”休息室服务」
（tcode=G_HFEZZXXS，10-15 新词面 1 例 CZ8513/MU9026 经合肥）：与
郑州/昆明/兰州三件同族对称收编（r247 先例），含「休息室」子串天然
触发 fcode 去重门防重拼。

样本形态取自生产冻结 dump（debug/tongcheng_xhr_2026-10-15、
debug/ctrip_xhr_2026-10-15）。运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r275_fields.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.tongcheng import TongchengCrawler  # noqa: E402
from crawlers.ctrip import CtripCrawler  # noqa: E402

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
