# -*- coding: utf-8 -*-
"""ctrip 二段实际承运号 shareCarrier2——goal 轮字段调研唯一增量：

中转共享航班的「二段实际坐谁的飞机」无既有出口承载：shareCarrier
只读首段（basinfo[0] ishared 门），mutilstn[i>0] 段的 ishared/crerflgno
从未被读——调研实证旧代 3 例（MU8201→KN5977 形态），新代 0/96 稀疏。
采集层一行读法随手采（数据先行，消费随出勤——fliggy _via 备案同族
先例），多段共享按段序「/」连接。宁缺勿错：ishared 门+非空双门，
直飞行/未共享段/空串段均不落键。

样本形态取自调研冻结 dump 的 basinfo 结构。运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_ctrip_seg_share.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.ctrip import CtripCrawler  # noqa: E402

_LOG = logging.getLogger("t_ss2")
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


def test_seg_share_second_leg_lands():
    """中转二段 ishared=true + crerflgno → shareCarrier2 落键。"""
    r = _one(_seg(flgno="MU8201"),
             _seg(dd="2026-10-06 15:15:00", ad="2026-10-06 19:05:00",
                  flgno="HU7279", ishared=True, crerflgno="KN5977"))
    assert r["shareCarrier2"] == "KN5977", r


def test_seg_share_multi_legs_slash_join():
    """三段行两段共享 → 段序「/」连接。"""
    r = _one(_seg(flgno="MU8201"),
             _seg(dd="2026-10-06 15:15:00", ad="2026-10-06 19:05:00",
                  flgno="HU7279", ishared=True, crerflgno="KN5977"),
             _seg(dd="2026-10-06 21:10:00", ad="2026-10-06 23:40:00",
                  flgno="HU7280", ishared=True, crerflgno="KN5978"))
    assert r["shareCarrier2"] == "KN5977/KN5978", r


def test_seg_share_direct_flight_no_key():
    """直飞行（单段）无该键。"""
    r = _one(_seg(flgno="MU8201", ishared=True, crerflgno="MU5700"))
    assert "shareCarrier2" not in r, r


def test_seg_share_unshared_second_leg_no_key():
    """二段未共享（ishared 假门）不落键。"""
    r = _one(_seg(flgno="MU8201"),
             _seg(dd="2026-10-06 15:15:00", ad="2026-10-06 19:05:00",
                  flgno="HU7279", ishared=False, crerflgno="HU7279X"))
    assert "shareCarrier2" not in r, r
    r2 = _one(_seg(flgno="MU8201"),
              _seg(dd="2026-10-06 15:15:00", ad="2026-10-06 19:05:00",
                   flgno="HU7279"))
    assert "shareCarrier2" not in r2, r2


def test_seg_share_empty_crerflgno_no_key():
    """ishared=true 但 crerflgno 空串 → 宁缺勿错不落键。"""
    r = _one(_seg(flgno="MU8201"),
             _seg(dd="2026-10-06 15:15:00", ad="2026-10-06 19:05:00",
                  flgno="HU7279", ishared=True, crerflgno=""))
    assert "shareCarrier2" not in r, r


def test_seg_share_first_leg_still_share_carrier():
    """首段共享语义不受影响（shareCarrier 原样）。"""
    r = _one(_seg(flgno="3U5276", ishared=True, crerflgno="MU5700"),
             _seg(dd="2026-10-06 15:15:00", ad="2026-10-06 19:05:00",
                  flgno="MU5701"))
    assert r["shareCarrier"] == "MU5700", r
    assert "shareCarrier2" not in r, r
