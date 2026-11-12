# -*- coding: utf-8 -*-
"""推送层单源收口钉：图例兜底识别挂 TIER_EMOJI 投影。

_is_legend_line 的档位 emoji 集合与 _EMOJI_TIER_WORDS 同文件两种
形态（字面量 vs 投影）：档位 emoji 改版时转写表跟表走、图例识别
若锚死字面量即静默失配（强提醒通道漏剥图例行）。单源律钉：
monkeypatch 投影后图例识别必须跟随。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v229_push.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import notifier  # noqa: E402


def test_legend_line_default_projection():
    """现行档位 emoji 下图例行识别为图例（基线行为不变）。"""
    legend = "> ⏱22:47 🎯真达标 🟩破线 🟨擦边 超线"
    assert notifier._is_legend_line(legend)


def test_legend_line_follows_tier_emoji_projection(monkeypatch):
    """档位 emoji 投影改版（🎯🟩🟨→✅🟧🟡）：图例识别跟随投影，
    不锚死字面量（单源律，与 _EMOJI_TIER_WORDS 同源）。"""
    legend = "> ⏱22:47 ✅真达标 🟧破线 🟡擦边 超线"
    monkeypatch.setattr(
        notifier, "TIER_EMOJI",
        {**notifier.TIER_EMOJI, "qual": "✅", "mkt": "🟧", "near": "🟡"})
    assert notifier._is_legend_line(legend), (
        "投影改版后图例识别应跟随 TIER_EMOJI，字面量锚死即漏剥")


def test_legend_line_projection_counts_not_single_dot(monkeypatch):
    """正文行至多 1 个档位点的语义不变：投影改版后单点行不误判
    图例（KPI 行点前置 1 个的豁免面跟投影走）。"""
    kpi = "📍 10-06　✅ 直飞 ￥1760 破线"
    monkeypatch.setattr(
        notifier, "TIER_EMOJI",
        {**notifier.TIER_EMOJI, "qual": "✅", "mkt": "🟧", "near": "🟡"})
    assert not notifier._is_legend_line(kpi)
