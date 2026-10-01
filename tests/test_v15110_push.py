# -*- coding: utf-8 -*-
"""本轮推送层（前轮审计备案转正修）：

「擦边0%」词面修正——0.xx% 的距线比例经 `:.0f` 四舍五入到 0%，
与档位词「擦边」字面自相矛盾（擦边=距线 0%？读者需回看差￥4 才能解，
push_history.jsonl:2407 实锤）。修法：不足半点（pct<0.5，含 0.5
本身——`.0f` 半点 banker 舍入到 0 的形态）出「擦边不足1%」，KPI 摘要
（kpi_tier_txt）与建议行（_suggest_line）共用 _near_txt 单源自动
收口；webui 端 diffTxt「差￥N（0%）」与擦边 span 同病 JS 侧同修。

判定不动：只是读感词面，档位判定（NEAR_RATIO 带宽）零变化。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15110_push.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import _near_txt, kpi_tier_txt  # noqa: E402


def test_near_txt_sub_half_percent():
    """0.21%（差￥4/线￥1900 实锤形态）：「擦边不足1%」不再出
    自我否定的「擦边0%」。"""
    assert _near_txt(0.0021) == "擦边不足1%"


def test_near_txt_half_percent_banker_boundary():
    """恰 0.5%：`.0f` 半点 banker 舍入到 0 的形态同样出「擦边不足1%」
    （边界含 0.5，防「擦边0%」从半点缝里回流）。"""
    assert _near_txt(0.005) == "擦边不足1%"


def test_near_txt_normal_percent_kept():
    """≥0.5% 且能舍到非零的形态维持原词面（词面漂移最小化）：
    0.6%→「擦边1%」、9%→「擦边9%」。"""
    assert _near_txt(0.006) == "擦边1%"
    assert _near_txt(0.09) == "擦边9%"


def test_kpi_tier_txt_sub1_summary():
    """KPI 摘要（日报 PNG summary 与 multi 总表同语言单源）：
    ￥1904 对线 ￥1900 出「直飞 ￥1904 擦边不足1%」。"""
    txt = kpi_tier_txt("直飞", 1904, 1900, False)
    assert "擦边不足1%" in txt
    assert "擦边0%" not in txt
    assert "<" not in txt


def test_webui_diff_pct_and_near_span_wordface():
    """webui JS 同病同修：diffTxt 百分比与擦边 span 均走 pctTxt
    不足1 分支（「差￥4（0%）」与「擦边0% · 未达标」同源收口）；
    边界 <=0.5 与 Python _near_txt 显式含边界精确同语言（两端
    半点向上同契约）；输入式与 near 判定同式 (p-t)*100/t（先除后
    减的浮点在 x.5 中点系统性向下偏，两端一档分叉）；词面不用
    尖括号（钉钉 L1 全禁族）。"""
    import webui
    assert "function pctTxt(np){return np<=0.5?'不足1':Math.round(np);}" \
        in webui.PAGE
    assert "pctTxt((p-t)*100/t)" in webui.PAGE
    assert "pctTxt((brief.price-th)*100/th)" in webui.PAGE
    assert "pctTxt((p/t-1)*100)" not in webui.PAGE
