"""渠道字段十六批（载荷卫生收尾）：中转航站楼对 transTerminal/
transDepTerminal 无值不落键——qunar H5/PC、ctrip、tongcheng 四写点
条件展开（fliggy 既有 if 门零改动）。

依据（r230 观测 _scratch/r230_wc_data.md）：DB 存量 transTerminal/
transDepTerminal 空串残留 1,491 行（三渠道写点空串照落）。r229
depTerminal/arrTerminal 同族尾巴：str 槽位空串=无值（LESSONS 廿九§4
门型判例的字符串侧），无值不落；消费端（webui 白名单 strip + JS
falsy 渲染门 + CSV 空列）对缺键天然免疫，零消费端改动。有值照落
不变（正例钉 test_v1552/test_v1554/test_v1556 维持）。
"""

import json

from crawlers.ctrip import CtripCrawler
from crawlers.qunar import QunarCrawler
from crawlers.tongcheng import TongchengCrawler


# ---- qunar H5 ----

def _h5_row(trans_info):
    b1 = {"depTime": "08:00", "arrTime": "11:00",
          "depDate": "2026-10-06", "arrDate": "2026-10-06"}
    if trans_info is not None:
        b1["transInfo"] = trans_info
    f = {"minPrice": 800, "code": "MU8369", "transCity": "西安",
         "binfo1": b1,
         "binfo2": {"depTime": "13:30", "arrTime": "17:20",
                    "depDate": "2026-10-06", "arrDate": "2026-10-06"}}
    rows = QunarCrawler._extract_flights_obj([f])
    return rows[0] if rows else {}


def test_qunar_h5_trans_terminal_absent_without_value():
    """firstArrInfo 缺席/terminal 空=无值不落键（旧行为空串照落）。"""
    assert "transTerminal" not in _h5_row({"transTime": "5时50分"})
    assert "transTerminal" not in _h5_row(None)


def test_qunar_h5_trans_dep_terminal_absent_same_building():
    """secondDepInfo 与 firstArrInfo 同楼=无换乘增量不落（宁缺勿错）。"""
    ti = {"transTime": "5h45m",
          "firstArrInfo": {"airport": "正定", "terminal": "T2"},
          "secondDepInfo": {"airport": "正定", "terminal": "T2",
                            "time": "06:05"}}
    assert "transDepTerminal" not in _h5_row(ti)


# ---- qunar PC ----

_PC_DATE = "2026-10-06"


def _pc(**kw):
    b2 = {"depTime": "06:50", "arrTime": "09:10",
          "arrDate": "2026-10-07",
          "depTerminal": "T5", "depAirport": "咸阳机场"}
    b2.update(kw.pop("b2", {}))
    flight = {"minPrice": 2000, "code": "GS7495/9C6178",
              "transCity": "西安",
              "binfo1": {"depTime": "19:25", "arrTime": "21:40",
                         "date": _PC_DATE, "arrTerminal": "T3",
                         "arrAirport": "咸阳机场"},
              "binfo2": b2}
    flight.update(kw)
    return json.dumps({"data": {"flights": [flight]}}, ensure_ascii=False)


def test_qunar_pc_trans_terminals_absent_without_value():
    """二段楼空串/同楼=不落；直飞行双键全不落。"""
    out = QunarCrawler._parse_pc_flights(_pc(b2={"depTerminal": ""}),
                                         _PC_DATE)
    assert "transDepTerminal" not in out[0]
    same = QunarCrawler._parse_pc_flights(_pc(b2={"depTerminal": "T3"}),
                                          _PC_DATE)
    assert "transDepTerminal" not in same[0]
    direct = json.dumps({"data": {"flights": [{
        "minPrice": 2000, "code": "9C8866",
        "binfo": {"depTime": "08:00", "arrTime": "11:30",
                  "date": _PC_DATE, "arrDate": _PC_DATE}}]}})
    d = QunarCrawler._parse_pc_flights(direct, _PC_DATE)[0]
    assert "transTerminal" not in d and "transDepTerminal" not in d


# ---- ctrip ----

def _ctrip_ci(**over):
    ci = {"cgrd": 0, "prate": 96, "meal": "", "extendinfos": []}
    ci.update(over)
    return ci


def _ctrip_direct():
    return {"mutilstn": [{"basinfo": {"flgno": "MU5137"},
                          "dateinfo": {"ddate": "2026-10-06 08:00:00",
                                       "adate": "2026-10-06 11:30:00"},
                          "aportinfo": {"city": "上海"}}],
            "policyinfo": [{"tprice": 1200, "quantity": 3,
                            "classinfor": [_ctrip_ci()]}]}


def test_ctrip_trans_terminal_absent_on_direct():
    """直飞行不落中转航站楼键（旧行为空串照落）。"""
    obj = {"fltitem": [_ctrip_direct()]}
    rows = CtripCrawler._extract_ctrip_flights(
        CtripCrawler, json.dumps(obj, ensure_ascii=False))
    assert rows and "transTerminal" not in rows[0]


# ---- tongcheng ----

def _tc_fp():
    return {"dt": "2026-10-06 13:20", "at": "2026-10-06 21:30",
            "sd": "2h45m", "td": "8h10m", "sc": "张掖",
            "ss": [{"fn": "CZ6981", "dt": "2026-10-06 13:20",
                    "at": "2026-10-06 16:05", "aat": "T3", "dac": "URC",
                    "aac": "YZY"},
                   {"fn": "MU5700", "dt": "2026-10-06 18:20",
                    "at": "2026-10-06 21:30", "dat": "T5", "dac": "YZY",
                    "aac": "PVG"}],
            "lps": [{"atp": 1800, "brs": [{"al": 3}]}]}


def _tc_rows(fp):
    rows = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp]}}))
    assert rows
    return rows[0]


def test_tongcheng_trans_terminals_absent_without_value():
    """段级 aat/dat 缺失=无值不落键（有值照落不变）。"""
    fp = _tc_fp()
    del fp["ss"][0]["aat"]
    assert "transTerminal" not in _tc_rows(fp)
    fp2 = _tc_fp()
    del fp2["ss"][1]["dat"]
    assert "transDepTerminal" not in _tc_rows(fp2)
