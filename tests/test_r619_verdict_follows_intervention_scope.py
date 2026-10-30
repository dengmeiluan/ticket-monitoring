# -*- coding: utf-8 -*-
"""r619：干预结论（effect_verdict）也必须是这次干预那个域的结论。

`intervention_effect()` 给了 `scope_before/scope_after`（r512），
`effect_verdict()` 却只读渠道级 `before/after`。后果比「数字难看」更严重：
webui 用这个 verdict 把渠道级的 `path_degraded` 建议**改写成 `recovering`**：

    if (_st0 in ("improved", "recovered")
            and advice.state in ("path_degraded", "degraded")):
        _ch["advice"] = {"state": "recovering", ...}

实测形态：国际自检后国际仍 0%，但渠道级因为国内一直很好而 100% →
verdict 判「干预有效」→ 面板把「路径劣化、该处理」换成「恢复中、再观察」，
用户就此不再处理一个仍然全红的域。这是把「可判断 + 可干预」直接关掉。

判据：
  1) 干预 scope 是 dom/intl 且有该域样本时，verdict 必须按该域判；
  2) 该域判不出（样本不足）时如实说待判，不拿渠道级顶替；
  3) 非域 scope 保持渠道级口径不变。
负控：把 verdict 改回只看 before/after 即红。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pacing import effect_verdict  # noqa: E402


def _eff(**kw):
    e = {"has": True, "action": "verify", "before": 0.9, "before_n": 40,
         "after": 1.0, "after_n": 12}
    e.update(kw)
    return e


def test_domain_verdict_uses_domain_numbers():
    """渠道级 100%，但国际域 0% → 不能判「干预有效」。"""
    e = _eff(scope="intl", scope_before=0.0, scope_before_n=6,
             scope_after=0.0, scope_after_n=6)
    state, hint, sev = effect_verdict(e)
    assert state not in ("improved", "recovered"), (
        "国际域干预后国际仍 0%%，却判成 %s——verdict 只看渠道级数字" % state)
    assert "国际" in hint, "结论没说明是哪个域：%s" % hint
    assert sev == "act", "国际仍全红应给出要处理的结论：%s" % sev


def test_domain_verdict_reports_improvement_when_domain_improved():
    e = _eff(scope="intl", scope_before=0.0, scope_before_n=6,
             scope_after=1.0, scope_after_n=6)
    state, hint, sev = effect_verdict(e)
    assert state in ("improved", "recovered"), (
        "国际从 0%% 到 100%% 却判成 %s：%s" % (state, hint))
    assert "国际" in hint, hint


def test_domain_verdict_says_unjudged_instead_of_borrowing():
    """该域没有干预后样本 → 待判，不能拿渠道级的 100% 宣布有效。"""
    e = _eff(scope="intl", scope_before=0.0, scope_before_n=6,
             scope_after=None, scope_after_n=0)
    state, hint, sev = effect_verdict(e)
    assert state not in ("improved", "recovered"), (
        "国际域干预后零样本，却判成 %s——渠道级样本替它背了书" % state)
    assert "国际" in hint, hint


def test_non_domain_scope_keeps_channel_level_verdict():
    e = _eff(scope="pc")
    state, hint, sev = effect_verdict(e)
    assert state in ("improved", "recovered"), (
        "非域 scope 应保持渠道级口径：%s / %s" % (state, hint))


def test_no_domain_fields_keeps_channel_level_verdict():
    """老接口/无分域字段时行为一字不变（向后兼容）。"""
    state, hint, sev = effect_verdict(_eff())
    assert state in ("improved", "recovered"), (state, hint)
