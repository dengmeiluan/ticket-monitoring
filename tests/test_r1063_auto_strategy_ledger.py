# -*- coding: utf-8 -*-
"""r1063 T52：两条自动策略写进**同一本干预台账**（不造第二套统计）。

先查了一遍现有能力：面板每条策略行**早就**显示「干预 N 次 · 生效 M 次 · 待判 K 次」，
数据来自 `PriceStorage.strategy_stats()`（7 天窗口，只收 `strategy_*` 动作族、
`note` 以 `[<sid>]` 开头）。

也就是说「近 7 天动过几次」这件能力已经存在——**我上一轮那份 JSON 账本不该长成
第二个统计口径**。这轮把换道/会话重建两个自动动作写进那本台账，于是它们在那两行
也能显示出来，界面一行代码没改。

（JSON 账本保留，但它回答的是另一个问题：换道的"救回几条"、重建的"下一轮恢复几次"
——后者需要跨轮 `pending` 状态，台账的 `ok/rows` 表达不了。）
"""
import io
import os

import pytest

from core.storage import PriceStorage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()


@pytest.fixture()
def st(tmp_path):
    return PriceStorage(str(tmp_path / "t.db"))


def test_auto_actions_land_in_the_same_strategy_stats(st):
    """写 `strategy_*` + `[sid]` 前缀 → 必须出现在同一份 strategy_stats 里。"""
    st.save_intervention(platform="fliggy", action="strategy_app_fallback",
                         ok=True, rows=6,
                         note="[app_fallback] 换道 fliggy→app_fliggy 回采 6 条")
    st.save_intervention(platform="ctrip", action="strategy_session_reset",
                         ok=True, rows=0,
                         note="[session_reset] 换一份干净档案（连续被拦 3 次）")
    got = st.strategy_stats()
    assert got.get("app_fallback", {}).get("interventions", 0) >= 1, got
    assert got.get("session_reset", {}).get("interventions", 0) >= 1, got


def test_non_strategy_actions_do_not_pollute_strategy_stats(st):
    """人工作业不能记成"策略动过"（这是既有边界，顺手钉一下）。"""
    st.save_intervention(platform="fliggy", action="probe", ok=True, rows=1,
                         note="[app_fallback] 人工探测")
    got = st.strategy_stats()
    assert got.get("app_fallback", {}).get("interventions", 0) == 0, got


def test_main_wires_three_points():
    for needle in ("strategy_app_fallback", "strategy_session_reset"):
        assert needle in MAIN, needle
    # 三处：预置 / 换道结果 / 会话重建
    assert MAIN.count("action=\"strategy_app_fallback\"") >= 2
    assert MAIN.count("action=\"strategy_session_reset\"") >= 1
    # 每处都必须被 try 包住：台账写失败不许影响采集
    for key in ("strategy_session_reset",):
        i = MAIN.index(key)
        assert "except Exception" in MAIN[i:i + 700], key


def test_notes_carry_the_strategy_id_prefix():
    """`strategy_stats` 靠 `note` 开头的 `[<sid>]` 归集，前缀错了就归不上。"""
    for needle in ('"[app_fallback]', '"[session_reset]'):
        assert needle in MAIN, needle
