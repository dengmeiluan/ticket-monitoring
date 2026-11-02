# -*- coding: utf-8 -*-
"""r763：途牛 PC 行的到达时刻带「+0 / +1」后缀，旧正则把整行判废。

离线用已保存的真实页面快照跑生产 JS（`PC_ITEMS_JS`）再喂
`_parse_pc_items`，5 份快照全部 0 条产出：

    fn='CZ1925 325(中)' price='￥1080\\n经济舱' dep='10:15' arr='12:20+0'

`_parse_pc_items` 要求 `^\\d{2}:\\d{2}$` 同时命中到达时刻，而真实值带
跨天后缀 `+0`（同日）/`+1`（次日）。于是每一条都被 `continue` 掉，
PC 通路一次都没出过数。这也解释了路径账本里 30 条记录**全是 H5/API**、
没有一条 PC。

判据：
  * 带 `+0` / `+1` 的到达时刻要能解析，且 `+1` 要落成跨天标记；
  * 真正的坏值（空、乱码、只有 `+1`）仍要被拒——不能为了能解析就放宽成
    「只要含数字就收」。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from crawlers.tuniu import TuniuCrawler


def _item(**kw):
    base = {"airline": "东航", "fn": "MU5100 327", "dep": "07:00",
            "depAir": "首都机场T2", "arr": "08:55", "arrAir": "浦东机场T1",
            "dur": "1h55m", "rate": "100%", "price": "￥552\n经济舱",
            "cross": "08:55", "rowText": "东航 MU5100"}
    base.update(kw)
    return base


def test_arrival_with_same_day_suffix_parses():
    """真实快照里的 `arr='12:20+0'` 必须能解析。"""
    rows = TuniuCrawler._parse_pc_items(
        [_item(arr="12:20+0", price="￥1080\n经济舱")], "2026-10-24")
    assert len(rows) == 1, "带 +0 的到达时刻仍被判废——PC 通路永远出不了数"
    assert rows[0]["arrTime"] == "12:20"
    assert rows[0]["price"] == 1080.0


def test_arrival_with_next_day_suffix_marks_cross_day():
    """`+1` 是次日到达，要落成跨天标记而不是被丢掉。"""
    rows = TuniuCrawler._parse_pc_items(
        [_item(arr="00:35+1")], "2026-10-24")
    assert len(rows) == 1
    assert rows[0]["arrTime"] == "00:35"
    assert rows[0].get("crossDayDesc") == "+1天"


@pytest.mark.parametrize("bad", ["", "abc", "+1", "12", "1:5", "25:00"])
def test_broken_arrival_is_still_rejected(bad):
    """负控：放宽后缀不能放宽到「含数字就收」。"""
    assert TuniuCrawler._parse_pc_items(
        [_item(arr=bad)], "2026-10-24") == []


def test_departure_time_keeps_strict_validation():
    """去程时刻没有跨天后缀语义，坏值必须拒。"""
    assert TuniuCrawler._parse_pc_items(
        [_item(dep="7:00")], "2026-10-24") == []
    assert TuniuCrawler._parse_pc_items(
        [_item(dep="")], "2026-10-24") == []


def test_parse_real_snapshot_shape_end_to_end():
    """用真实快照的原始字段组合（含 +0 与多行价签）跑一遍。"""
    items = [
        _item(fn="CZ1925 325(中)", dep="10:15", arr="12:20+0",
              price="￥1080\n经济舱"),
        _item(fn="SC5161 321", dep="15:30", arr="18:55+0",
              price="￥1750\n经济舱"),
    ]
    rows = TuniuCrawler._parse_pc_items(items, "2026-10-26")
    assert [r["code"] for r in rows] == ["CZ1925", "SC5161"]
    assert [r["price"] for r in rows] == [1080.0, 1750.0]
