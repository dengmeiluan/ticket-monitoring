# -*- coding: utf-8 -*-
"""WebUI 精细化（r230 审计落地）：K线图例色票无所指收口 / KPI 主数字
亮色对比度档位统一 / 选中态 hover 死区补反馈。

背景（_scratch/r230_wd_webui.md，P0=0/P1=0/P2=3）：
- P2-1 K线模式静态图例「直飞■蓝/中转■橙」无所指——蜡烛只有红/绿，
  系列靠左右簇位置区分且全图无一字说明（r230_wd_chart_kline_*.png）；
  修法=图例两枚系列色票 K线模式隐藏 + ringNote K线句补「左簇=直飞 ·
  右簇=中转」簇位语义（达标虚线/线内区间双模式保留不动）；
- P2-2 亮色 KPI 主数字三档离散：蓝 5.63 / 达标绿 4.28 / 橙 3.78——
  同卡 12px 小字已收 --ok-txt 族，主角反停裸色令牌（橙为全站正文级
  最低）；修法=.kpi.hit .num→--ok-txt、.kpi.t .num→新文字级橙令牌
  --orange-txt（#a45508 对白卡 5.41；暗色成对换谱=暗 --orange 本值
  #e6922e，暗色三档原全 ≥7 不动）；.kpi.d .num 蓝 5.63 已过不动；
- P2-3 选中态 hover 死区：.on 家族（tabs/nav/chip/rngchip）悬停零
  反馈，与 .pill:hover brightness(1.07) 先例不一致；选中 chip 恰是
  「再点=取消」高频目标。置尾追加族规则（层叠序：同特异性后者胜，
  LESSONS 二十一§1——源码钉锁级联位次，computed 行为钉在 uitest）。
"""
import inspect
import re

import webui

_SRC = None


def src():
    global _SRC
    if _SRC is None:
        _SRC = inspect.getsource(webui)
    return _SRC


# ---------------- P2-1 K线图例色票 ----------------

def test_p21_legend_series_spans_have_ids():
    s = src()
    assert 'id="lgDirect"' in s, "直飞系列色票缺锚点 id"
    assert 'id="lgTrans"' in s, "中转系列色票缺锚点 id"


def test_p21_chart_toggles_series_swatch_by_mode():
    body = re.search(r"function chart\(\)", src())
    assert body, "chart() 不在源码"
    seg = src()[body.start():body.start() + 9000]
    assert "lgDirect" in seg and "lgTrans" in seg, \
        "chart() 未随模式切换系列色票显隐"
    assert seg.count("'none'") >= 2 or seg.count('"none"') >= 2, \
        "K线模式未隐藏系列色票"


def test_p21_ringnote_kline_cluster_semantics():
    body = re.search(r"function chart\(\)", src())
    seg = src()[body.start():body.start() + 9000]
    assert "左簇=直飞" in seg and "右簇=中转" in seg, \
        "K线 ringNote 缺簇位语义（系列靠左右簇区分却无一字说明）"


# ---------------- P2-2 KPI 主数字文字级令牌 ----------------

def test_p22_kpi_num_text_tokens():
    s = src()
    assert ".kpi.t .num{color:var(--orange-txt)}" in s, \
        "橙档主数字未换文字级令牌（3.78 全站正文级最低）"
    assert ".kpi.hit .num{color:var(--ok-txt)}" in s, \
        "达标主数字未收 --ok-txt 族（12px 小字已收，主角反停裸令牌）"
    assert "--orange-txt:#a45508" in s, "亮色文字级橙令牌缺失（5.41:1）"
    assert "--orange-txt:#e6922e" in s, "暗色成对换谱缺失（=暗 --orange 本值）"


# ---------------- P2-3 选中态 hover 反馈 ----------------

def test_p23_on_hover_family_rule_and_cascade_position():
    s = src()
    rule = (".tabs span.on:hover,nav span.on:hover,.chip.on:hover,\n"
            " .rngchip.on:hover,.cnav.on:hover{filter:brightness(1.07)}")
    pos = s.find(rule)
    assert pos >= 0, "选中态 hover 族规则缺失或 rngchip/cnav 成员脱落"
    # 级联位次：族规则必须声明在全部同族 .on 基础规则之后（同特异性
    # 后者胜；filter 无既有声明，置尾即胜）
    for base in (".tabs span.on{", "nav span.on{", ".chip.on{",
                 ".rngchip.on{", ".cnav.on{"):
        b = s.find(base)
        assert b >= 0 and b < pos, f"族规则未置尾于 {base} 之后"
