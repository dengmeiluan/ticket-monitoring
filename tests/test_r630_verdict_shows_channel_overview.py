# -*- coding: utf-8 -*-
"""r630：分域结论后必须给渠道全貌，否则读者只看到「这一域没起色」。

r619 让结论严格按干预的域判（正确）。但真实库（2026-10-30 实测 qunar）：

    probe / scope=intl
    渠道级：44% (117) → 84% (98)      ← 整体大幅改善
    国际域：48% ( 46) → 53% ( 64)      ← 国际几乎没动

旧文案只写「国际域：有改善但仍偏低：48% → 53%，建议再自检一次」——
用户据此会反复点国际自检，而整体已经从 44% 涨到 84%，
真正该做的是换域或先观察。**同一份数据里的两句话必须一起给**。

负控：去掉 `_with_channel` 包装即红。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pacing import effect_verdict  # noqa: E402


def _eff(**kw):
    e = {"has": True, "action": "probe", "before": 0.44, "before_n": 117,
         "after": 0.84, "after_n": 98}
    e.update(kw)
    return e


def test_domain_verdict_also_reports_channel_overview():
    """国际域没起色、但渠道整体大好时，两句话都要有。"""
    e = _eff(scope="intl", scope_before=0.48, scope_before_n=46,
             scope_after=0.53, scope_after_n=64)
    state, hint, sev = effect_verdict(e)
    assert state == "partial", state
    assert "48%" in hint and "53%" in hint, hint          # 域结论还在
    assert "44%" in hint and "84%" in hint, (
        "没给渠道全貌，用户会一直折腾没起色的那一域：%s" % hint)
    assert "整体已可用" in hint, (
        "该域没跟上时要点明「整体已可用」：%s" % hint)


def test_domain_ok_does_not_claim_channel_is_ahead():
    """域本身已达标（tongcheng 30%→100%）时，不能再说「这个域没跟上」。"""
    e = _eff(scope="intl", scope_before=0.30, scope_before_n=40,
             scope_after=1.0, scope_after_n=40)
    state, hint, sev = effect_verdict(e)
    assert state == "improved", state
    assert "30%" in hint and "100%" in hint, hint
    assert "没跟上" not in hint, (
        "域已 100% 还说「没跟上」是自相矛盾：%s" % hint)


def test_non_domain_scope_has_no_duplicate_overview():
    """非域 scope 只有渠道级数字，不该追加重复的「同期渠道整体」。"""
    e = _eff(scope="pc")
    state, hint, sev = effect_verdict(e)
    assert "同期渠道整体" not in hint, (
        "非域 scope 不该重复一遍渠道级数字：%s" % hint)


def test_no_domain_fields_unchanged():
    """没有 scope_* 字段的老调用一字不变。"""
    state, hint, sev = effect_verdict(_eff())
    assert "同期渠道整体" not in hint, hint


def test_pending_keeps_its_single_message():
    """待判（该域无样本）不需要渠道全貌，保持简洁。"""
    e = _eff(scope="intl", scope_before=None, scope_before_n=0,
             scope_after=None, scope_after_n=0)
    state, hint, sev = effect_verdict(e)
    assert state == "pending", state
    assert "同期渠道整体" not in hint, hint
