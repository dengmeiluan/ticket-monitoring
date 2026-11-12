# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r630_verdict_shows_channel_overview.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import os
import sys

from core.pacing import effect_verdict


# ---- merged from tests/test_r630_verdict_shows_channel_overview.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
        "域已 100%% 还说「没跟上」是自相矛盾：%s" % hint)


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
