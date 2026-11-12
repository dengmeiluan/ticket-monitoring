# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r619_verdict_follows_intervention_scope.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import os
import sys

from core.pacing import effect_verdict


# ---- merged from tests/test_r619_verdict_follows_intervention_scope.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
