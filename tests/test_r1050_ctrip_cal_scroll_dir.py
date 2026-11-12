# -*- coding: utf-8 -*-
"""携程日历滚动方向决策（纯函数回归保护）。

这条判断踩过两次真坑（2026-11-06）：
1. **只会前翻**：表单残留远期日期（实测 `2027年2月14日`，生产跑远期航线
   留下的）时，日历就开在 2027-02；目标 2026-11-16 早三个月 → 永远滚不到，
   报「日历滚动后仍找不到 2026-11-16」。
2. **前翻的滚动坐标写死 900×1600**（`(450,1400)→(450,600)`）：在 1260×2800
   上只滑到上半屏，日历主体没动 → **首屏之外的所有日期都取不到**。
"""
from crawlers.app_ctrip import cal_scroll_dir

#: 实测：表单残留 2027-02-14 时，日历首屏表头就这三行
_LEAKED = [(2027, 2, 684), (2027, 3, 1677), (2027, 4, 2670)]


def test_target_earlier_scrolls_back():
    assert cal_scroll_dir(_LEAKED, 2026, 11) == "back"


def test_target_later_scrolls_forward():
    assert cal_scroll_dir([(2026, 11, 684), (2026, 12, 1677)],
                          2027, 2) == "forward"


def test_target_visible_uses_forward_default():
    """目标已在可见范围时不会走到滚动分支，方向取默认值即可。"""
    assert cal_scroll_dir([(2026, 11, 684), (2026, 12, 1677)],
                          2026, 12) == "forward"


def test_empty_months_falls_back_to_forward():
    """表头都没识别出来时保持原行为，不要引入新的不确定性。"""
    assert cal_scroll_dir([], 2026, 11) == "forward"


def test_same_year_boundary_back():
    """跨年比较必须按 (年, 月) 元组，不能只比月份数字。"""
    assert cal_scroll_dir([(2027, 1, 684)], 2026, 12) == "back"
    assert cal_scroll_dir([(2026, 12, 684)], 2027, 1) == "forward"


def test_garbage_months_does_not_crash():
    assert cal_scroll_dir(None, 2026, 11) == "forward"
    assert cal_scroll_dir([("x", "y", 0)], 2026, 11) == "forward"
