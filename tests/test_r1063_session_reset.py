# -*- coding: utf-8 -*-
"""r1063 T47：会话重建——「清掉数据后又能看到机票」变成一条可配置策略。

用户实机观察：飞猪验证码过不去，**清掉数据后又能看到机票**。这说明影子档案
（cookie / localStorage / 各类持久化指纹状态）被风控"记住"了，换一份干净档案
反而回到"匿名但可信"的状态。

纪律（每条都对应一个门禁）：
  * **只挪不删**：目录改名备份，随时可还原；
  * **保住我们的账**：`policy_state.json` / `yield_stats.json` / `login_ledger.json`
    拷回新档案——重置的是浏览器身份，不是我们的学习成果；
  * **有上限**：阈值 + 冷却 + 每日次数（重置必丢 cookie，反复重置等于打死账号）；
  * **判据明确**：只统计"被拦/挑战"，普通超时不重置。
"""
import io
import os

import pytest

from core import session_reset as sr
from core import strategy_params as sp


@pytest.fixture(autouse=True)
def _clean():
    sp.invalidate()
    yield
    sp.invalidate()


def _profile(root, plat, extra=True):
    d = os.path.join(str(root), plat)
    os.makedirs(os.path.join(d, "Default"), exist_ok=True)
    if extra:
        for fn in ("policy_state.json", "yield_stats.json"):
            with open(os.path.join(d, fn), "w", encoding="utf-8") as f:
                f.write('{"x": 1}')
    return d


def test_backup_moves_not_deletes_and_carries_our_state(tmp_path):
    d = _profile(tmp_path, "fliggy")
    rep = sr.backup("fliggy", str(tmp_path), reason="manual")
    assert rep["ok"], rep
    assert os.path.isdir(d), "新档案必须存在"
    assert os.path.isdir(os.path.join(d, "Default")) is False, "新档案要是干净的"
    # 我们的账要跟过来
    assert set(rep["kept_state"]) == {"policy_state.json", "yield_stats.json"}
    assert os.path.isfile(os.path.join(d, "policy_state.json"))
    # 旧档案还在（可还原）
    assert rep["backup"] in [b["name"] for b in sr.list_backups("fliggy",
                                                               str(tmp_path))]


def test_backup_of_missing_profile_is_not_a_success(tmp_path):
    rep = sr.backup("nope", str(tmp_path))
    assert rep["ok"] is False and "没有档案" in rep["why"]


def test_restore_brings_it_back_without_overwriting(tmp_path):
    d = _profile(tmp_path, "qunar")
    rep = sr.backup("qunar", str(tmp_path))
    # 新档案里写点垃圾，证明还原会把它挪开而不是覆盖
    with open(os.path.join(d, "junk.txt"), "w", encoding="utf-8") as f:
        f.write("x")
    r2 = sr.restore("qunar", str(tmp_path), rep["backup"])
    assert r2["ok"], r2
    assert os.path.isdir(os.path.join(d, "Default")), "原档案内容应回来了"
    assert not os.path.exists(os.path.join(d, "junk.txt"))
    assert r2["discarded"].startswith("qunar.discard_")


def test_prune_keeps_only_the_newest(tmp_path):
    _profile(tmp_path, "ctrip")
    names = []
    for _ in range(4):
        rep = sr.backup("ctrip", str(tmp_path), keep=2)
        assert rep["ok"], rep
        names.append(rep["backup"])
        # 每次都要有档案可重置
        _profile(tmp_path, "ctrip")
    left = [b["name"] for b in sr.list_backups("ctrip", str(tmp_path))]
    assert len(left) <= 2, left


def test_should_reset_respects_switch_threshold_cooldown_and_cap():
    sp.set_config({})
    # 开关默认开；未到阈值
    ok, why = sr.should_reset("fliggy", fails=1)
    assert ok is False and "未到阈值" in why, why
    # 到阈值
    ok, why = sr.should_reset("fliggy", fails=99)
    assert ok is True, why
    # 冷却中
    ok, why = sr.should_reset("fliggy", fails=99, last_reset_ts=1.0,
                              now=2.0)
    assert ok is False and "冷却" in why, why
    # 今日上限
    ok, why = sr.should_reset("fliggy", fails=99, resets_today=99)
    assert ok is False and "今日" in why, why
    # 开关关掉
    sp.set_config({"crawler": {"strategy_enabled": {"session_reset": False}}})
    ok, why = sr.should_reset("fliggy", fails=99)
    assert ok is False and "开关" in why, why


def test_auto_step_counts_only_consecutive_blocks(tmp_path):
    _profile(tmp_path, "tuniu")
    st = {}
    r1 = sr.auto_step(st, "tuniu", str(tmp_path), blocked=True)
    assert r1["acted"] is False, "第一次不该动手"
    r2 = sr.auto_step(st, "tuniu", str(tmp_path), blocked=False)
    assert r2["acted"] is False and st["fails"]["tuniu"] == 0, "没被拦要清零"
    acted = None
    for _ in range(5):
        r = sr.auto_step(st, "tuniu", str(tmp_path), blocked=True)
        if r["acted"]:
            acted = r
            break
    assert acted is not None, "达到阈值后应该真的重建"
    assert acted["result"]["ok"] is True


def test_auto_step_never_raises_on_broken_root():
    r = sr.auto_step({}, "ctrip", "\\\\?\\不存在的路径\\x", blocked=True)
    assert r["acted"] is False


def test_routes_exist_for_manual_control():
    """可干预：必须是**手也能按**的（自动只是兜底）。"""
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "webui.py"), encoding="utf-8").read()
    assert '"/api/session/reset"' in src
    assert '"/api/session/restore"' in src


def test_main_auto_hook_is_wired_and_guarded():
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "main.py"), encoding="utf-8").read()
    assert "session_reset as _sr" in src
    assert "_sr.auto_step(" in src
    # 必须被 try 包住：会话维护不许把一轮采集搞挂
    i = src.index("_sr.auto_step(")
    assert "except Exception" in src[i - 200:i + 600] or \
        "except Exception" in src[i:i + 900]
