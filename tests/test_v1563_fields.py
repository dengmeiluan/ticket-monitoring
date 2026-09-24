"""字段回归：qunar PC binfo2.depTime→lay2dep + binfo2.depTerminal→
transDepTerminal（渠道字段第十四批，均既有键补源零协议改动）。

真实 dump 依据（09-21 15:55 PC 两日组，_scratch/research_v163_a.md）：
- lay2dep：中转行 49/49 真独立（≠b1.depTime=整体起飞），两日回放
  23/23+26/26 全落，形态「06:50」；
- transDepTerminal：47/49 非空、8/49 真跨楼（咸阳 T3→T5/T5→T2），
  同楼 41/49 无增量不落（H5 secondDepInfo 守卫同律）。
"""

import json

from crawlers.qunar import QunarCrawler

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
    """真独立二段起飞（≠整体起飞）落 HH:MM；直飞行空串。"""
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
    assert d["lay2dep"] == "" and d["transDepTerminal"] == ""


def test_pc_lay2dep_copy_guard():
    """H5 防复制态守卫同律：b2.depTime==整体起飞 → 不落
    （防渠道复制态回潮吐假「二段」时刻）。"""
    out = QunarCrawler._parse_pc_flights(
        _pc(b2={"depTime": "19:25"}), _PC_DATE)
    assert out[0]["lay2dep"] == ""
    # 缺键同样空串口径
    out = QunarCrawler._parse_pc_flights(
        _pc(b2={"depTime": ""}), _PC_DATE)
    assert out[0]["lay2dep"] == ""


def test_pc_trans_dep_terminal_cross_building():
    """真跨楼（T3 到 T5 出）落「咸阳T5」：depAirport 剥「机场」后缀
    +楼号，与 trans_term「咸阳T3」同型配对。"""
    out = QunarCrawler._parse_pc_flights(_pc(), _PC_DATE)
    t = out[0]
    assert t["transTerminal"] == "咸阳T3"
    assert t["transDepTerminal"] == "咸阳T5"


def test_pc_trans_dep_terminal_same_building_dropped():
    """H5 同律「与到达楼同楼无增量不落」；空串/缺键同落空。"""
    same = _pc(b2={"depTerminal": "T3"})
    assert QunarCrawler._parse_pc_flights(same, _PC_DATE)[0][
        "transDepTerminal"] == ""
    empty = _pc(b2={"depTerminal": ""})
    assert QunarCrawler._parse_pc_flights(empty, _PC_DATE)[0][
        "transDepTerminal"] == ""
