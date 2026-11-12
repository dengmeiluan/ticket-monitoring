# -*- coding: utf-8 -*-
"""r1063 T4：风险档位阈值与登录退避阶梯搬进参数层后，取值必须与搬家前逐位相等。

本门禁钉三件事：
1. **逐位等价**：`core/riskscore._THRESHOLD` 的四个分界（25/45/65/80）与
   `LOGIN_BACKOFF` 的七级阶梯（0/90/300/900/1800/3600/7200）搬家前的默认值
   一字不差；
2. **退避阶梯现读配置**：`LoginLedger.backoff_s()` 按 `streak` 索引配置里的
   列表、超界取末元素（等价旧的 `min(n, len-1)` 夹取）；
3. **求值在调用那一刻**：同一个模块级参数单例 `set_config()` 之后，
   `evaluate()` 必须立刻按新的分界分档——一旦有人把阈值抄进模块常量
   （`_THRESHOLD = …`）或实例属性，第 3 条当场红。

为什么第 3 条非要「同一个对象」：参数层是进程级单例，`set_config()` 只换
cfg、不重建任何东西；把值抄进模块常量的写法在 import 那一刻就定死了，之后
用户怎么改配置都不生效——这正是本项目定义的「配了不生效」。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r1063_risk_params_equivalent.py -q
"""
import pytest

from core import strategy_params as sp

# 搬进参数层前 `core/riskscore.py` 里的字面量（逐位、含类型）
_WANT_BACKOFF = [0, 90, 300, 900, 1800, 3600, 7200]


@pytest.fixture(autouse=True)
def _cfg():
    """参数层是**进程级单例**：本文件的用例改过配置后必须清空。

    不清空的后果很实在：`tests/test_r911_web_stealth_human_risk.py` 断言
    「48 分 → slow」，它会读到本文件留下的 50 分界，红在一个跟它无关的地方。
    """
    yield
    sp.invalidate()


# ---------------------------------------------------------------------------
# 1. 逐位等价（brief 原文用例）
# ---------------------------------------------------------------------------
def test_thresholds_and_backoff_defaults_unchanged():
    sp.set_config({})
    assert [sp.resolve("risk_bands.%s" % k).value
            for k in ("watch", "slow", "pause", "human")] == [25, 45, 65, 80]
    assert sp.resolve("risk_bands.login_backoff_s").value == \
        [0, 90, 300, 900, 1800, 3600, 7200]


def test_backoff_reads_config(tmp_path):
    """brief 原文用例（账本路径换成 tmp_path：Windows 上没有 /tmp）。"""
    sp.set_config({"crawler": {"risk": {"login_backoff_s": [0, 10, 20]}}})
    from core.riskscore import LoginLedger
    led = LoginLedger(str(tmp_path / "_r1063_ll.json"))
    assert led.backoff_s("ctrip") == 0


# ---------------------------------------------------------------------------
# 2. 行为等价：默认分界下每个分段的分档不变 + 阶梯超界取末元素
# ---------------------------------------------------------------------------
def test_default_bands_classify_the_same_way_as_before():
    """搬家前的分档口径：<25 calm / <45 watch / <65 slow / <80 pause / ≥80 human。

    每一段都用真实信号拼出分数，断言的是**分档结果**（短路语义、降序顺序）。
    """
    from core import riskscore
    sp.set_config({})
    cases = [
        ({}, "calm"),                                   # 0
        ({"login_fail_streak": 3}, "calm"),             # 18（还没到 25）
        ({"login_fail_streak": 5}, "watch"),            # 30
        ({"statuses": [403]}, "watch"),                 # 28
        ({"captcha": True, "login_wall": True}, "slow"),  # 48
        ({"statuses": [429], "soft": True,
          "rate_pressure": True}, "slow"),              # 54
        ({"statuses": [429], "soft": True,
          "rate_pressure": True, "login_wall": True}, "pause"),   # 72
        ({"captcha": True, "login_fail_streak": 5,
          "rate_pressure": True, "login_wall": True}, "human"),   # 90
    ]
    for sig, want in cases:
        got = riskscore.evaluate(sig)
        assert got["level"] == want, (sig, got["score"], got["level"], want)


def test_backoff_ladder_clamps_at_last_element(tmp_path):
    """`streak` 超过列表长度时取末元素（等价旧的 `min(n, len-1)`）。"""
    from core.riskscore import LoginLedger
    sp.set_config({"crawler": {"risk": {"login_backoff_s": [0, 10, 20]}}})
    led = LoginLedger(str(tmp_path / "_r1063_ll2.json"))
    want = [0, 10, 20, 20, 20]          # streak = 0,1,2,3,4
    assert led.backoff_s("ctrip") == want[0]
    for i, exp in enumerate(want[1:], start=1):
        led.note_result("ctrip", False, now=float(i))
        assert led.rec("ctrip")["streak"] == i
        assert led.backoff_s("ctrip") == exp, (i, exp)


# ---------------------------------------------------------------------------
# 3. 求值在调用那一刻：同一份配置单例改了 → 下一次 evaluate() 换档
# ---------------------------------------------------------------------------
def test_pause_threshold_is_read_at_call_time_not_frozen():
    """`crawler.risk.levels.pause=50` 之后，50 分必须当场落到 `pause`。

    50 分怎么来的（可复核）：403 拒绝 28 + 软拒 14 + 身份自检 68 分残留 8
    = 50；身份项没占过半，所以不会跳 `rotate`。
    """
    from core import riskscore
    sp.set_config({})
    sig = {"statuses": [403], "soft": True, "identity_score": 68}
    base = riskscore.evaluate(sig)
    assert base["score"] == 50
    assert base["level"] == "slow", base["level"]   # 默认 pause=65，50 还只是 slow

    sp.set_config({"crawler": {"risk": {"levels": {"pause": 50}}}})
    got = riskscore.evaluate(sig)
    assert (got["score"], got["level"]) == (50, "pause"), (
        "改了 pause 分界但分档没跟着动：阈值被抄进模块常量/实例属性了")
    assert got["advice"]["paths"] == "none"

    # 改回去也要当场回档（证明不是「第一次求值后粘住」）
    sp.set_config({"crawler": {"risk": {"levels": {"pause": 65}}}})
    assert riskscore.evaluate(sig)["level"] == "slow"


# ---------------------------------------------------------------------------
# 4. 用户把值写坏：退回目录默认值并留一句话（与 core/policy.py 同口径）
# ---------------------------------------------------------------------------
def test_unparsable_threshold_falls_back_to_default_and_says_so():
    from core import riskscore
    sp.set_config({"crawler": {"risk": {"levels": {"watch": "低"}}}})
    got = riskscore.evaluate({"login_fail_streak": 1})        # 6 分
    assert got["level"] == "calm"                            # 默认 watch=25 生效
    assert any("无法解析" in r for r in got["reasons"]), got["reasons"]


def test_unparsable_backoff_falls_back_to_default_ladder(tmp_path):
    from core.riskscore import LoginLedger
    for i, bad in enumerate(("0,90,300", 5, None, [], [0, "很久"])):
        sp.set_config({"crawler": {"risk": {"login_backoff_s": bad}}})
        # 每个坏值一条独立账本：账本是落盘的，复用同一条会把 streak 累加上去
        led = LoginLedger(str(tmp_path / ("_bad_ll_%d.json" % i)))
        led.note_result("ctrip", False, now=1.0)              # streak=1
        assert led.backoff_s("ctrip") == 90, (bad, led.backoff_s("ctrip"))


def test_risk_pids_cover_every_literal_and_resolve():
    from core import riskscore
    assert set(riskscore.RISK_PIDS.values()) == {
        "risk_bands.watch", "risk_bands.slow", "risk_bands.pause",
        "risk_bands.human", "risk_bands.login_backoff_s"}
    for key, pid in riskscore.RISK_PIDS.items():
        assert pid in sp.PARAMS, "pid 没登记进策略目录：%s → %s" % (key, pid)
        assert sp.resolve(pid).pid == pid, pid


def test_module_backoff_literal_matches_param_default():
    """`riskscore.LOGIN_BACKOFF` 只剩「搬家前字面量 + 坏配置兜底」这一个身份：
    它必须与参数层默认值逐位一致（`test_r911` 用 `LOGIN_BACKOFF[3]` 对照阶梯，
    两者一旦漂移，那条旧门禁就失去意义）。
    """
    from core import riskscore
    sp.set_config({})
    got = tuple(sp.resolve("risk_bands.login_backoff_s").value)
    assert tuple(riskscore.LOGIN_BACKOFF) == got == tuple(_WANT_BACKOFF), (
        riskscore.LOGIN_BACKOFF, got)


def test_module_level_literals_match_param_defaults():
    """`LEVEL_DEFAULTS`（坏默认值的最后兜底）同样不许与参数层默认值漂移。"""
    from core import riskscore
    sp.set_config({})
    for key, val in riskscore.LEVEL_DEFAULTS.items():
        assert sp.resolve("risk_bands.%s" % key).value == val, key


# ---------------------------------------------------------------------------
# 5. 非单调配置下「档位 = 分数够得着的最高那道门」（`sort(reverse=True)` 的不变量）
# ---------------------------------------------------------------------------
def test_levels_are_sorted_by_score_not_by_declaration_order():
    """`pause=30` 而 `slow=70`（用户把两道门填反了）时，75 分必须判 `slow`。

    这条用例是 `_levels()` 里那句 `sort(reverse=True)` 的**唯一**判据：
    不排序时结果由四个 pid 的声明顺序（human→pause→slow→watch）决定——
    75 分会先撞上 `pause=30`（够得着），于是判 `pause`；排序后取「分数所
    达到的最高那道门」，判 `slow`。同一条配置，两种顺序给出两个不同档位，
    正是「档位随代码书写顺序漂移」的隐患。

    注意语义边界：这不是「越保守越好」的单调保证。把 `human` 配到 40 而
    `pause` 留在 65 时，50 分仍判 `pause`（65 才是它够得着的最高门）。
    """
    from core import riskscore
    sp.set_config({"crawler": {"risk": {"levels": {"pause": 30, "slow": 70}}}})
    # 28（403）+ 14（软拒）+ 12（限速压力）+ 21（身份自检 16 分 → 84/4）= 75
    high = riskscore.evaluate({"statuses": [403], "soft": True,
                               "rate_pressure": True, "identity_score": 16})
    assert high["score"] == 75
    assert high["level"] == "slow", high["level"]     # 不排序会判 pause
    # 28 + 14 + 7（身份自检 72 分 → 28/4）= 49：两道门都够不着 70，停在 pause
    assert riskscore.evaluate({"statuses": [403], "soft": True,
                               "identity_score": 72})["level"] == "pause"


def test_pause_boundary_exactly_at_the_configured_value():
    """分界是「达到即算」（`score >= 分界`）：`pause=50` 时 49 分 slow、50 分 pause。"""
    from core import riskscore
    sp.set_config({"crawler": {"risk": {"levels": {"pause": 50, "slow": 45}}}})
    # 42 + 7（身份自检 72 分 → 残留 28/4） = 49
    assert riskscore.evaluate({"statuses": [403], "soft": True,
                               "identity_score": 72})["level"] == "slow"
    # 42 + 8（身份自检 68 分 → 残留 32/4） = 50
    assert riskscore.evaluate({"statuses": [403], "soft": True,
                               "identity_score": 68})["level"] == "pause"


# ---------------------------------------------------------------------------
# 6. 渠道级覆盖：`assess()` 与 `PolicyEngine.decide()` 必须给出**同一个**档位
#    （复核 2026-11-06 Important 1：decide() 曾不带 plat，两套口径打架）
# ---------------------------------------------------------------------------
_OVERRIDE_PAUSE50 = {"crawler": {"strategy_overrides": {
    "ctrip": {"risk_bands.pause": 50}}}}


def test_assess_honours_channel_override():
    """`assess("ctrip")` 走渠道覆盖：50 分判 pause；别的渠道仍按全局值判 slow。"""
    from core import riskscore
    sp.set_config(_OVERRIDE_PAUSE50)
    sig = {"statuses": [403], "soft": True, "identity_score": 68}   # 50 分
    ctrip = riskscore.assess("ctrip", statuses=sig["statuses"],
                             soft=sig["soft"],
                             identity_score=sig["identity_score"])
    assert (ctrip["score"], ctrip["level"]) == (50, "pause"), ctrip["level"]
    other = riskscore.assess("qunar", statuses=sig["statuses"],
                             soft=sig["soft"],
                             identity_score=sig["identity_score"])
    assert other["level"] == "slow", other["level"]


def test_policy_engine_passes_plat_into_riskscore(tmp_path, monkeypatch):
    """`decide(plat, …)` 必须把渠道名交给 `evaluate()`（否则覆盖永远不生效）。"""
    from core import riskscore
    from core.policy import PolicyEngine
    seen = {}
    real = riskscore.evaluate

    def spy(signals):
        seen.update(signals)
        return real(signals)

    monkeypatch.setattr(riskscore, "evaluate", spy)
    PolicyEngine({"user_data_dir": str(tmp_path)}, repo_root=".",
                 profile="zz_r1063_risk").decide("ctrip", now=1000.0)
    assert seen.get("plat") == "ctrip", seen.get("plat")


def test_policy_and_assess_agree_under_channel_override(tmp_path):
    """同一份覆盖下，`assess("ctrip")` 与 `decide("ctrip")` 得到同一个档位。

    `ChannelPolicy` 不直接暴露 level，所以用**只有 pause 档才会有的落点**做判据：
    `state=degraded` + 倍率 = `pace_factor.blocked`(3.0) + `（pause）` 那句 reason。
    slow 档是 `degraded` + `pace_factor.degraded`(2.5)、没有 pause 那句。
    """
    from core import riskscore
    from core.policy import PolicyEngine
    sig = {"statuses": [403], "soft": True, "identity_score": 68}   # 50 分

    eng = PolicyEngine({"user_data_dir": str(tmp_path)}, repo_root=".",
                       profile="zz_r1063_risk")
    # ① 无覆盖：两边都 slow
    sp.set_config({})
    base_pol = eng.decide("ctrip", now=1000.0, two_way=True, **sig)
    base_lvl = riskscore.assess("ctrip", **sig)["level"]
    assert base_lvl == "slow"
    assert (base_pol.state, base_pol.pace_factor) == ("degraded", 2.5), (
        base_pol.state, base_pol.pace_factor)
    assert not any("（pause）" in r for r in base_pol.reasons), base_pol.reasons

    # ② 渠道覆盖 pause=50：两边都 pause
    sp.set_config(_OVERRIDE_PAUSE50)
    ovr_pol = eng.decide("ctrip", now=1000.0, two_way=True, **sig)
    ovr_lvl = riskscore.assess("ctrip", **sig)["level"]
    assert ovr_lvl == "pause"
    assert (ovr_pol.score, ovr_pol.state) == (50, "degraded")
    assert ovr_pol.pace_factor == 3.0, ovr_pol.pace_factor   # 只有 pause 档压到 3.0×
    assert any("（pause）" in r for r in ovr_pol.reasons), ovr_pol.reasons
    # ③ 别的渠道不受这条覆盖影响：两边一致地停在 slow
    other = eng.decide("qunar", now=1000.0, two_way=True, **sig)
    assert riskscore.assess("qunar", **sig)["level"] == "slow"
    assert other.pace_factor == 2.5, other.pace_factor


# ---------------------------------------------------------------------------
# 7. 坏阶梯打在**没有 reasons 可用**的那条路上（`backoff_s`）也必须留痕
# ---------------------------------------------------------------------------
def test_bad_backoff_ladder_is_logged_not_swallowed(tmp_path, caplog):
    """复核 Important 2：`backoff_s()` 那侧以前完全静默，坏配置无痕。

    `warn` 有值（`evaluate()` 路径）时只进 reasons，不重复打日志；`warn` 缺失
    （`backoff_s()` 路径）时必须出一条 warning，文案与 reasons 那句同一句。
    """
    import logging
    from core.riskscore import LoginLedger
    sp.set_config({"crawler": {"risk": {"login_backoff_s": "0,90,300"}}})
    led = LoginLedger(str(tmp_path / "_log_ll.json"))
    led.note_result("ctrip", False, now=1.0)                  # streak=1
    with caplog.at_level(logging.WARNING, logger="core.riskscore"):
        assert led.backoff_s("ctrip") == 90                   # 默认阶梯第 1 级
    hits = [r for r in caplog.records if "无法解析" in r.getMessage()]
    assert hits, [r.getMessage() for r in caplog.records]
    assert "core.riskscore" in hits[0].name, hits[0].name

    # `warn` 有值时进 reasons、**不**再额外打日志（同一句话不出现两处）
    from core import riskscore
    sp.set_config({"crawler": {"risk": {"levels": {"watch": "低"}}}})
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="core.riskscore"):
        got = riskscore.evaluate({})
    assert any("无法解析" in r for r in got["reasons"]), got["reasons"]
    assert not [r for r in caplog.records if "无法解析" in r.getMessage()]


# ---------------------------------------------------------------------------
# 8. 连目录默认值都被改坏：兜底不许在 except 里二次抛（复核顺手 3）
# ---------------------------------------------------------------------------
def test_broken_catalog_default_never_raises(tmp_path, monkeypatch):
    """`Param.default` 本身转不动时退到搬家前字面量，绝不再抛一次。

    这条路平时走不到（目录里的默认值是好的），但 `except` 分支里再抛一次
    会让 `evaluate()` 把异常漏进下游的裸 `except Exception`——那正是「静默
    放行」的入口。所以两级兜底必须都有：默认值 → `LEVEL_DEFAULTS`/`LOGIN_BACKOFF`。
    """
    import dataclasses
    from core import riskscore
    from core.riskscore import LoginLedger

    monkeypatch.setitem(
        sp.PARAMS, "risk_bands.login_backoff_s",
        dataclasses.replace(sp.PARAMS["risk_bands.login_backoff_s"],
                            default="糟糕"))
    sp.set_config({"crawler": {"risk": {"login_backoff_s": "0,90,300"}}})
    led = LoginLedger(str(tmp_path / "_bd_ll.json"))
    led.note_result("ctrip", False, now=1.0)                  # streak=1
    assert led.backoff_s("ctrip") == riskscore.LOGIN_BACKOFF[1] == 90

    monkeypatch.setitem(
        sp.PARAMS, "risk_bands.watch",
        dataclasses.replace(sp.PARAMS["risk_bands.watch"], default="糟糕"))
    sp.set_config({"crawler": {"risk": {"levels": {"watch": "低"}}}})
    got = riskscore.evaluate({})                              # 0 分
    assert got["level"] == "calm"                             # LEVEL_DEFAULTS 的 25
    assert any("无法解析" in r for r in got["reasons"]), got["reasons"]
