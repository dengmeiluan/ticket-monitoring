# -*- coding: utf-8 -*-
"""r225 载荷卫生三案回归：qunar PC ptripNote 无值不落键（恒空键退役，
60,021 行 100% 空串的病根）/ ctrip bridgeRate 无值不落键（正则未命中
不再落空串）/ tongcheng atpt「余票紧张」→ fewTicket 补源（既有出口键
单渠道补源，fliggy fewTicket 值域白名单已含「紧张」，webui/report 零
协议改动；同结构槽 leftTickets 数字臂已在产证明载体可达）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v225_fields.py
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.qunar import QunarCrawler  # noqa: E402
from crawlers.ctrip import CtripCrawler  # noqa: E402
from crawlers.tongcheng import TongchengCrawler  # noqa: E402

_LOG = logging.getLogger("t225")


# ---- D1: qunar PC ptripNote 无值不落键 ----

def _pc_flight(**extra):
    f = {"minPrice": 1200, "code": "MF8266",
         "binfo": {"depTime": "12:05", "arrTime": "16:40",
                   "depDate": "2026-10-04", "arrDate": "2026-10-04",
                   "shortName": "厦航", "airCode": "MF8266"},
         "extparams": {}}
    f.update(extra)
    return f


def _pc_rows(f):
    return QunarCrawler._parse_pc_flights(json.dumps(
        {"data": {"flights": [f]}}), "2026-10-04")


def test_qunar_pc_ptripnote_present():
    """pTrip=true 且 Note 非空 → 键落值（特惠产品权益正文）。"""
    f = _pc_flight(binfo={"depTime": "12:05", "arrTime": "16:40",
                          "depDate": "2026-10-04", "arrDate": "2026-10-04",
                          "shortName": "厦航", "airCode": "MF8266",
                          "pTrip": True,
                          "pTripNote": "航变免费改、20Kg免费行李"})
    assert _pc_rows(f)[0]["ptripNote"] == "航变免费改、20Kg免费行李"


def test_qunar_pc_ptripnote_absent_no_key():
    """pTrip 非 true（全场绝大多数）→ 不落键。旧平铺落键使 60,021 行
    extra 恒挂空串 ptripNote（真值率 0）——无值不落键家族律
    （avgDelay/refundChange 同族）。"""
    rows = _pc_rows(_pc_flight())
    assert "ptripNote" not in rows[0], rows[0].get("ptripNote")


def test_qunar_pc_ptripnote_true_but_empty_no_key():
    """pTrip=true 但 Note 空串 → 同样不落键（空值不落）。"""
    f = _pc_flight(binfo={"depTime": "12:05", "arrTime": "16:40",
                          "depDate": "2026-10-04", "arrDate": "2026-10-04",
                          "shortName": "厦航", "airCode": "MF8266",
                          "pTrip": True, "pTripNote": ""})
    assert "ptripNote" not in _pc_rows(f)[0]


# ---- D2: ctrip bridgeRate 无值不落键 ----

class _CtripDirect:
    """最小直飞 fltitem（test_v1552_regress 同款骨架）。"""

    def _parse(self, item):
        obj = {"fltitem": [item]}
        return CtripCrawler._extract_ctrip_flights(
            CtripCrawler, json.dumps(obj, ensure_ascii=False))

    @staticmethod
    def _ci(**over):
        ci = {"cgrd": 0, "prate": 96, "meal": "", "extendinfos": []}
        ci.update(over)
        return ci

    def _direct(self, quantity=3, ci=None):
        return {"mutilstn": [{"basinfo": {"flgno": "MU5137"},
                              "dateinfo": {"ddate": "2026-10-05 08:00:00",
                                           "adate": "2026-10-05 11:30:00"},
                              "aportinfo": {"city": "上海"}}],
                "policyinfo": [{"tprice": 1200, "quantity": quantity,
                                "classinfor": [ci or self._ci()]}]}


def test_ctrip_bridge_rate_present_int():
    rows = _CtripDirect()._parse(_CtripDirect()._direct(ci=_CtripDirect._ci(
        extendinfos=[{"content": "连廊率93%"}])))
    assert rows[0]["bridgeRate"] == 93


def test_ctrip_bridge_rate_absent_no_key():
    """extendinfos 无连廊率词 → 不落键。旧空串落键 ~180 行/日存量
    （int 真值占 99.3%）——与 ptripNote 同批载荷卫生。"""
    rows = _CtripDirect()._parse(_CtripDirect()._direct())
    assert "bridgeRate" not in rows[0], rows[0].get("bridgeRate")


# ---- D3: tongcheng atpt「余票紧张」→ fewTicket 补源 ----

def _tc_flight(**extra):
    f = {"fn": "MF2370", "asn": "厦航", "dt": "2026-10-06 10:10",
         "at": "2026-10-06 14:55", "td": "4h45m", "amt": "中",
         "lps": [{"atp": 4350, "brs": {"al": 20},
                  "atpt": {"tt": 1, "td": "余1张"},
                  "pts": [{"tt": 2, "td": "全价经济舱"}]}]}
    f.update(extra)
    return f


def _tc_rows(f):
    obj = {"success": True, "data": {"ec": 0, "fl": [f]}}
    return TongchengCrawler._extract_flights(
        json.dumps(obj, ensure_ascii=False))


def test_tongcheng_fewticket_tense_direct():
    """atpt.td=「余票紧张」→ fewTicket=「紧张」（既有出口键，fliggy
    值域白名单已含该词，webui 明细次行 few 槽原样透传）；fresh dump
    1/288 行稀疏在场。"""
    f = _tc_flight()
    f["lps"][0]["atpt"] = {"tt": 1, "td": "余票紧张"}
    r = _tc_rows(f)[0]
    assert r["fewTicket"] == "紧张"
    assert "leftTickets" not in r


def test_tongcheng_fewticket_numeric_arm_unchanged():
    """数字臂照常：「余3张」→ leftTickets=3，不落 fewTicket（两臂
    互斥，数字形态语义更精确）。"""
    f = _tc_flight()
    f["lps"][0]["atpt"] = {"tt": 1, "td": "余3张"}
    r = _tc_rows(f)[0]
    assert r["leftTickets"] == 3
    assert "fewTicket" not in r


def test_tongcheng_fewticket_reset_on_lower_policy():
    """随最低价政策复位防脏携带：先高价新政带「余票紧张」、后低价政
    无 atpt → fewTicket 不落（与 leftTickets 复位同律）。"""
    f = _tc_flight(lps=[
        {"atp": 4600, "brs": {"al": 20},
         "atpt": {"tt": 1, "td": "余票紧张"}},
        {"atp": 4350, "brs": {"al": 20}}])
    r = _tc_rows(f)[0]
    assert r["price"] == 4350
    assert "fewTicket" not in r


def test_tongcheng_fewticket_tense_transfer():
    """中转路径同臂：book1 fps 形态 atpt.td=「余票紧张」→ fewTicket
    （两处解析点同收，注释「本轮 connection 未现样本，出现即采」）。"""
    fp = {"dt": "2026-10-06 08:00", "at": "2026-10-07 18:00",
          "sd": "2h15m", "td": "9h30m", "sc": "西安",
          "dasn": "天山", "aasn": "浦东", "dat": "", "aat": "T2",
          "ss": [{"fn": "CZ6981", "amn": "空客320(中)"},
                 {"fn": "MU5700", "amn": "波音787(大)"}],
          "lps": [{"atp": 1800, "brs": [{"al": 3}],
                   "atpt": {"tt": 1, "td": "余票紧张"},
                   "pts": [{"td": "5.2折经济舱"}]}]}
    rows = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp]}}, ensure_ascii=False))
    assert rows[0]["fewTicket"] == "紧张"
