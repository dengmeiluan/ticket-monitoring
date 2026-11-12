# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r256_fields.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import json
import logging
import os
import sys

from crawlers.ctrip import CtripCrawler
from crawlers.qunar import QunarCrawler
from crawlers.tongcheng import TongchengCrawler


# ---- merged from tests/test_r256_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("r256")
_CT = CtripCrawler({}, _LOG)
_QC = QunarCrawler({}, _LOG)


# ---- ①qunar：binfo2.piaoShaoDesc「二段票少」 ----

def _pc_flight(b1=None, b2=None, **top):
    """PC wbdflightlist 行最小载体（与 r240 夹具同构）。"""
    f = {"minPrice": 1200, "code": "CZ6646/MU5464",
         "binfo1": dict({"depTime": "08:00", "arrTime": "11:30",
                         "date": "2026-10-06", "shortCarrier": "CZ",
                         "airCode": "6646"}, **(b1 or {})),
         "binfo2": b2 or {}}
    f.update(top)
    return f


def _pc_text(flights):
    return json.dumps({"data": {"flights": flights}}, ensure_ascii=False)


def _pc_rows(flights):
    rows = _QC._parse_pc_flights(_pc_text(flights), "2026-10-06")
    assert rows, "样本应产出至少一行"
    return rows[0]


def test_qunar_b2_few_ticket_two_seg_word():
    """b1 票少缺席 + b2.piaoShaoDesc=「票少」→ fewTicket=「二段票少」
    （r256 dump 10-06 两例实录形态：现行出口双空、风险不可见）。"""
    r = _pc_rows([
        _pc_flight(b2={"arrTime": "18:20", "arrDate": "2026-10-06",
                       "depTime": "14:00", "piaoShaoDesc": "票少"}),
    ])
    assert r.get("fewTicket") == "二段票少", r


def test_qunar_b1_few_ticket_word_unchanged():
    """b1 票少在场：维持原词「票少」（整行紧张语义不变，b2 状态不
    覆盖首段词面）。"""
    r = _pc_rows([
        _pc_flight(b1={"piaoShaoDesc": "票少"},
                   b2={"arrTime": "18:20", "arrDate": "2026-10-06",
                       "depTime": "14:00", "piaoShaoDesc": "票少"}),
    ])
    assert r.get("fewTicket") == "票少", r


def test_qunar_no_few_ticket_no_key():
    """两端票少均缺席：fewTicket 不落键（恒空键卫生律不变）。"""
    r = _pc_rows([
        _pc_flight(b2={"arrTime": "18:20", "arrDate": "2026-10-06",
                       "depTime": "14:00"}),
    ])
    assert "fewTicket" not in r, r


# ---- ②ctrip：cgrd 值域漂移勘误（2=公务舱） ----

def _ctrip_item(segs, policies):
    return {"mutilstn": segs, "policyinfo": policies}


def _ctrip_seg(dd, ad, flgno="CZ5640"):
    return {"dateinfo": {"ddate": dd, "adate": ad},
            "basinfo": {"flgno": flgno},
            "dportinfo": {"bsname": "", "aport": "URC"},
            "aportinfo": {"bsname": "T3", "aport": "SHA"}}


def _pol(price, cgrd, qty=5):
    return {"tprice": price, "quantity": qty,
            "classinfor": [{"cgrd": cgrd,
                            "classNoteList": [{"notetype": 2,
                                               "notecnt": "Y"}]}]}


_D1 = ("2026-10-15 08:30:00", "2026-10-15 13:50:00")


def _ctrip_one(item):
    rows = _CT._extract_ctrip_flights(json.dumps([item]))
    assert rows
    return rows[0]


def test_ctrip_cgrd2_cabin_business_class():
    """最低价政策 cgrd=2 → cabin=「公务舱」（nt=4 词面 69/69 实证，
    旧映射「头等舱」为代际漂移错挂）。"""
    r = _ctrip_one(_ctrip_item([_ctrip_seg(*_D1)],
                               [_pol(2750, 2)]))
    assert r.get("cabin") == "公务舱", r


def test_ctrip_cgrd2_biz_cabin_business_word():
    """高档参考价政策 cgrd=2 胜出 → bizCabin=「公务」（bizPrice
    配对不变，只改词面）。"""
    r = _ctrip_one(_ctrip_item(
        [_ctrip_seg(*_D1)],
        [_pol(560, 0), _pol(9900, 2), _pol(2730, 2)]))
    assert r["bizPrice"] == 2730
    assert r["bizCabin"] == "公务", r


def test_ctrip_cgrd1_business_word_unchanged():
    """cgrd=1=公务：既有语义维持（1 档现行域零出场但语义在案）。"""
    r = _ctrip_one(_ctrip_item(
        [_ctrip_seg(*_D1)],
        [_pol(560, 0), _pol(2730, 1)]))
    assert r["bizPrice"] == 2730
    assert r["bizCabin"] == "公务", r
    r2 = _ctrip_one(_ctrip_item([_ctrip_seg(*_D1)], [_pol(2730, 1)]))
    assert r2.get("cabin") == "公务舱", r2


def test_ctrip_cgrd0_economy_unchanged():
    """cgrd=0=经济舱：主路径行为不变。"""
    r = _ctrip_one(_ctrip_item([_ctrip_seg(*_D1)], [_pol(560, 0)]))
    assert r.get("cabin") == "经济舱", r
    assert "bizPrice" not in r, r


# ---- ③tongcheng：新最低价政策 discount/cabin 脏携带复位（r255 挂账①） ----

def test_tongcheng_lowest_policy_no_dirty_carry():
    """直飞两政策行 [5.4折公务舱@670, 超惠飞@500]：低价政策胜出后
    cabin 不得残留「公务舱」、discount 不得残留「5.4折」（超惠飞政策
    无舱位/折扣词面，如实缺省宁缺勿错——r255 Soldier 备案①预存
    脏携带，与 left_tickets/few_ticket/chaofei 复位同律）。"""
    fl = {"fn": "9C6117", "asn": "春秋航空",
          "dt": "2026-10-15 19:00", "at": "2026-10-15 23:40",
          "td": "4h40m", "afn": "空客A320(中)",
          "lps": [
              {"atp": 670, "brs": [{"al": 3}],
               "pts": [{"tt": 2, "td": "5.4折公务舱"}]},
              {"atp": 500, "brs": [{"al": 3}],
               "pts": [{"tt": 2, "td": "超惠飞"}],
               "fs": [{"ft": 7, "fcs": ["3", "6", "7"]}]},
          ]}
    text = json.dumps({"data": {"fl": [fl]}}, ensure_ascii=False)
    out = TongchengCrawler._extract_flights(text)
    assert out and out[0]["price"] == 500, out
    f = out[0]
    assert f.get("cabin", "") != "公务舱", f
    assert f.get("discount", "") != "5.4折", f


def test_tongcheng_lowest_policy_words_still_landed():
    """对照：低价政策自带舱位/折扣词面时照常落（复位只清残留，
    不伤正常配对——「6.8折经济舱@500」单独成行时两键照落）。"""
    fl = {"fn": "9C6117", "asn": "春秋航空",
          "dt": "2026-10-15 19:00", "at": "2026-10-15 23:40",
          "td": "4h40m", "afn": "空客A320(中)",
          "lps": [{"atp": 500, "brs": [{"al": 3}],
                   "pts": [{"tt": 2, "td": "6.8折经济舱"}]}]}
    text = json.dumps({"data": {"fl": [fl]}}, ensure_ascii=False)
    out = TongchengCrawler._extract_flights(text)
    f = out[0]
    assert f.get("cabin") == "经济舱", f
    assert f.get("discount") == "6.8折", f


def test_tongcheng_transfer_tctip_no_dirty_carry():
    """中转复位组补 tc_tip（Soldier P1）：[带 $tcTip「航司中转，
    享联程服务」@900, 无 $tcTip@500] 两政策行，低价胜出后
    airlineTransfer 不得残留上一政策词面（恒落键×条件赋值组合
    在新低支路缺复位=随价错配推送）。"""
    fp = {"dt": "2026-10-15 13:20", "at": "2026-10-15 21:30",
          "td": "8h10m", "sc": "兰州",
          "ss": [{"fn": "9C6117", "dt": "2026-10-15 13:20",
                  "at": "2026-10-15 16:05"},
                 {"fn": "MU5700", "dt": "2026-10-15 18:20",
                  "at": "2026-10-15 21:30"}],
          "lps": [
              {"atp": 900, "brs": [{"al": 3}],
               "pts": [{"tt": 2, "td": "6.8折经济舱"}],
               "$tcTip": {"c1": "中转专享", "c2": "航司中转，享联程服务"}},
              {"atp": 500, "brs": [{"al": 3}],
               "pts": [{"tt": 2, "td": "超惠飞"}]},
          ]}
    rows = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp]}}, ensure_ascii=False), "")
    assert rows and rows[0]["price"] == 500, rows
    assert rows[0].get("airlineTransfer", "") == "", rows[0]


def test_tongcheng_transfer_tctip_valued_still_landed():
    """对照：唯一政策自带 $tcTip.c2 时照常落（复位只清残留）。"""
    fp = {"dt": "2026-10-15 13:20", "at": "2026-10-15 21:30",
          "td": "8h10m", "sc": "兰州",
          "ss": [{"fn": "9C6117", "dt": "2026-10-15 13:20",
                  "at": "2026-10-15 16:05"},
                 {"fn": "MU5700", "dt": "2026-10-15 18:20",
                  "at": "2026-10-15 21:30"}],
          "lps": [{"atp": 900, "brs": [{"al": 3}],
                   "pts": [{"tt": 2, "td": "6.8折经济舱"}],
                   "$tcTip": {"c1": "中转专享",
                              "c2": "航司中转，享联程服务"}}]}
    rows = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp]}}, ensure_ascii=False), "")
    assert rows, rows
    assert rows[0].get("airlineTransfer") == "航司中转，享联程服务", rows[0]
