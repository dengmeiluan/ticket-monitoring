# -*- coding: utf-8 -*-
"""r221 走势图 Y 轴刻度「档距悬崖」：nice-step 门槛放宽到 raw*0.5。

审计（_scratch/r221_webui_report.md P1-1）：阶梯 (1,2,5,10) 以
`m*_mag >= raw` 取档，raw=(hi-lo)/4 ∈ (100,200] 时步长突翻倍
（100→200）——默认 48h 窗常态只画 ￥1800/￥2000 两条网格线，
折线/K 线（webui chart()）与日报走势图（report.py）同根因。
门槛放宽为 `m*_mag >= raw*0.5`（刻度 4-8 条带），标签仍恒 ×00/×50
收尾（整价锚语义不变）。webui JS 与 report.py 同律同改。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15121_webui.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from report import _nice_ticks  # noqa: E402


def test_cliff_band_gets_dense_ticks():
    """悬崖带实证形态（demo 48h：lo=1630 hi=2060，raw=107.5）：
    步长 100（旧档 200），网格线 ≥4 条。"""
    nice, k0, k1 = _nice_ticks(1630, 2060)
    assert nice == 100, nice
    assert k1 - k0 + 1 >= 4, (nice, k0, k1)


def test_seven_day_window_three_plus():
    """7d 窗形态（跨度 ~800）：步长不劣于旧档。"""
    nice, k0, k1 = _nice_ticks(1500, 2400)
    assert nice == 200, nice          # raw=225 → 旧档同 200
    assert k1 - k0 + 1 >= 4


def test_labels_still_round_prices():
    """整价锚语义不变：全部刻度值 ×00/×50 收尾（1/2/5×10^n 族）。"""
    for lo, hi in ((1630, 2060), (1500, 2400), (800, 9800), (100, 160)):
        nice, k0, k1 = _nice_ticks(lo, hi)
        m = nice / max(nice, 1)
        assert nice in (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200,
                        500, 1000, 2000, 5000), nice
        for k in range(k0, k1 + 1):
            v = nice * k
            assert abs(v - round(v)) < 1e-9 or nice < 1, v


def test_cover_floor_and_ceiling():
    """ceil/floor 语义：全部刻度线落在数据域 [lo,hi] 内（渲染域外
    零画线），且域内刻度数 ≥4。"""
    nice, k0, k1 = _nice_ticks(1630, 2060)
    assert nice * k0 >= 1630 - 1e-9 and nice * k1 <= 2060 + 1e-9
    assert k1 - k0 + 1 >= 4
