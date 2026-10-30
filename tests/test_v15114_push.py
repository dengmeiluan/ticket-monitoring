# -*- coding: utf-8 -*-
"""推送层：擦边词面 x.5% 中点双端一档差收口（审校 P2-1）。

_near_txt 的展示取整与 webui pctTxt 同契约：>0.5 半点向上
（=JS Math.round 语义；banker 偶数舍入在 2.5/4.5/…中点比前端
低一档，同价两端词面分叉）；≤0.5 恒「擦边不足1%」（低边界
双端契约，恰 0.5 显式含边界）。near 带宽判定面不动，纯展示词面。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15114_push.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import _near_txt, kpi_tier_txt  # noqa: E402


def test_near_txt_half_midpoints_round_half_up():
    """x.5 中点半点向上：2.5→3、4.5→5（banker 偶数舍入分叉点）、
    1.5/3.5 形态钉（banker 恰为偶上不区分，防回归改型）。"""
    assert _near_txt(0.025) == "擦边3%"
    assert _near_txt(0.045) == "擦边5%"
    assert _near_txt(0.015) == "擦边2%"
    assert _near_txt(0.035) == "擦边4%"


def test_near_txt_low_boundary_kept():
    """低边界契约维持：≤0.5 恒「擦边不足1%」（恰 0.5 显式含边界，
    0.51 起出「擦边1%」）。"""
    assert _near_txt(0.005) == "擦边不足1%"
    assert _near_txt(0.0049) == "擦边不足1%"
    assert _near_txt(0.0051) == "擦边1%"
    assert _near_txt(0.006) == "擦边1%"


def test_kpi_tier_txt_consumes_half_up():
    """消费点 kpi_tier_txt 同语言：+2.5% 恰中点 →「擦边3%」。"""
    txt = kpi_tier_txt("直飞", 2050, 2000, False)
    assert "擦边3%" in txt
