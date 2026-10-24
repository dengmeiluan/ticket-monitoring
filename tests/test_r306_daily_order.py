# -*- coding: utf-8 -*-
"""r306 日报小节行程时间序（推送审校互证唯一落地案）：

build_and_push 小节循环曾按 (from,to,date) 纯字典序排——返程城市对
（HAK→SHA）整体排到去程（SHA→HAK）前（H<S），与主推送
_digest_payload 已修的「行程时间序：去程日期在前返程在后」律相反
（用户实报「应该优先展示去程」主推送侧已改，日报侧遗留）。

钉面两层：
- 行为钉：_daily_route_key 纯函数键语义（键首=航线配置最早日期，
  城市对字典序只作同日次级；无配置匹配退自身 date）；
- 接线钉：小节循环确实以该键排序（字面钉锁接线形态，防未来
  循环改动静默回退字典序）。"""
import re
from pathlib import Path

import pytest

import report


RC = [
    {"from": "SHA", "to": "HAK", "dates": ["2027-01-29", "2027-01-30"]},
    {"from": "HAK", "to": "SHA", "dates": ["2027-02-13"]},
]


def test_return_trip_not_before_outbound():
    """返程小节（HAK→SHA）不得排到去程（SHA→HAK）前——旧字典序
    （H<S）下返程恒打头即本钉的复现形态。"""
    keys = [("HAK", "SHA", "2027-02-13"),
            ("SHA", "HAK", "2027-01-29"),
            ("SHA", "HAK", "2027-01-30")]
    ordered = sorted(keys, key=report._daily_route_key(RC))
    assert ordered == [("SHA", "HAK", "2027-01-29"),
                       ("SHA", "HAK", "2027-01-30"),
                       ("HAK", "SHA", "2027-02-13")]


def test_same_pair_dates_ascending():
    """同城市对多日期按日期升序（min 键同值时 date 末键兜序）。"""
    keys = [("SHA", "HAK", "2027-01-30"), ("SHA", "HAK", "2027-01-29")]
    ordered = sorted(keys, key=report._daily_route_key(RC))
    assert ordered == [("SHA", "HAK", "2027-01-29"),
                       ("SHA", "HAK", "2027-01-30")]


def test_unmatched_pair_falls_back_to_own_date():
    """无配置匹配的键（防御病理形态）退自身 date 作键首。"""
    ordered = sorted([("PEK", "SHA", "2027-03-01"),
                      ("SHA", "PEK", "2027-02-01")],
                     key=report._daily_route_key(RC))
    assert ordered == [("SHA", "PEK", "2027-02-01"),
                       ("PEK", "SHA", "2027-03-01")]


def test_section_loop_wired_to_order_key():
    """接线钉：build_and_push 小节循环必须带排序键（防回退纯字典序）。"""
    src = Path(report.__file__).read_text(encoding="utf-8")
    assert re.search(
        r"sorted\(list\(charts\) \+ _trendless,\s*key=", src), \
        "日报小节循环未挧行程时间序排序键"


@pytest.mark.parametrize("bad", [
    [("HAK", "SHA", "2027-02-13"), ("SHA", "HAK", "2027-01-29")],
])
def test_legacy_lexicographic_would_fail(bad):
    """变异自检：旧字典序形态喂给新键必须产生不同序（钉有咬合力）。"""
    assert sorted(bad, key=report._daily_route_key(RC)) != sorted(bad)
