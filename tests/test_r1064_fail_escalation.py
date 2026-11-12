# -*- coding: utf-8 -*-
"""连续失败 → cadence 自动升级（对所有渠道生效）。

2026-11-06 实测：qunar 一个渠道占了当天 **305 次白打**（175 次「未解析到
价格」+ 130 次「三路径空结果」），其余渠道合计只有 7 次。

固定 cadence 不足以压制：cadence 是按 (渠道, 航线, 日期) 算的，6 条航线 ×
每 2 小时 = 72 次/天，比现状 52 次好不了多少。真正要表达的是
「连续失败的渠道，越不该按正常节奏去戳」。

规则：continuous <3 → ×1；3–5 → ×2；≥6 → ×4；总上限 720 分钟；成功即清零。
soft（会话没养熟）不算失败——那是我们自己的功课没做好。
"""
import time

from core.pacing import Pacing

KEY = ("SHA", "BKK", "2026-11-16")


def _pac(floor=120):
    return Pacing({"crawler": {"cadence": {"qunar": floor}}})


def _floor_of(pac, key=KEY):
    """用 0 分钟尝试年龄反推当前生效的 cadence 地板。"""
    pac.note_try("qunar", key, now=time.time() - 1)
    _tier, why = pac.plan_query("qunar", key, 0, days_ahead=10)
    return why


def test_escalates_with_consecutive_failures():
    pac = _pac(120)
    assert "0/120" in _floor_of(pac)
    for _ in range(3):
        pac.observe("qunar", ["blocked"], "三路径空结果")
    assert "0/240" in _floor_of(pac), pac._fail_streak
    for _ in range(3):
        pac.observe("qunar", ["blocked"], "三路径空结果")
    assert "0/480" in _floor_of(pac), pac._fail_streak


def test_success_resets_immediately():
    pac = _pac(120)
    for _ in range(6):
        pac.observe("qunar", ["blocked"], "三路径空结果")
    assert pac._fail_streak.get("qunar") == 6
    pac.observe("qunar", ["ok"], "")
    assert pac._fail_streak.get("qunar") == 0
    assert "0/120" in _floor_of(pac)


def test_soft_reject_does_not_count():
    """软拒是"会话没养熟"，不是渠道坏了，不该升级 cadence。"""
    pac = _pac(120)
    pac.observe("qunar", ["soft_reject"], "软拒 444")
    assert pac._fail_streak.get("qunar", 0) == 0


def test_cap_at_720():
    pac = _pac(600)
    for _ in range(9):
        pac.observe("qunar", ["blocked"], "三路径空结果")
    # 600 × 4 = 2400，但封顶 720
    assert "0/720" in _floor_of(pac), pac._fail_streak


def test_zero_cadence_stays_off():
    """cadence=0 的渠道（如 tongcheng/fliggy）不受升级影响，仍然是 0。"""
    pac = _pac(0)
    for _ in range(6):
        pac.observe("qunar", ["blocked"], "三路径空结果")
    _tier, why = pac.plan_query("qunar", KEY, 0, days_ahead=10)
    assert "渠道节奏" not in why, why
