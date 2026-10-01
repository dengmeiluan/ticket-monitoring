# -*- coding: utf-8 -*-
"""推送层对齐四案（_scratch/r263_push_audit.md 立案，TDD 先行）：

A1 擦边带百分比双路径舍入分叉（P2-1）：文本 KPI 行1 尾注走
   `:.0f` banker 舍入（1640/1600→「·2%」），图内 summary/建议行走
   _near_txt 的 floor(x+0.5)（→「擦边3%」）——同条推送两数互斥
   （判例「KPI 与建议行两数互斥」的百分比现行犯）。抽
   _kpi_pct_suffix/_pct_int 单源：擦边带四语言同源挂「擦边N%」，
   取整统一 floor(x+0.5)=前端 Math.round 契约。
A2 ntfy 截断悬垂冒号（P3-1）：截点回退到 URL 起点后，「文字: 」
   残留在截尾读作未完句。
A3 ntfy/aliyun 行首空格残留（P3-2）：#### 剥除层新暴露的行首空格
   无人再剥（跨层职责缝隙），锁屏预览显眼。
A4 日报文本 KPI 兜底补百分比尾注（P3-4）：_kpi 降级链与主链
   _pct_fallback_forms 同源（能力对称三十§3），docstring「依次丢
   注→百分比→裸价」与实现对齐。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_push_align.py
"""
import logging as _lg
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


# ---------- A1: 百分比取整/词面单源 ----------

def test_pct_suffix_near_band_uses_near_txt():
    """擦边带（diff>0 且 ≤NEAR_RATIO）尾注挂「擦边N%」四语言同源：
    1640/1600=2.5% → _near_txt floor(2.5+0.5)=3（banker 直格式化曾
    出「·2%」与图内互斥）。"""
    from core.alerter import _kpi_pct_suffix
    assert _kpi_pct_suffix(1640, 1600) == "擦边3%"


def test_pct_suffix_qual_keeps_abs_magnitude():
    """达标行（diff<0）幅度保号（abs）：1200/1600 → 「25%」。"""
    from core.alerter import _kpi_pct_suffix
    assert _kpi_pct_suffix(1200, 1600) == "25%"


def test_pct_int_half_point_rounds_up():
    """取整契约 floor(x+0.5)=前端 Math.round：12.5% → 13（banker
    round 偶数舍入曾出 12，与图内低一档）。"""
    from core.alerter import _pct_int
    assert _pct_int(12.5) == 13
    assert _pct_int(2.4999999) == 2
    assert _pct_int(11.5) == 12


def test_pct_suffix_near_boundary():
    """擦边带边界：恰 10%（NEAR_RATIO）内挂词面、超出走裸百分比。"""
    from core.alerter import _kpi_pct_suffix, NEAR_RATIO
    assert NEAR_RATIO == 0.10
    assert _kpi_pct_suffix(1760, 1600) == "擦边10%"   # 10.0% 恰边界
    assert _kpi_pct_suffix(1776, 1600) == "11%"       # 11% 真超线


def test_pct_suffix_sub_one_pct_rules():
    """<1% 分档：达标带幅度省略（「低￥9（0%）」矛盾读感守卫不变）；
    擦边带由 _near_txt 接管出「擦边不足1%」（档位词不是裸 0%）。"""
    from core.alerter import _kpi_pct_suffix
    assert _kpi_pct_suffix(1594, 1600) == ""          # 低 0.375% 省略
    assert _kpi_pct_suffix(1604, 1600) == "擦边不足1%"  # 超 0.25% 擦边


def test_pct_suffix_no_th():
    from core.alerter import _kpi_pct_suffix
    assert _kpi_pct_suffix(1640, 0) == ""
    assert _kpi_pct_suffix(1640, None) == ""


def test_kpi_pct_suffix_callers_wired():
    """三处调用点接线源码钉（调用点内联是温床）：multi _kpi_block +
    单航线 direct/transfer 全部走 helper。"""
    src = open("core/alerter.py", encoding="utf-8").read()
    assert src.count("_kpi_pct_suffix(") >= 4, (
        "KPI 幅度尾注存在旁路路径：三处调用点必须全部走 _kpi_pct_suffix")


# ---------- A2/A3: ntfy 截断与行首空格 ----------

def test_ntfy_trunc_no_dangling_colon(monkeypatch):
    """A2：截点回退到链接起点后，悬垂「文字: 」剥除——截尾读作
    完整词而非未完句。"""
    import core.notifier as N
    calls = []
    monkeypatch.setattr(N.httpx, "post",
                        lambda u, **kw: (calls.append(kw),
                                         mock.Mock(status_code=200))[1])
    nt = N.NtfyNotifier(topic="t", logger=_lg.getLogger("t"))
    # 截点（600）落入 URL 中段 → 回退到 URL 起点 → 尾部悬垂「￥1680: 」
    body = "直飞 ￥1680: https://flight.example.com/very/long/url/" + "x" * 600
    assert nt.send("标题", body) is True
    sent = calls[-1]["json"]["message"]
    assert "已截断" in sent
    head = sent.split("（已截断")[0]
    assert not head.rstrip().endswith(("：", ":", " ", "\u3000")), (
        "截尾悬垂冒号在场（链接「文字: url」原子对被截点拆开）：%r"
        % head[-24:])


def test_ntfy_no_leading_space_after_marker_strip(monkeypatch):
    """A3：#### 剥除后新暴露的行首空格二次剥——锁屏预览无前导空格。"""
    import core.notifier as N
    calls = []
    monkeypatch.setattr(N.httpx, "post",
                        lambda u, **kw: (calls.append(kw),
                                         mock.Mock(status_code=200))[1])
    nt = N.NtfyNotifier(topic="t", logger=_lg.getLogger("t"))
    assert nt.send("标题", "第一行\n#### 上海→乌鲁木齐 10/08-10/09") is True
    sent = calls[-1]["json"]["message"]
    for ln in sent.split("\n"):
        assert ln == ln.lstrip(" "), repr(ln)


def test_sanitize_strips_fullwidth_gt():
    """A4 前置：sanitize_desp 尖括号家族全角 ＞ 一致性收口
    （＜ 已剥，＞ 剥后恒为孤字符无害——家族两向对称）。"""
    from core.alerter import sanitize_desp
    assert sanitize_desp("a＞b") == "ab"
    assert sanitize_desp("a＜b") == "ab"


# ---------- A4: 日报 KPI 兜底百分比尾注（源码钉） ----------

def test_report_kpi_fallback_pct_wired():
    """report._kpi 降级链走 _pct_fallback_forms + _kpi_pct_suffix
    （闭包内函数行为钉不可直调，源码钉锁接线；docstring「依次丢
    注→百分比→裸价」随实现成立）。"""
    src = open("report.py", encoding="utf-8").read()
    assert "_pct_fallback_forms(" in src, "report 未接主链降级单源"
    assert src.count("_kpi_pct_suffix(") >= 1, (
        "日报 KPI 兜底未挂百分比尾注单源")


# ---------- M1/m1/m2（Soldier 审查修复） ----------

def _kpi_line_replay(label, price, th, qual_hit):
    """report._kpi 降级链公式复刻（闭包不可直调；与源码钉配合：
    钉锁实现、本复刻锁链公式的行宽数学性质）。"""
    from core.alerter import (gap_txt, tier_dot, TIER_EMOJI, _MKT_NOTE_PAREN,
                              _fit_line, _pct_fallback_forms, _kpi_pct_suffix)
    mark, gap, tail = "", "", ""
    diff = price - th
    gap = gap_txt(price, th, qual_hit)
    mark = tier_dot(qual_hit, diff, th)
    tail = _MKT_NOTE_PAREN if (price < th and not qual_hit) else ""
    core = f"{mark}{label} ￥{price:.0f}"
    base = (f"**{core}**" if mark == TIER_EMOJI["qual"] + " " else core)
    mid = base + f"　线￥{th:.0f}　{gap}"
    forms = _pct_fallback_forms(mid + tail, _kpi_pct_suffix(price, th))
    return _fit_line(forms[0], fallbacks=forms[1:] + [mid, base])


def test_kpi_line_soldier_cases_within_budget():
    """M1：降级链替换曾丢旧链深档——pct 空（达标带+行情注）地板档
    43 宽直出、pct 非空 45 宽直出且行情注反留。修复后两 Soldier
    样本地板档 ≤40，且 pct 非空超宽时行情注先于裸价丢失（档序=
    pct 形态→注→裸价）。"""
    from core.alerter import _disp_dw
    l1 = _kpi_line_replay("中转", 4991, 5000, False)
    l2 = _kpi_line_replay("中转", 4400, 5000, False)
    assert _disp_dw(l1) <= 40, (_disp_dw(l1), l1)
    assert _disp_dw(l2) <= 40, (_disp_dw(l2), l2)
    assert "（行情价）" not in l2, l2


def test_kpi_fallback_chain_has_deep_tiers():
    """M1 源码钉：pct 三档链尾必须接旧链深档 [mid, base]（丢行情注
    →裸价）——只接 forms[1:] 时 pct 空三档同形=零降级、pct 非空
    链尾=mid+tail 档序颠倒。"""
    src = open("report.py", encoding="utf-8").read()
    assert "fallbacks=forms[1:] + [mid, base]" in src, (
        "日报 KPI 降级链缺深档：pct 链尾须接 [mid, base]")


def test_ntfy_trunc_colon_strip_on_hard_cut(monkeypatch):
    """m1：URL 起点在 600 截点之外（硬截路径）截尾停「文字: 」同样
    要剥——冒号剥在截断分支统一施，非截断正文尾冒号合法不剥。"""
    import core.notifier as N
    calls = []
    monkeypatch.setattr(N.httpx, "post",
                        lambda u, **kw: (calls.append(kw),
                                         mock.Mock(status_code=200))[1])
    nt = N.NtfyNotifier(topic="t", logger=_lg.getLogger("t"))
    # 「￥99: 」冒号恰在索引 599、URL 起点 601 ≥ 600 → 硬截路径
    body = "y" * 595 + " ￥99: https://example.com/long/url/segment"
    assert nt.send("标题", body) is True
    sent = calls[-1]["json"]["message"]
    assert "已截断" in sent
    head = sent.split("（已截断")[0]
    assert not head.rstrip().endswith(("：", ":", " ", "\u3000")), (
        "硬截路径悬垂冒号在场：%r" % head[-24:])


def test_ntfy_non_trunc_keeps_legit_tail_colon(monkeypatch):
    """冒号剥只在截断分支施：短正文以冒号结尾（合法标点）不剥。"""
    import core.notifier as N
    calls = []
    monkeypatch.setattr(N.httpx, "post",
                        lambda u, **kw: (calls.append(kw),
                                         mock.Mock(status_code=200))[1])
    nt = N.NtfyNotifier(topic="t", logger=_lg.getLogger("t"))
    assert nt.send("标题", "完整词面如下：") is True
    sent = calls[-1]["json"]["message"]
    assert sent.rstrip().endswith("："), sent
