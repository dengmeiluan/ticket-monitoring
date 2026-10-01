# -*- coding: utf-8 -*-
"""r235 推送层（WebUI/推送审计 P1 + P2 落地）：

- _l2_fallbacks「/」联程名剥首段档（P1）：中转联程名常态形态
  「海南航空 HU7849/春秋9C8845」无「｜」营销双名——超宽时剥名档
  不可达直落地板逐字截，到达时刻烂尾「08:30→01:3」+跨天括注整体
  消失（重放场景实锤；十九§9 跨天辨识信息档序最前、十九§13② 时刻
  不可被逐字截吃掉——「｜」双名形态当年修过，「/」联程形态漏网）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r235_push.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import _disp_dw as _dw          # noqa: E402
from core.alerter import _l2_fallbacks            # noqa: E402


def test_l2_fallbacks_slash_join_leg_strip():
    """「/」联程名剥首段档：保末段航司+完整时刻+跨天括注。"""
    base = "海南航空 HU7849/春秋9C8845 08:30→01:30(+1天)"
    assert _dw(base) > 40, "前提：联程 base 原样超宽"
    tiers = _l2_fallbacks(base, "", "")
    slash = [t for t in tiers if t.startswith("春秋9C8845")]
    assert slash, "「/」剥首段档不在链上: %s" % (tiers,)
    assert "08:30→01:30(+1天)" in slash[0], "时刻/跨天被截: %s" % (tiers,)
    assert _dw(slash[0]) <= 40
    # 档序：「/」档紧邻地板档之前（地板=逐字截恒末位）
    assert tiers.index(slash[0]) == len(tiers) - 2, tiers


def test_l2_reachable_tiers_keep_arrival_and_cross():
    """行为钉：_fit_line 选取语义=首个 ≤40 档——链的选取结果必须
    保住到达时刻+跨天括注（地板逐字截档只是全超兜底，不参与选取）。"""
    base = "海南航空 HU7849/春秋9C8845 08:30→01:30(+1天)"
    for tiers in (_l2_fallbacks(base, "", ""),
                  _l2_fallbacks(base, "(+1天)", " ｜ 较上轮 ↑￥50")):
        reachable = [t for t in tiers if 0 < _dw(t) <= 40]
        assert reachable, tiers
        picked = reachable[0]
        assert "01:30" in picked, "到达时刻被截: %s ← %s" % (picked, tiers)


def test_l2_fallbacks_mixed_pipe_then_slash():
    """双名+联程混合形态：「｜」档先剥营销名；「｜」档仍超宽时
    「/」档再剥首段联程航司——两档串联皆在链上，链尾地板恒达标。"""
    base = "新海航｜海南航空 HU7849/春秋9C8845 08:30→01:30(+1天)"
    tiers = _l2_fallbacks(base, "", "")
    assert any(t.startswith("海南航空 HU7849/春秋9C8845") for t in tiers), tiers
    assert any(t.startswith("春秋9C8845") for t in tiers), tiers
    assert _dw(tiers[-1]) <= 40


def test_l2_fallbacks_pipe_form_unchanged():
    """回归：「｜」双名形态档序不变（营销名剥档先于「/」档与地板）。"""
    tiers = _l2_fallbacks(
        "新海航｜海南航空 HU7849 07:10→13:45", "(+1天)",
        " ｜ 较上轮 ↑￥50")
    assert any(t.startswith("海南航空") for t in tiers), tiers
    assert not any("较上轮" in t for t in tiers), tiers
    assert _dw(tiers[-1]) <= 40
