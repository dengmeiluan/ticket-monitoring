# -*- coding: utf-8 -*-
"""从未成功过的渠道也必须受 cadence 约束（2026-11-06 修的真缺陷）。

原实现：
    if not last:                      # 没有「成功取价」的基线
        return "fast", "无历史基线"    # ← cadence 检查在它后面，永远走不到
于是从未出过数的渠道**每轮都被跑**。实测 qunar 一天 52 次查询、0 次成功，
纯空转还持续消耗 IP 信誉——这正是"越跑越容易被风控"的一条来源。

修法：cadence 按**尝试时间**算（它本来就是「别比 N 分钟更频繁地打它」），
并提到"无基线"分支之前；尝试时间由 main.py 在真正发请求时 `note_try()` 记录。
"""
import time

from core.pacing import Pacing

KEY = ("SHA", "BKK", "2026-11-16")


def _pac(floor):
    return Pacing({"crawler": {"cadence": {"qunar": floor}}})


def test_never_tried_no_baseline_still_runs():
    """第一次必须能跑——cadence 不能把新渠道永久挡在门外。"""
    pac = _pac(120)
    tier, why = pac.plan_query("qunar", KEY, 0, days_ahead=10)
    assert tier != "skip", (tier, why)
    assert "无历史基线" in why


def test_failed_attempt_respects_cadence():
    """试过但没成功（没有基线）→ 在 cadence 内必须 skip。"""
    pac = _pac(120)
    pac.note_try("qunar", KEY, now=time.time() - 30 * 60)
    tier, why = pac.plan_query("qunar", KEY, 0, days_ahead=10)
    assert tier == "skip", (tier, why)
    assert "渠道节奏" in why, why


def test_runs_again_after_cadence():
    pac = _pac(120)
    pac.note_try("qunar", KEY, now=time.time() - 121 * 60)
    tier, _why = pac.plan_query("qunar", KEY, 0, days_ahead=10)
    assert tier != "skip"


def test_cadence_zero_never_skips():
    pac = _pac(0)
    pac.note_try("qunar", KEY, now=time.time() - 60)
    tier, _why = pac.plan_query("qunar", KEY, 0, days_ahead=10)
    assert tier != "skip"


def test_success_baseline_still_wins():
    """有成功基线时行为不变：取 max(成功时间, 尝试时间) 判 cadence。"""
    pac = _pac(120)
    now = time.time()
    pac.seed_fetch("qunar", KEY, 500.0, at_ts=now - 10 * 60)
    tier, why = pac.plan_query("qunar", KEY, 0, days_ahead=10)
    assert tier == "skip" and "渠道节奏" in why, (tier, why)


def test_tries_map_is_bounded():
    """长跑时尝试表不能无限增长（每轮多条航线 × 多个日期）。"""
    pac = _pac(120)
    now = time.time()
    for i in range(5000):
        pac.note_try("qunar", ("A", "B", "2026-11-%02d" % (i % 28 + 1)),
                     now=now)
        if i % 1000 == 0:
            pac.note_try("qunar", ("X", "Y", str(i)), now=now)
    assert len(pac._tries) <= 4096, len(pac._tries)
