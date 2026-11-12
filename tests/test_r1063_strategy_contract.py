# -*- coding: utf-8 -*-
"""r1063：策略目录的十轴矩阵必须无缺口，且判据不是恒真。

十轴沿用 core/channel_contract.py 的语言：可配置/可观测/可干预/可开启/
可中断/可区分/可识别/可建议/可独立/语义清晰。每一格都去读**真实登记点**
（config 键被生产代码读、路由真存在、控件真有落点），不读第二份声明。

注意（preflight 裁决）：本文件只钉「目录自身完整性 + 可配置/语义清晰/可识别」
三轴——另外四轴（可观测/可干预/可开启/可中断/可区分/可建议/可独立）要等
T6/T12/T13 把接口与界面建起来才可能存在，十轴全绿的断言在 T12。
"""
import dataclasses
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Spec 附录 B 的首批 28 条：id / 中文名 / 族 / trigger / scope。
# 硬约束是「逐字一致」——T2/T3 会往目录里加参数，这张表是那时唯一的拦截点。
#
# **scope 列纠正（波次六，2026-11-07）**：附录 B 写这三行时波次一的接线还没
# 落地，scope 是当时的猜测。现在读点已定，声明必须跟着事实走：
#   * `breaker_switch`：`core/pacing.py::observe` 用
#     `switch_on(..., plat=, dim=, path=)` ⇒ 四层全真生效；
#   * `policy_gate`：两个采集器的 `_policy_enabled(dim=…)` ⇒ 到维度级，
#     **没有** `path=`（闸门是采集入口，一次采集跨多条链路）；
#   * `warmup`：`pacing.observe` 与 `main._warm_once(c, dim)` 都递维度 ⇒
#     到维度级；链路级只有软拒分支拿得到 path，只到一半就不算支持。
# 表里改的就是这三行，其余 25 行一个字没动（对账仍然逐字）。
APPENDIX_B = (
    ("ttl_tier", "分层 TTL", "节奏", "proactive", ("global", "channel", "dimension")),
    ("near_window", "邻近比价窗口", "节奏", "proactive", ("global", "channel")),
    ("cadence", "渠道最小间隔", "节奏", "proactive", ("global", "channel")),
    ("schedule_clock", "周期/扰动/错峰", "节奏", "proactive", ("global",)),
    ("quiet_window", "静默窗", "节奏", "proactive", ("global",)),
    ("rate_min_gap", "最小请求间隔", "限速", "reactive",
     ("global", "channel", "path")),
    ("rate_per_minute", "每分钟上限", "限速", "reactive",
     ("global", "channel", "path")),
    ("concurrency", "并发上限/平台锁", "限速", "proactive", ("global",)),
    ("channel_rate", "渠道内限速档", "限速", "proactive",
     ("global", "channel")),
    ("budget", "单次采集预算", "限速", "reactive", ("channel",)),
    ("breaker_switch", "熔断总开关", "熔断", "reactive",
     ("global", "channel", "dimension", "path")),
    ("breaker_ladder", "冷却阶梯", "熔断", "reactive", ("global",)),
    ("login_cooldown", "登录墙冷却", "熔断", "reactive", ("global",)),
    ("challenge_cooldown", "硬风控冷却", "熔断", "reactive", ("global",)),
    ("session_reset", "会话重建", "熔断", "reactive",
     ("global", "channel")),
    ("health_penalty", "成功率保护（含五档阈值）", "健康", "reactive",
     ("global", "channel", "dimension", "path")),    ("policy_gate", "策略闸门", "风险", "auto",
     ("global", "channel", "dimension")),
    ("pace_factor", "间隔倍率五档", "风险", "auto",
     ("global", "channel", "dimension", "path")),
    ("block_window", "停手窗口", "风险", "auto", ("global", "channel")),
    ("risk_bands", "风险分档 + 登录退避阶梯", "风险", "reactive",
     ("global", "channel")),
    ("warmup", "首页预热", "预热", "proactive",
     ("global", "channel", "dimension")),
    ("stealth_humanize", "指纹一致性 + 拟人化", "身份", "proactive", ("global",)),
    ("identity_headers", "UA / 移动 UA / TLS 指纹", "身份", "proactive",
     ("global", "channel")),
    ("proxy_route", "出口/代理选择", "身份", "proactive", ("global", "channel")),
    ("rotate_advice", "换身份建议", "身份", "proactive", ("channel",)),
    ("slider_attempt", "滑块自动尝试", "挑战", "reactive", ("global", "channel")),
    ("slider_guard", "滑块失败拉黑", "挑战", "reactive", ("global", "channel")),
    ("captcha_solve", "验证码识别", "挑战", "reactive",
     ("global", "channel")),
    ("app_fallback", "换跑道", "通路", "reactive",
     ("global", "channel", "dimension")),
    ("path_fallback", "通路回退顺序", "通路", "proactive", ("channel", "path")),
    ("retired_path", "退役通路口径", "通路", "reactive", ("channel", "path")),
)


def _audit():
    """目录全量审计的便捷入口（brief 正文里的 `_audit()` 引用）。"""
    from core import strategy_contract as sc
    return sc.audit()


def test_registry_has_all_strategies_with_unique_ids():
    from core.strategy_contract import STRATEGIES
    # r1063 T22/T31/T47：31 条（换跑道、渠道内限速档、会话重建）。
    assert len(STRATEGIES) == 31
    ids = [s.id for s in STRATEGIES]
    assert len(ids) == len(set(ids))
    assert {"ttl_tier", "rate_per_minute", "policy_gate", "block_window",
            "app_fallback",
            "channel_rate"} <= set(ids)


def test_registry_matches_appendix_b_row_by_row():
    """28 条必须与 Spec 附录 B 逐字一致（id/中文名/族/trigger/scope/顺序）。"""
    from core.strategy_contract import STRATEGIES
    got = [(s.id, s.cn, s.family, s.trigger, tuple(s.scope)) for s in STRATEGIES]
    assert got == list(APPENDIX_B), [
        (a[:4], b[:4]) for a, b in zip(got, APPENDIX_B) if a != b][:3]


def test_configurable_axis_reads_real_production_code():
    """可配置轴：cfg 点路径的末段必须出现在生产代码里。

    负控（本测试下半段）：把一个 pid 的 cfg 改成不存在的键 → **该轴**必须报 n
    （只看「这一行有 n」会被其它轴本来就有缺口糊弄过去）。
    """
    from core import strategy_contract as sc
    rows = [r for r in sc.audit() if r.axis == "configurable"]
    assert rows, "audit 没求值"
    assert not [r for r in rows if r.state == "n"], [
        (r.sid, r.plat, r.note) for r in rows if r.state == "n"][:5]

    bad = dataclasses.replace(
        sc.STRATEGIES[0],
        params=(sc.Param("ttl_tier.fast", "schedule.no_such_key_xyz",
                         "int", 15),))
    rows2 = [r for r in sc.audit(strategies=(bad,)) if r.axis == "configurable"]
    assert rows2, "负控没有求值"
    assert all(r.state == "n" for r in rows2), (
        "判据恒真：伪键被放过", [(r.plat, r.state, r.note) for r in rows2][:3])


def test_unread_new_key_is_reported_n():
    """附录 B 的「新键」现在真没人读 → 必须 n（不能靠本模块自己的文字点亮）。"""
    from core import strategy_contract as sc
    one = dataclasses.replace(
        [s for s in sc.STRATEGIES if s.id == "block_window"][0],
        params=(sc.Param("block_window.s", "crawler.policy.block_s",
                         "int", 300, 0, 86400),),
        na_reason="")
    rows = [r for r in sc.audit(strategies=(one,)) if r.axis == "configurable"]
    assert rows and all(r.state == "n" for r in rows), [
        (r.plat, r.state, r.note) for r in rows][:3]


def test_generic_leaf_needs_parent_corroboration():
    """`enabled` / `text` 这类泛化末段：父段不在同一文件读，就不能算「被读到」。"""
    from core import strategy_contract as sc
    one = dataclasses.replace(
        [s for s in sc.STRATEGIES if s.id == "breaker_switch"][0],
        params=(sc.Param("breaker_switch.enabled",
                         "crawler.nowhere_xyz.enabled", "bool", True),))
    rows = [r for r in sc.audit(strategies=(one,)) if r.axis == "configurable"]
    assert rows and all(r.state == "n" for r in rows), [
        (r.plat, r.state, r.note) for r in rows][:3]


def test_audit_never_counts_its_own_module_as_production_code():
    """本模块不能出现在自己的「生产代码扫描集」里，否则判据必然自证成立。"""
    from core import strategy_contract as sc
    prod = sc._ctx().prod
    assert prod, "扫描集为空"
    # 扫描集的键是相对仓库根、正斜杠写法（Windows 上也一样）
    assert "core/strategy_contract.py" not in prod, (
        "审计模块把自己当成生产读点：判据会恒真")


def test_semantics_and_identifiable_axes_are_clean():
    from core import strategy_contract as sc
    for axis in ("semantics", "identifiable"):
        bad = [r for r in sc.audit() if r.axis == axis and r.state == "n"]
        assert not bad, (axis, [(r.sid, r.plat, r.note) for r in bad][:5])


def test_na_cells_must_say_why():
    rows = [r for r in _audit() if r.state == "na"]
    assert rows, "一个 na 都没有，说明判据没真的求值"
    assert all(r.note.strip() for r in rows), "na 必须写明理由"


def test_cli_prints_the_matrix():
    import subprocess
    import sys
    out = subprocess.run([sys.executable, "-m", "core.strategy_contract"],
                         cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8")
    assert out.returncode == 0, out.stdout[-800:] + out.stderr[-800:]
    assert "策略" in out.stdout
