# -*- coding: utf-8 -*-
"""r1063 T5：`decide()` 出**决策明细**（谁说了算）+ **人工停手最先生效**。

本文件钉四件事（外加三条复核提出的收口项）：

1. **人工停手（halt）优先级最高**：人工点了「停手」，`decide()` 必须在读
   风险分、状态机、产量之前就把它执行掉——人工判断不能败给自动分档。
   到期自动失效（`minutes<=0` 立即过期），不写 `policy_state.json`。
2. **「解除自动熔断」≠「恢复人工停手」**：`reset_auto()` 只清自动状态机，
   `strategy_halt.json` 一动不动（两件事在界面上也是两个按钮）。
3. **决策明细带来源**：`ChannelPolicy.decisions` 逐条记「这条决策读了哪个
   参数、生效值多少、来自哪一层（默认/全局/渠道/维度/链路）、为什么读」。
   这是界面回答「谁说了算」的唯一数据来源（T12/T13 消费）。
4. **坏账本不许炸闸门**：手改过的 `policy_state.json` 里 `until` 写成
   `"一小时后"` 时，`float()` 会抛 `ValueError` → `crawlers/base.py` 的裸
   `except` 吞成 `pol is None` → 闸门静默全开。这里与参数坏值同律收口。

运行（必须带 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，否则插件加载超时）：

    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
      tests/test_r1063_strategy_interrupt.py -q
"""
import json
import logging
import os
import time

import pytest

from core import strategy_params as sp


@pytest.fixture(autouse=True)
def _cfg():
    """参数层是**进程级单例**：本文件改过配置后必须清空，别污染别的文件。

    （`tests/test_r913_policy_engine.py` 断言默认 1.0×，读到本文件留下的
    2.0× 会红在一个跟它无关的地方。）
    """
    sp.invalidate()
    yield
    sp.invalidate()


def _eng(tmp_path, profile="ctrip"):
    from core.policy import PolicyEngine
    return PolicyEngine({}, repo_root=str(tmp_path), profile=profile)


# ---------------------------------------------------------------------------
# 1. 人工停手最先生效（brief 原文四条）
# ---------------------------------------------------------------------------
def test_halt_beats_state_machine(tmp_path):
    """人工停手必须压过一切自动档位：状态 blocked、不放行、理由写得明白。"""
    from core.policy import PolicyEngine, set_halt
    eng = PolicyEngine({}, repo_root=str(tmp_path), profile="ctrip")
    set_halt(eng.base_dir, "ctrip", 5, "人工核查中")
    p = eng.decide("ctrip", two_way=True)
    assert p.allow is False and p.state == "blocked"
    assert any("人工停手" in r for r in p.reasons)
    # 停手窗口 = 人工给的 5 分钟（不是参数层的 block_window）
    assert 0 < p.wait_s() <= 5 * 60
    # 停手期间的倍率仍来自参数层（`pace_factor.blocked`），不是字面量
    assert p.pace_factor == sp.resolve("pace_factor.blocked").value
    assert p.need_warmup is True
    # 明细里确实记下了这条被读出来的倍率
    assert any(x["pid"] == "pace_factor.blocked" for x in p.decisions), p.decisions


def test_halt_beats_persisted_blocked_window(tmp_path):
    """人工停手的到期时间以**人工给的**为准，不沿用自动停手的旧窗口。"""
    from core.policy import read_halt, set_halt
    eng = _eng(tmp_path)
    os.makedirs(eng.base_dir, exist_ok=True)
    old_until = time.time() + 30 * 60
    with open(eng.state_path, "w", encoding="utf-8") as f:
        json.dump({"ctrip": {"state": "blocked", "until": old_until,
                             "at": time.time()}}, f)
    set_halt(eng.base_dir, "ctrip", 2, "人工核查")
    p = eng.decide("ctrip", two_way=True)
    assert p.allow is False and p.state == "blocked"
    assert p.stop_until < old_until, "人工停手的到期时间被自动窗口顶掉了"
    assert read_halt(eng.base_dir)["ctrip"]["note"] == "人工核查"


def test_halt_expires_by_itself(tmp_path):
    from core.policy import PolicyEngine, set_halt
    eng = PolicyEngine({}, repo_root=str(tmp_path), profile="ctrip")
    set_halt(eng.base_dir, "ctrip", 0, "一秒后失效")   # minutes=0 → 立即过期
    assert eng.decide("ctrip", two_way=True).allow is True


def test_reset_does_not_clear_halt(tmp_path):
    """「解除自动熔断」与「恢复人工停手」是两件事。"""
    from core.policy import PolicyEngine, set_halt, read_halt
    eng = PolicyEngine({}, repo_root=str(tmp_path), profile="ctrip")
    set_halt(eng.base_dir, "ctrip", 30, "人工")
    eng.reset_auto()   # 新增：只清 policy_state 里的 blocked/余温
    assert "ctrip" in read_halt(eng.base_dir)
    # 而且停手仍然生效：reset 不许顺手把人工停手解掉
    assert eng.decide("ctrip", two_way=True).allow is False


def test_decisions_expose_source_so_ui_can_say_who_decided(tmp_path):
    from core.policy import PolicyEngine
    from core import strategy_params as sp
    sp.set_config({"crawler": {"policy": {"pace": {"watch": 2.0}}}})
    p = PolicyEngine({}, repo_root=str(tmp_path), profile="x").decide(
        "ctrip", two_way=True)
    d = {x["pid"]: x for x in p.decisions}
    assert d["pace_factor.healthy"]["source"] in ("default", "global")


# ---------------------------------------------------------------------------
# 2. halt 与 policy_state.json 严格分家
# ---------------------------------------------------------------------------
def test_halt_does_not_leak_into_policy_state(tmp_path):
    """`policy_state.json` 的 `{state,until,at}` 形状不许被 halt 污染。

    为什么重要：那个文件是**自动**状态机（到期自动转 rehab）。把人工停手写
    进去，`reset_auto()` 就会顺手解掉人工停手，而余额/余温也会被 5 分钟的
    人工窗口改写——两套语义混在一个文件里必然互相打架。
    """
    from core.policy import set_halt
    eng = _eng(tmp_path)
    set_halt(eng.base_dir, "ctrip", 5, "人工核查中")
    pol = eng.decide("ctrip")                 # 非 two_way：会走落盘路径
    assert pol.state == "blocked" and pol.allow is False
    assert not os.path.isfile(eng.state_path), (
        "人工停手被写进了 policy_state.json：%s" % eng.state_path)
    # 停手只住在自己的文件里，形状与 brief 一致
    with open(os.path.join(eng.base_dir, "strategy_halt.json"),
              encoding="utf-8") as f:
        rec = json.load(f)["ctrip"]
    assert set(rec) == {"until", "note"} and rec["note"] == "人工核查中"


def test_halt_file_contract_and_mtime_cache(tmp_path):
    """`set_halt` / `read_halt` / `clear_halt` 的返回形状与 mtime 缓存口径。"""
    from core.policy import clear_halt, read_halt, set_halt
    eng = _eng(tmp_path)
    assert read_halt(eng.base_dir) == {}       # 没有文件 = 没有停手（不抛）
    rec = set_halt(eng.base_dir, "ctrip", 30, "人工核查")
    assert isinstance(rec, dict) and rec["ctrip"]["note"] == "人工核查"
    assert rec["ctrip"]["until"] > time.time() + 29 * 60
    got = read_halt(eng.base_dir)
    assert set(got) == {"ctrip"} and set(got["ctrip"]) == {"until", "note"}
    # mtime 缓存不许把外部改写挡掉（`decide()` 每次决策都读它）
    path = os.path.join(eng.base_dir, "strategy_halt.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"ctrip": {"until": time.time() + 60, "note": "外部改写"}},
                  f, ensure_ascii=False)
    stamp = time.time() + 5
    os.utime(path, (stamp, stamp))
    assert read_halt(eng.base_dir)["ctrip"]["note"] == "外部改写"
    # 坏文件按「没有停手」处理，绝不抛
    with open(path, "w", encoding="utf-8") as f:
        f.write("{ 这不是 json")
    stamp = time.time() + 10
    os.utime(path, (stamp, stamp))
    assert read_halt(eng.base_dir) == {}
    assert clear_halt(eng.base_dir, "ctrip") is False
    set_halt(eng.base_dir, "ctrip", 30, "人工")
    assert clear_halt(eng.base_dir, "ctrip") is True
    assert read_halt(eng.base_dir) == {}


# ---------------------------------------------------------------------------
# 3. reset_auto 只清自动状态机
# ---------------------------------------------------------------------------
def test_reset_auto_clears_blocked_state(tmp_path):
    """「解除自动熔断」要真的把它解掉，否则那个按钮是假的。"""
    eng = _eng(tmp_path)
    os.makedirs(eng.base_dir, exist_ok=True)
    with open(eng.state_path, "w", encoding="utf-8") as f:
        json.dump({"ctrip": {"state": "blocked", "until": time.time() + 3600,
                             "at": time.time()}}, f)
    assert eng.decide("ctrip", two_way=True).allow is False   # 自动熔断生效
    eng.reset_auto()
    fake = _eng(tmp_path).decide("ctrip", two_way=True)
    assert fake.allow is True and fake.state == "healthy"


# ---------------------------------------------------------------------------
# 4. 决策明细的形状、顺序与来源
# ---------------------------------------------------------------------------
def test_decisions_cover_every_consulted_param_in_order(tmp_path):
    """每个被读的参数都要进明细，且是**读取顺序**（不是字典序）。"""
    from core import policy
    p = _eng(tmp_path).decide("ctrip", two_way=True)
    pids = [x["pid"] for x in p.decisions]
    assert pids == list(policy.POLICY_PIDS.values()), (
        "决策明细的参数集合/顺序与读点对不上", pids)
    for x in p.decisions:
        assert set(x) == {"pid", "value", "source", "why"}, x
        assert x["source"] in sp.SOURCES, x
        assert x["why"], "明细条目必须写清「为什么读它」：%r" % (x,)
    d = {x["pid"]: x for x in p.decisions}
    assert d["pace_factor.healthy"]["value"] == 1.0
    assert d["health_bands.min_samples"]["value"] == 8


def test_decisions_carry_channel_source_for_override(tmp_path):
    """渠道级覆盖生效时，明细必须说「渠道说了算」——不能一律标默认。"""
    eng = _eng(tmp_path)
    sp.set_config({"crawler": {"strategy_overrides": {
        "ctrip": {"pace_factor.watch": 2.0}}}})
    p = eng.decide("ctrip", two_way=True)
    d = {x["pid"]: x for x in p.decisions}
    assert d["pace_factor.watch"]["source"] == "channel"
    assert d["pace_factor.watch"]["value"] == 2.0
    # 没被覆盖的那条仍是默认值 + default 来源
    assert d["pace_factor.degraded"]["source"] == "default"


def test_as_dict_exposes_decisions_and_stays_backward_compatible(tmp_path):
    """`as_dict()` 只加键不改键：`/api/pacing` 的既有消费方不许被打破。"""
    p = _eng(tmp_path).decide("ctrip", two_way=True)
    got = p.as_dict()
    for key in ("plat", "state", "allow", "wait_s", "pace_factor", "humanize",
                "need_warmup", "rotate", "score", "reasons"):
        assert key in got, "as_dict() 丢了既有键：%s" % key
    assert isinstance(got["decisions"], list) and got["decisions"]
    assert set(got["decisions"][0]) == {"pid", "value", "source", "why"}
    # 明细是副本：改返回值不许污染决定本身
    got["decisions"][0]["value"] = "tampered"
    assert p.decisions[0]["value"] != "tampered"


# ---------------------------------------------------------------------------
# 5. 坏账本 / 坏参数：两条路都不许静默
# ---------------------------------------------------------------------------
def test_corrupt_policy_state_until_does_not_raise(tmp_path):
    """手改过的 `policy_state.json` 里 `until: "一小时后"` 不许炸闸门。

    原来的 `float(prev.get("until") or 0.0)` 直接抛 `ValueError`；`decide()`
    的调用方 `crawlers/base.py::_policy_now` 是裸 `except` → `pol is None` →
    `_policy_gate` 把 `None` 当放行 = **闸门静默全开**。与参数坏值同一类缺陷。
    """
    eng = _eng(tmp_path)
    os.makedirs(eng.base_dir, exist_ok=True)
    with open(eng.state_path, "w", encoding="utf-8") as f:
        json.dump({"ctrip": {"state": "blocked", "until": "一小时后",
                             "at": time.time()}}, f)
    p = eng.decide("ctrip", two_way=True)
    assert p.allow is True                       # 坏窗口当作「没有窗口」
    assert p.state == "healthy"
    assert any("无法解析" in r for r in p.reasons), (
        "坏 until 被静默吞掉了，面板上看不到一个字", p.reasons)


def test_coerce_without_warn_logs_instead_of_silence(tmp_path, caplog):
    """`_coerce` 没有 `warn` 收集器时必须打日志（与 `riskscore._say_bad` 同律）。

    为什么不能静默：`core/policy.py` 的取值点不止 `decide()` 一条，
    没有 reasons 可写的调用方（报表/界面/其它模块直接读档位）以前会
    **完全不吭声**地用默认值，用户以为配置生效了。
    """
    from core import policy
    sp.set_config({"crawler": {"policy": {"pace": {"watch": "2.0x"}}}})
    with caplog.at_level(logging.WARNING, logger="core.policy"):
        val = policy._pace("watch", "ctrip")
    assert val == 1.5, val                       # 目录里的默认值
    msgs = [r.getMessage() for r in caplog.records]
    assert any("无法解析" in m for m in msgs), msgs


def test_halt_path_still_reports_bad_param(tmp_path):
    """停手在**判定**上优先，不是**信息**上优先：坏值提示一条都不许吞。"""
    from core.policy import set_halt
    eng = _eng(tmp_path)
    set_halt(eng.base_dir, "ctrip", 5, "人工")
    sp.set_config({"crawler": {"policy": {"pace": {"blocked": "慢"}}}})
    p = eng.decide("ctrip", two_way=True)
    assert p.pace_factor == 3.0                  # pace_factor.blocked 的默认值
    assert any("无法解析" in r for r in p.reasons), p.reasons


def test_expired_halt_leaves_the_auto_window_intact(tmp_path):
    """停手过期后自动窗口照旧生效——halt 从不改写 `policy_state.json`。"""
    from core.policy import set_halt
    eng = _eng(tmp_path)
    os.makedirs(eng.base_dir, exist_ok=True)
    auto_until = time.time() + 1800
    with open(eng.state_path, "w", encoding="utf-8") as f:
        json.dump({"ctrip": {"state": "blocked", "until": auto_until,
                             "at": time.time()}}, f)
    set_halt(eng.base_dir, "ctrip", 0, "已过期的人工停手")
    p = eng.decide("ctrip", two_way=True)
    assert p.allow is False and p.state == "blocked"
    assert p.stop_until == auto_until            # 自动窗口没被人工窗口污染
    assert not any("人工停手" in r for r in p.reasons)


def test_set_halt_requires_a_channel(tmp_path):
    """空渠道 → `ValueError`：写个 `""` 键等于「点了停手什么都没发生」。"""
    from core.policy import set_halt
    eng = _eng(tmp_path)
    with pytest.raises(ValueError):
        set_halt(eng.base_dir, "", 5, "没说是哪个渠道")


# ---------------------------------------------------------------------------
# 6. 复核（2026-11-06）两条 Important：停手这条链上的失败一律不许静默
# ---------------------------------------------------------------------------
def test_halt_beats_live_risk_signals(tmp_path):
    """停手压过**实时信号**（不只是压过持久化窗口）：同引擎、同输入。

    现有用例只证明了「压过 `policy_state.json` 里的旧停手」；人工停手的真实
    场景是「这一轮正在冒滑块/登录墙，人要求先别跑」，所以这里用同一份信号
    对比两次决定：没有 halt → `degraded`，有 halt → `blocked`。
    """
    from core.policy import set_halt
    eng = _eng(tmp_path)
    live = eng.decide("ctrip", captcha=True, login_wall=True, two_way=True)
    assert (live.state, live.allow) == ("degraded", True)
    set_halt(eng.base_dir, "ctrip", 5, "人工核查中")
    p = eng.decide("ctrip", captcha=True, login_wall=True, two_way=True)
    assert p.allow is False and p.state == "blocked"
    assert p.score == 0.0, "停手短路在风险评分之前，score 不该参与"
    assert any("人工停手" in r for r in p.reasons)


def test_clear_halt_reports_write_failure(tmp_path, caplog, monkeypatch):
    """撤停手写盘失败时**不许返回 True**：halt 还在生效，界面却报「已恢复」。

    这是本项目头号缺陷的同族：失败被静默。`clear_halt` 原来把 `_save_json()`
    的返回值丢掉了。
    """
    from core import policy
    eng = _eng(tmp_path)
    policy.set_halt(eng.base_dir, "ctrip", 30, "人工")
    monkeypatch.setattr(policy, "_save_json", lambda *a, **k: False)
    with caplog.at_level(logging.WARNING, logger="core.policy"):
        ok = policy.clear_halt(eng.base_dir, "ctrip")
    assert ok is False
    msgs = [r.getMessage() for r in caplog.records]
    assert any("没能落盘" in m for m in msgs), msgs
    # 与返回值一致：文件里那条还在 → 停手继续生效
    assert "ctrip" in policy.read_halt(eng.base_dir)


def test_set_halt_reports_write_failure(tmp_path, caplog, monkeypatch):
    """下停手写盘失败同样不许假装成功（与 `clear_halt` 的失败契约对齐）。"""
    from core import policy
    eng = _eng(tmp_path)
    monkeypatch.setattr(policy, "_save_json", lambda *a, **k: False)
    with caplog.at_level(logging.WARNING, logger="core.policy"):
        rec = policy.set_halt(eng.base_dir, "ctrip", 5, "人工")
    assert rec is False, "写盘失败却返回了停手表：界面会显示「已停手」"
    msgs = [r.getMessage() for r in caplog.records]
    assert any("没能落盘" in m for m in msgs), msgs
    assert "ctrip" not in policy.read_halt(eng.base_dir)


def test_bad_halt_record_is_reported_not_forgotten(tmp_path, caplog):
    """手改坏的 halt 记录必须吭声：静默遗忘 = 「人工停手」凭空消失、采集照跑。"""
    from core import policy
    eng = _eng(tmp_path)
    os.makedirs(eng.base_dir, exist_ok=True)
    with open(os.path.join(eng.base_dir, policy.HALT_FILE),
              "w", encoding="utf-8") as f:
        json.dump({"ctrip": {"until": "明天", "note": "人工"}}, f,
                  ensure_ascii=False)
    with caplog.at_level(logging.WARNING, logger="core.policy"):
        p = eng.decide("ctrip", two_way=True)
    assert p.allow is True                       # 读不懂 → 按「未停手」
    assert any("读不懂" in r for r in p.reasons), p.reasons
    msgs = [r.getMessage() for r in caplog.records]
    assert any("读不懂" in m for m in msgs), msgs
    # 坏记录不进停手表（界面按「没有停手」显示，但 reasons/日志已经提示去查文件）
    assert "ctrip" not in policy.read_halt(eng.base_dir)


def test_non_dict_halt_record_is_reported_too(tmp_path):
    """整条记录不是字典（手写成字符串）同样要吭声，别只认 `until` 坏。"""
    from core import policy
    eng = _eng(tmp_path)
    os.makedirs(eng.base_dir, exist_ok=True)
    with open(os.path.join(eng.base_dir, policy.HALT_FILE),
              "w", encoding="utf-8") as f:
        json.dump({"ctrip": "人工停手到明天"}, f, ensure_ascii=False)
    p = eng.decide("ctrip", two_way=True)
    assert p.allow is True
    assert any("读不懂" in r and "不是字典" in r for r in p.reasons), p.reasons
    assert policy.read_halt_ex(eng.base_dir)[1] == [
        {"plat": "ctrip", "why": "整条记录不是字典：'人工停手到明天'"}]


def test_zero_minute_record_is_not_reported_as_bad(tmp_path):
    """`set_halt(..., 0)` 写下的 `until: 0` 是**合法**的「没有停手」，不许喊狼来了。"""
    from core.policy import set_halt
    eng = _eng(tmp_path)
    set_halt(eng.base_dir, "ctrip", 0, "一秒后失效")
    p = eng.decide("ctrip", two_way=True)
    assert p.allow is True
    assert not any("读不懂" in r for r in p.reasons), p.reasons


def test_set_halt_rejects_unparsable_minutes(tmp_path):
    """分钟数写坏 → `ValueError`：静默归 0 等于「点了停手立刻失效、什么都不做」。"""
    from core.policy import set_halt
    eng = _eng(tmp_path)
    for bad in ("五分钟", "abc", None):
        with pytest.raises(ValueError):
            set_halt(eng.base_dir, "ctrip", bad, "人工")
