# -*- coding: utf-8 -*-
"""r1063：常量搬进参数层后，取值必须与搬家前逐位相等（行为不变）。

本门禁钉两件事：
1. **逐位等价**：`_PACE`/`_BLOCK_S`/`_STICKY_S`/产量阈值搬家前的默认值一字不差
   （1.0/1.5/1.5/2.5/3.0、3600/3600、1800/3600/1800、0.40/0.90/8）；
2. **决策时求值**：同一个 `PolicyEngine` 对象，改完配置再 `decide()` 必须拿到
   新数字——一旦有人把参数抄进实例属性（`self.pace_factor = …`），第 2 条当场红。
   这是本任务存在的理由：`set_config()` 只换 cfg、不重建对象。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r1063_policy_params_equivalent.py -q
"""
import os

import pytest

from core import strategy_params as sp

# 搬进参数层前 `core/policy.py` 里的字面量（逐位、含类型）
_WANT = {
    "pace_factor.healthy": 1.0,
    "pace_factor.rehab": 1.5,
    "pace_factor.watch": 1.5,
    "pace_factor.degraded": 2.5,
    "pace_factor.blocked": 3.0,
    "block_window.human": 3600,
    "block_window.rotate": 3600,
    "residue_window.watch": 1800,
    "residue_window.degraded": 3600,
    "residue_window.rehab": 1800,
    "health_bands.min_samples": 8,
    "health_bands.ok_low": 0.40,
    "health_bands.ok_high": 0.90,
}


@pytest.fixture(autouse=True)
def _cfg():
    """参数层是**进程级单例**：本文件的用例改过配置后必须清空。

    不清空的后果很实在：`tests/test_r913_policy_engine.py` 断言默认 1.0×，
    它会读到本文件留下的 2.0×，红在一个跟它无关的地方。
    """
    yield
    sp.invalidate()


def _engine(tmp_path, profile="ctrip"):
    from core.policy import PolicyEngine
    return PolicyEngine({"user_data_dir": str(tmp_path)},
                        repo_root=".", profile=profile)


def _seed_yield(tmp_path, plat, pattern):
    """在 ``<tmp>/<plat>/yield_stats.json`` 里造产量样本（True=成功）。"""
    from core.yield_stats import YieldLedger
    path = os.path.join(str(tmp_path), plat)
    os.makedirs(path, exist_ok=True)
    yl = YieldLedger(os.path.join(path, "yield_stats.json"))
    for ok in pattern:
        yl.note(plat, "pc", ok)


# ---------------------------------------------------------------------------
# 1. 逐位等价（brief 原文用例）
# ---------------------------------------------------------------------------
def test_pace_block_sticky_values_are_identical_to_pre_r1063():
    sp.set_config({})
    want = {"pace_factor.healthy": 1.0, "pace_factor.rehab": 1.5,
            "pace_factor.watch": 1.5, "pace_factor.degraded": 2.5,
            "pace_factor.blocked": 3.0,
            "block_window.human": 3600, "block_window.rotate": 3600,
            "residue_window.watch": 1800, "residue_window.degraded": 3600,
            "residue_window.rehab": 1800,
            "health_bands.min_samples": 8, "health_bands.ok_low": 0.40,
            "health_bands.ok_high": 0.90}
    for pid, val in want.items():
        got = sp.resolve(pid)
        assert (got.value, got.source) == (val, "default"), pid


def test_decide_reads_params_not_hardcoded_constants():
    """改配置后决策必须跟着变——这是「热生效」的最小证据。"""
    from core.policy import PolicyEngine
    sp.set_config({"crawler": {"policy": {"pace": {"healthy": 2.0}}}})
    eng = PolicyEngine({}, repo_root=".", profile="zz_r1063")
    p = eng.decide("ctrip", two_way=True)
    assert p.pace_factor == 2.0


# ---------------------------------------------------------------------------
# 2. 行为等价：默认值下的决策与搬家前一致（state 与倍率都钉住）
# ---------------------------------------------------------------------------
def test_default_decision_matches_pre_r1063(tmp_path):
    sp.set_config({})
    eng = _engine(tmp_path, "ctrip")
    assert eng.decide("ctrip", now=1000.0, two_way=True).pace_factor == 1.0
    slow = eng.decide("ctrip", now=1000.0, captcha=True, login_wall=True,
                      two_way=True)
    assert (slow.state, slow.pace_factor) == ("degraded", 2.5)
    # human 档 → 停 3600s、倍率 3.0、humanize 2.0（_BLOCK_S/_PACE 的原值）
    blocked = eng.decide("ctrip", now=1000.0, statuses=[403, 429, 503],
                         captcha=True, soft=True, rate_pressure=True,
                         two_way=True)
    assert blocked.state == "blocked" and blocked.allow is False
    assert blocked.pace_factor == 3.0 and blocked.wait_s(now=1000.0) == 3600


def test_rehab_and_residue_use_the_old_windows(tmp_path):
    sp.set_config({})
    eng = _engine(tmp_path, "qunar")
    # degraded 的余温窗口 3600s：1400s 后仍在窗口内
    eng.decide("qunar", now=1000.0, captcha=True, login_wall=True)
    kept = eng.decide("qunar", now=1400.0)
    assert (kept.state, kept.pace_factor) == ("degraded", 2.5)
    # 窗口过期（3600s 之后）→ 回到 healthy
    assert eng.decide("qunar", now=1000.0 + 3700).state == "healthy"


def test_yield_thresholds_are_the_old_ones(tmp_path):
    sp.set_config({})
    _seed_yield(tmp_path, "tuniu", [True] * 3 + [False] * 7)
    eng = _engine(tmp_path, "tuniu")
    bad = eng.decide("tuniu", now=1000.0, two_way=True)
    assert bad.state == "degraded" and bad.pace_factor >= 1.5
    # 3 个样本时仍「不据此调整」（min_samples=8）
    _seed_yield(tmp_path, "ctrip", [True, False, False])
    few = _engine(tmp_path, "ctrip").decide("ctrip", now=1000.0, two_way=True)
    assert (few.state, few.pace_factor) == ("healthy", 1.0)
    # 40 个样本、成功率 1.0 → ok_high=0.90 命中「可加频」0.8×
    _seed_yield(tmp_path, "fliggy", [True] * 40)
    good = _engine(tmp_path, "fliggy").decide("fliggy", now=1000.0, two_way=True)
    assert (good.state, good.pace_factor) == ("healthy", 0.8)


# ---------------------------------------------------------------------------
# 3. 决策时求值：**同一个引擎对象**，改配置 → 下一次 decide() 换数字
# ---------------------------------------------------------------------------
def test_same_engine_rereads_pace_factor(tmp_path):
    eng = _engine(tmp_path, "ctrip")
    sp.set_config({"crawler": {"policy": {"pace": {"degraded": 4.0}}}})
    first = eng.decide("ctrip", now=1000.0, captcha=True, login_wall=True,
                       two_way=True)
    assert (first.state, first.pace_factor) == ("degraded", 4.0)
    sp.set_config({"crawler": {"policy": {"pace": {"degraded": 3.5}}}})
    second = eng.decide("ctrip", now=1000.0, captcha=True, login_wall=True,
                        two_way=True)
    assert (second.state, second.pace_factor) == ("degraded", 3.5), (
        "同一个引擎对象第二次用的是旧倍率：参数被抄进了实例属性")


def test_same_engine_rereads_block_window(tmp_path):
    eng = _engine(tmp_path, "ctrip")
    sp.set_config({"crawler": {"policy": {"block_s": {"human": 120}}}})
    first = eng.decide("ctrip", now=1000.0, statuses=[403], captcha=True,
                       soft=True, rate_pressure=True, two_way=True)
    assert first.state == "blocked" and first.wait_s(now=1000.0) == 120
    sp.set_config({"crawler": {"policy": {"block_s": {"human": 300}}}})
    second = eng.decide("ctrip", now=1000.0, statuses=[403], captcha=True,
                        soft=True, rate_pressure=True, two_way=True)
    assert second.wait_s(now=1000.0) == 300


def test_same_engine_rereads_residue_window(tmp_path):
    """余温窗口是**决策时**读的：改成 0 之后，上一轮的证据当场失效。"""
    eng = _engine(tmp_path, "qunar")
    sp.set_config({})
    eng.decide("qunar", now=1000.0, captcha=True, login_wall=True)
    assert eng.decide("qunar", now=1400.0).state == "degraded"
    sp.set_config({"crawler": {"policy": {"sticky_s": {"degraded": 0}}}})
    assert eng.decide("qunar", now=1400.0).state == "healthy"


def test_same_engine_rereads_health_bands(tmp_path):
    _seed_yield(tmp_path, "tuniu", [True, False, False])
    eng = _engine(tmp_path, "tuniu")
    sp.set_config({})
    assert eng.decide("tuniu", now=1000.0, two_way=True).state == "healthy"
    # 样本门槛降到 3 → 同一批样本立刻算数
    sp.set_config({"crawler": {"health": {"min_samples": 3}}})
    low = eng.decide("tuniu", now=1000.0, two_way=True)
    assert low.state == "degraded" and low.pace_factor >= 1.5
    # 下界门槛也降下来（Wilson 下界 1/3 样本 ≈0.079）→ 又回到 healthy
    sp.set_config({"crawler": {"health": {"min_samples": 3, "ok_low": 0.05}}})
    assert eng.decide("tuniu", now=1000.0, two_way=True).state == "healthy"


# ---------------------------------------------------------------------------
# 4. 结构：常量表真的没了，pid 对照表对得上目录
# ---------------------------------------------------------------------------
def test_module_has_no_hardcoded_decision_tables():
    from core import policy
    for name in ("_PACE", "_BLOCK_S", "_STICKY_S"):
        assert not hasattr(policy, name), "常量表还在：%s" % name


def test_policy_pids_cover_every_constant_and_resolve():
    from core import policy
    assert set(policy.POLICY_PIDS.values()) == set(_WANT), (
        "POLICY_PIDS 与搬家前的常量对不上",
        sorted(set(policy.POLICY_PIDS.values()) ^ set(_WANT)))
    for key, pid in policy.POLICY_PIDS.items():
        assert pid in sp.PARAMS, "pid 没登记进策略目录：%s → %s" % (key, pid)
        assert sp.resolve(pid).pid == pid, pid


def test_engine_keeps_no_param_cache_attributes(tmp_path):
    """引擎对象上不许出现「参数缓存」属性（`self.pace = …` 这一类）。"""
    eng = _engine(tmp_path, "ctrip")
    eng.decide("ctrip", now=1000.0, captcha=True, login_wall=True,
               two_way=True)
    bad = [n for n in vars(eng)
           if any(k in n for k in ("pace", "block", "sticky", "health_band"))]
    assert not bad, "引擎对象缓存了决策参数：%s" % bad


# ---------------------------------------------------------------------------
# 5. 两套「同值近名」阈值各管各的（复核 Important 1）
# ---------------------------------------------------------------------------
def test_pacing_health_ratio_does_not_move_policy_pace(tmp_path):
    """`crawler.health_slow_ratio` 是 pacing 的 TTL 阶梯，`crawler.health.ok_low`
    是 policy 的产量分带——前者改**采集间隔**，后者改**风险姿态倍率**。

    两对默认值一个是 0.4、一个是 0.40，键名只差一个下划线/一个点，界面上还
    并排出现在同一条「成功率保护」策略行里。这条用例就是「它们不是一个旋钮」
    的证据：改前者决策不动，改后者决策才动。
    """
    _seed_yield(tmp_path, "tuniu", [True, False, False])
    eng = _engine(tmp_path, "tuniu")
    sp.set_config({"crawler": {"health": {"min_samples": 3}}})
    base = eng.decide("tuniu", now=1000.0, two_way=True)
    assert base.state == "degraded"          # Wilson 下界 0.079 < 0.40

    # ① pacing 的旋钮（`crawler.health_slow_ratio` 默认 0.4，与 ok_low 同值）
    #    连同同值近名的 slow_factor(1.5)/slowest_factor(3.0) 一起改 → 决策不动
    sp.set_config({"crawler": {"health_slow_ratio": 0.99,
                               "health_slow_factor": 9.0,
                               "health_slowest_factor": 9.0,
                               "health": {"min_samples": 3}}})
    same = eng.decide("tuniu", now=1000.0, two_way=True)
    assert (same.state, same.pace_factor) == (base.state, base.pace_factor), (
        "pacing 的 health_slow_ratio 动了 policy 的决策：两套阈值被串成一个旋钮")

    # ② 真正的 policy 旋钮（`crawler.health.ok_low`）改了 → 决策跟着动
    sp.set_config({"crawler": {"health": {"min_samples": 3, "ok_low": 0.05}}})
    assert eng.decide("tuniu", now=1000.0, two_way=True).state == "healthy"


# ---------------------------------------------------------------------------
# 6. 用户把值写坏：退回默认 + 在 reasons 里看得见（复核 Important 2）
# ---------------------------------------------------------------------------
def test_unparsable_value_falls_back_to_default_and_says_so(tmp_path):
    """手写的 `config.yaml` 里写了 `"2.0x"`：不许抛、不许静默按 1.0 走。"""
    eng = _engine(tmp_path, "ctrip")
    sp.set_config({"crawler": {"policy": {"pace": {"watch": "2.0x"}}}})
    pol = eng.decide("ctrip", now=1000.0, captcha=True, two_way=True)  # 30 分
    assert pol.state == "watch"
    assert pol.pace_factor == 1.5, pol.pace_factor      # 目录里的默认值
    assert any("无法解析" in r for r in pol.reasons), pol.reasons


def test_unparsable_value_never_breaks_the_gate(tmp_path):
    """坏值绝不能让 `decide()` 抛异常。

    失败的传播链（复核给出）：`decide()` 抛 `ValueError` →
    `crawlers/base.py::_policy_now` 的裸 `except Exception: return None` →
    `_policy_gate` 的 `if pol is None: return True` = **闸门静默全开、不留日志**，
    `_sleep` 的倍率也退回 1.0。搬家前这三张常量不可能坏，这是参数化新开的失效面。
    """
    for bad in ({"crawler": {"policy": {"block_s": {"human": "一小时"}}}},
                {"crawler": {"policy": {"sticky_s": {"degraded": "?"}}}},
                {"crawler": {"policy": {"pace": {"blocked": "慢"}}}},
                {"crawler": {"health": {"min_samples": "abc",
                                        "ok_low": "低",
                                        "ok_high": None}}}):
        sp.set_config(bad)
        pol = _engine(tmp_path, "ctrip").decide(
            "ctrip", now=1000.0, statuses=[403], captcha=True, soft=True,
            rate_pressure=True, two_way=True)          # 84 分 → human 档
        assert pol.state == "blocked"
        assert pol.wait_s(now=1000.0) == 3600          # block_s.human 的默认值
        assert pol.pace_factor == 3.0                  # pace.blocked 的默认值
        assert any("无法解析" in r for r in pol.reasons), (bad, pol.reasons)
