# -*- coding: utf-8 -*-
"""r1063 T210-T212：智行整窗收割的**顺序契约**。

真机踩过：整窗收割按"窗口顺序"发，结果 `out[0]` 变成窗口首日（430 元），
而调用方/页面约定**第一行就是"我们要的那天"**（测试
`test_long_calendar_dialog_preferred_over_strip` 当场变红，断言 256 元）。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return io.open(os.path.join(ROOT, "crawlers", "app_zhixing.py"),
                   encoding="utf-8").read()


def test_subscribed_dates_come_first():
    s = _src()
    i = s.index("_out_wanted")
    seg = s[i:i + 1600]
    assert "_out_wanted.append(_fp)" in seg, "订阅日期必须单独收集"
    assert "_out_wanted + _out_extra" in seg, (
        "合并顺序必须是「订阅日 + 其余」，否则 out[0] 不再是订阅那天")


def test_harvest_is_capped():
    s = _src()
    assert "app_calendar_harvest_cap" in s
    i = s.index("app_calendar_harvest_cap")
    assert "_out_extra[:max(0, _cap - len(_out_wanted))]" in s[i:i + 1200] or \
        "_cap" in s[i:i + 1200], "必须有上限，防一次写爆几十天"


def test_priceless_cells_not_counted():
    s = _src()
    i = s.index("price is None")
    assert "无价格子" in s[i:i + 120], "无价格子不该算进'收了 N 天'"
