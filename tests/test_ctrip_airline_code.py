# -*- coding: utf-8 -*-
"""ctrip airlineCode——五渠道协议对齐补口（r263 渠道调研立案）：

五渠道统一出口键 airlineCode（tuniu airlineIataCode / qunar
shortCarrier / fliggy code 派生 / tongcheng ac，webui 白名单/CSV
航司码列/搜索 hay 三消费面通用形态已就位），ctrip 是唯一缺口——
CSV 航司码列与搜索对携程行空。源取 mutilstn[].basinfo.aircode
渠道原生词面（调研 dump 268/268 段恒在，值域 MU/CZ/MF/CA/3U…，
与 flgno 前缀恒等但不走派生——渠道原生源优先，fliggy 无原生源才
派生），iata2 守卫单源拒脏形，无值不落键（本文件 r241 卫生律）。

样本形态取自调研冻结 dump。运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_ctrip_airline_code.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.ctrip import CtripCrawler  # noqa: E402

_LOG = logging.getLogger("t_ac")
_CT = CtripCrawler({}, _LOG)


def _seg(dd="2026-10-06 08:30:00", ad="2026-10-06 13:50:00",
         flgno="CZ5640", **bas):
    b = {"flgno": flgno}
    b.update(bas)
    return {"dateinfo": {"ddate": dd, "adate": ad},
            "basinfo": b,
            "dportinfo": {"bsname": "", "aport": "URC"},
            "aportinfo": {"bsname": "T3", "aport": "SHA"}}


def _one(*segs):
    rows = _CT._extract_ctrip_flights(json.dumps(
        [{"mutilstn": list(segs),
          "policyinfo": [{"tprice": 1200, "quantity": 5,
                          "drate": 5.2,
                          "classinfor": [{"cgrd": 0, "classNoteList":
                                          [{"notetype": 2, "notecnt": "Y"}]}],
                          }]}]))
    assert rows
    return rows[0]


def test_airline_code_from_basinfo():
    """basinfo.aircode 渠道原生词面 → airlineCode 落键。"""
    r = _one(_seg(flgno="MU8369", aircode="MU"))
    assert r["airlineCode"] == "MU", r


def test_airline_code_digit_head_passes_guard():
    """数字头二字码（3U 川航/9C 春秋）照过 iata2。"""
    r = _one(_seg(flgno="3U5276", aircode="3U"))
    assert r["airlineCode"] == "3U", r


def test_airline_code_transfer_first_leg():
    """中转行随首段承运航司（与 qunar/tuniu 中转首段语义对齐）。"""
    r = _one(_seg(flgno="BK2776", aircode="BK"),
             _seg(dd="2026-10-06 15:15:00", ad="2026-10-06 19:05:00",
                  flgno="FM9402", aircode="FM"))
    assert r["airlineCode"] == "BK", r


def test_airline_code_guard_rejects_bad_shape():
    """iata2 守卫脏形（三位/小写/单字符）不落键（无值不落律）。"""
    for bad in ("MU8", "mu", "M"):
        r = _one(_seg(flgno="MU8369", aircode=bad))
        assert "airlineCode" not in r, (bad, r)


def test_airline_code_absent_no_key():
    """basinfo 无 aircode → 键不落。"""
    r = _one(_seg(flgno="MU8369"))
    assert "airlineCode" not in r, r
