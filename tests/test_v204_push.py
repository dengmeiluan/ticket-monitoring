# -*- coding: utf-8 -*-
"""日报缺图对账行地板档保日期（推送审校 P2-1）。

审计实证：09:08 实发 desp 同篇含 10/05 走势图
+「⚠️ 乌鲁木齐→上海 本期走势无图」（实为 10/06 缺图）——降级链末档
丢日期段后多日期航线无法定位缺图日期。日期是缺图辨识信息（跨天辨识
信息不可丢同律），末档改「保日期截城市名」（_section_title._trim
同款双侧逐字截，无省略号），地板档恒达标（守卫链尾地板档纪律）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v204_push.py -q
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import _dw
from report import _miss_chart_line


def test_short_name_full_form():
    """正常短名：全形态（城市+日期+完整说明），日期在行。"""
    line = _miss_chart_line("乌鲁木齐→上海", "2026-10-06")
    assert "乌鲁木齐→上海" in line
    assert "10/06" in line
    assert "本期无图" in line


def test_long_name_floor_keeps_date():
    """长自定义城市名（双侧超宽）：末档截城市名保日期——多日期航线
    可定位缺图期；行宽恒 ≤40 半角（手机 20 全角）。"""
    nm = "非常长的自定义城市名称甲→非常长的自定义城市名称乙"
    line = _miss_chart_line(nm, "2026-10-06")
    assert _dw(line) <= 40
    assert "10/06" in line          # 辨识信息恒在
    assert "…" not in line          # U+2026 禁令
    assert "本期无图" in line


def test_extreme_long_name_still_guarded():
    """极端超名（单侧 30+ 半角）：仍 ≤40 且保日期。"""
    nm = "超超超超超超超超超超超超超超超超超长→名"
    line = _miss_chart_line(nm, "2026-10-06")
    assert _dw(line) <= 40
    assert "10/06" in line


def test_never_worse_than_mid_tier():
    """短名全形态也 ≤40（守卫链首档即达标，无静默超宽残留）。"""
    for nm in ("乌→上", "乌鲁木齐→上海", "上海→乌鲁木齐"):
        assert _dw(_miss_chart_line(nm, "2026-10-06")) <= 40


def test_floor_keeps_both_sides():
    """地板档双侧均分截（_section_title 同律）：到达侧短名不被出发侧
    整侧吞掉，同日双向航线（长→短 / 短→长）缺图行方向可辨——整串
    逐字截曾把到达侧整侧吞掉（Soldier P2-1）。"""
    a = "非常长的自定义城市名称甲"
    l1 = _miss_chart_line(f"{a}→乙", "2026-10-06")
    l2 = _miss_chart_line(f"乙→{a}", "2026-10-06")
    assert _dw(l1) <= 40 and _dw(l2) <= 40
    assert "10/06" in l1 and "10/06" in l2
    assert "乙" in l1 and "乙" in l2          # 短侧恒在
    assert l1 != l2, "双向缺图行同串=方向不可辨"


def test_floor_both_long_within_budget():
    """双侧超长：均分截后 ≤40、日期恒在（同前缀极端对的方向边界
    与 _section_title 同律接受）。"""
    a = "非常长的自定义城市名称甲"
    b = "非常长的自定义城市名称乙"
    for nm in (f"{a}→{b}", f"{b}→{a}"):
        line = _miss_chart_line(nm, "2026-10-06")
        assert _dw(line) <= 40
        assert "10/06" in line
