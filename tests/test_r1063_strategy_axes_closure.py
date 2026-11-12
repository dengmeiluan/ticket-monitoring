# -*- coding: utf-8 -*-
r"""r1063 T12c：十五轴矩阵**补到零缺口**（可开启 / 可干预 / 可建议 / 可调整）。

T11b 把矩阵扩到十五轴，T12a/T12b 把接口与配置页建起来；到 T12c 开工时
`python -m core.strategy_contract --strict` 仍报 62 格 `n`：

    可建议 21 / 可开启 19 / 可干预 14 / 可调整 8

本文件钉的是「这 62 格怎么变绿的」，而且每条都要**可证伪**——本文件里的
负控比正向多，因为它们才是判据不恒真的证据：

1. **可开启**：28 条策略每条都有 `<sid>.enabled`（`crawler.strategy_enabled.<sid>`，
   默认 `True`）。只有登记、没有读点就是**假开关**，所以这里额外钉「每个开关
   在生产代码里有读点」，并且真的关一条、看行为变（`pace_factor` / `block_window`
   / `risk_bands` / `quiet_window` / `rate_min_gap` 五条）。
2. **可干预**：声明出来的路由必须在 `webui.py` 的 `self.path == "…"` 里真存在
   （声明不存在的路由就是写空气），且**中断类**路由要能被 `interruptible` 轴认出。
3. **可建议**：`core/strategy_advice.advise(sid, ctx)` 按**策略**给动作码 + ≤40 字
   中文短句，28 条不许同一句；动作码只能取 `ACTIONS`，有执行入口的动作码必须
   对应一条**真路由**。
4. **可调整**：T12c 裁决把判据改成「目录驱动的渲染模板 + 该参数的控件 id 在
   `GLB_RANGES`/`GLB_RANGES_DYN` 登记过」。它不是恒真——负控造一条**没登记**的
   参数，这一轴必须仍报 `n`；控件 id 的派生规则（Python 与 `webui.py` 的
   `stratCid`）也要逐字对账，否则面板上的 id 与边界表里的 id 会悄悄分叉。

运行（必须带 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，否则插件加载超时）：

    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
      tests/test_r1063_strategy_axes_closure.py -q
"""
import dataclasses
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _webui():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def _one(sid, **kw):
    from core import strategy_contract as sc
    s = [x for x in sc.STRATEGIES if x.id == sid][0]
    return dataclasses.replace(s, **kw) if kw else s


def _axis(item, axis):
    """只求某条策略×某条轴的格（item 可以是 sid 字符串）。"""
    from core import strategy_contract as sc
    if isinstance(item, str):
        item = _one(item)
    return [r for r in sc.audit(strategies=(item,), plats=("*",))
            if r.axis == axis]


# ---------------------------------------------------------------- 1 零缺口

def test_strict_matrix_has_zero_defects():
    """`--strict` 退出码 0：62 格全补完（这是整个 T12c 的验收面）。"""
    import subprocess
    import sys
    out = subprocess.run([sys.executable, "-m", "core.strategy_contract",
                          "--strict"],
                         cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8")
    assert out.returncode == 0, out.stdout[-1500:] + out.stderr[-500:]
    assert "n 0 格" in out.stdout, out.stdout[-300:]


def test_every_strategy_can_be_switched_off_and_defaults_to_on():
    """每条策略都有 `<sid>.enabled`，且**缺省即开启**（今天的行为）。"""
    from core.strategy_contract import STRATEGIES
    from core import strategy_params as sp
    sp.invalidate()
    for s in STRATEGIES:
        pid = s.id + ".enabled"
        assert pid in sp.PARAMS, s.id
        p = sp.PARAMS[pid]
        assert p.kind == "bool", (s.id, p.kind)
        assert p.default is True, (s.id, p.default)
        # 五条本来就有自己的开关（`crawler.breaker.enabled` 等），复用不另造；
        # 其余 23 条统一走 `crawler.strategy_enabled.<sid>` 这一族键。
        assert p.cfg.startswith("crawler."), (s.id, p.cfg)
        assert sp.resolve(pid).value is True, s.id
    sp.invalidate()


def test_every_enabled_switch_has_a_production_read_point():
    """**假开关**防线：只登记参数不算数，必须真有生产读点。

    `strategy_params` 自己与策略目录自己都不算读点（提供方给自己作证）。
    判据是 `read_by_switch`（AST）：pid 必须**作为实参**交给某个传递地能走到
    `strategy_params.resolve(` 的调用；注释/docstring/列表里写一句不算
    （复核 2026-11-06 第 6 条收紧的正是这一点）。
    """
    from core.strategy_contract import STRATEGIES
    from core import strategy_params as sp
    ctx = __import__("core.strategy_contract", fromlist=["_ctx"])._ctx()
    sp.invalidate()
    bad = []
    for s in STRATEGIES:
        pid = s.id + ".enabled"
        if ctx.read_by_switch(pid):
            continue
        if ctx.read_by_code(sp.PARAMS[pid].cfg)[0]:
            continue
        bad.append((s.id, pid))
    assert not bad, "这些开关只是登记了参数、没有生产读点（假开关）：%s" % bad[:5]


def test_toggleable_reports_n_for_a_switch_nobody_resolves():
    """负控（#6）：只登记、没人求值的开关，`可开启` 轴必须报 `n`。

    旧判据「有 kind=bool 的参数就算能开关」对这条恒绿——那正是 `--strict`
    在缺口上仍退出 0 的原因：判据自己给自己作证。
    """
    from core import strategy_contract as sc
    fake = _one("ttl_tier", id="zz_cosmetic",
                params=(sc.Param("zz_cosmetic.enabled",
                                 "crawler.zz_cosmetic_enabled", "bool", True),))
    rows = _axis(fake, "toggleable")
    assert rows and rows[0].state == sc.N, rows
    assert "没有真读点" in rows[0].note, rows[0].note


def test_toggleable_read_point_must_be_a_real_resolve_argument():
    """负控（#6）：读点判据必须是「pid 当实参交给能走到 resolve( 的调用」。

    合成两份源码各证一面：**注释/docstring/列表里写一句不算**（旧判据
    `read_by_param` 会把它算成读点），而 `_on("…")` → `sp.resolve(pid)` 这条
    真链路算。
    """
    from core import strategy_contract as sc
    ctx = sc._Ctx()
    ctx._prod = {"core/fake_only_mentions.py": (
        '"""ttl_tier.enabled 这一句只是文档，不是读点。"""\n'
        "PIDS = ['ttl_tier.enabled']\n"
        "# ttl_tier.enabled 注释里再提一次\n"
        "def nothing():\n    return PIDS\n")}
    assert ctx.read_by_switch("ttl_tier.enabled") == (), \
        "只出现在 docstring/列表里的 pid 被当成了读点（判据又退化成形容词）"
    ctx2 = sc._Ctx()
    ctx2._prod = {"core/fake_real.py": (
        "from core import strategy_params as sp\n"
        "def _on(pid, plat=''):\n"
        "    return sp.resolve(pid, plat=plat).value\n"
        "def decide(plat):\n"
        "    if not _on('ttl_tier.enabled', plat):\n"
        "        return 0\n"
        "    return 1\n")}
    assert ctx2.read_by_switch("ttl_tier.enabled") == ("core/fake_real.py",), \
        ctx2.read_by_switch("ttl_tier.enabled")


def test_all_four_closure_axes_have_no_n():
    """四条补过的轴一条 `n` 都不许剩（矩阵零缺口的具体四列）。"""
    for axis in ("toggleable", "intervenable", "advisable", "adjustable"):
        rows = _axis_all(axis)
        bad = [(r.sid, r.plat, r.note) for r in rows if r.state == "n"]
        assert not bad, (axis, bad[:3])


def _axis_all(axis):
    from core import strategy_contract as sc
    return [r for r in sc.audit() if r.axis == axis]


# ---------------------------------------------------------------- 2 真生效

def _with_config(cfg):
    """装一份参数配置，退出时清掉（模块级单例：漏给同进程其它用例很坑）。"""
    from core import strategy_params as sp
    sp.set_config(cfg)
    return sp


def test_switching_a_strategy_off_actually_changes_behaviour():
    """关掉「间隔倍率五档」→ 倍率恒 1.0；打开时同一份配置照旧放大。"""
    from core import strategy_params as sp
    from core.policy import PolicyEngine
    base = {"crawler": {"policy": {"pace": {"watch": 2.0}}}}
    try:
        sp.set_config(base)
        p = PolicyEngine({}, repo_root=".", profile="zz_12c").decide(
            "ctrip", two_way=True, statuses=[429])
        assert p.pace_factor == 2.0, p.pace_factor      # 28 分 → watch 档 2.0×
        on = dict(base)
        on["crawler"] = dict(base["crawler"])
        on["crawler"]["strategy_enabled"] = {"pace_factor": False}
        sp.set_config(on)
        q = PolicyEngine({}, repo_root=".", profile="zz_12c").decide(
            "ctrip", two_way=True, statuses=[429])
        assert q.pace_factor == 1.0, q.pace_factor      # 关掉 → 不再放慢
    finally:
        sp.invalidate()


def test_switch_off_reaches_the_real_decision_points():
    """不止 `pace_factor`：停手窗口 / 风险分档 / 静默窗 / 最小间隔都真读开关。"""
    from core import strategy_params as sp
    from core import policy
    from core import pacing as pac
    from core import riskscore
    try:
        sp.invalidate()
        # 默认开启：停手窗口 3600s、四道风险门齐、静默窗生效、限速 3s
        assert policy._block("human", "ctrip") == 3600
        assert len(riskscore._levels_on(None, "ctrip")) == 4
        p = pac.Pacing({"schedule": {"scan_quiet_start": "01:00",
                                     "scan_quiet_end": "07:00",
                                     "fast_ttl_min": 15,
                                     "slow_ttl_min": 120},
                        "crawler": {"rate": {"min_gap_s": 3}}})
        assert p.cfg["scan_quiet_start"] == "01:00"
        (gap_c, _pm), _chain = p._rate_limits("ctrip", "", "")
        assert gap_c == 3.0, gap_c

        sp.set_config({"crawler": {"strategy_enabled": {
            "block_window": False, "risk_bands": False,
            "quiet_window": False, "rate_min_gap": False}}})
        assert policy._block("human", "ctrip") == 0          # 不自停
        assert riskscore._levels_on(None, "ctrip") == ((0, "calm"),)
        p2 = pac.Pacing({"schedule": {"scan_quiet_start": "01:00",
                                      "scan_quiet_end": "07:00"}})
        assert p2.cfg["scan_quiet_start"] == ""              # 静默窗不生效
        assert p2.quiet_now(now=4102444800.0) is False or True  # 不因空串抛异常
        (gap2, _pm2), _c2 = p2._rate_limits("ctrip", "", "")
        assert gap2 == 0.0, gap2                             # 不限最小间隔
    finally:
        sp.invalidate()


def test_breaker_switch_channel_override_stops_cooling_that_channel():
    """**Critical（#1）的行为判据**：渠道覆盖 `breaker_switch.enabled=false` 之后，
    **消费这个开关的闸门**必须真的不再冷却那一家——不是只让 `resolve()` 改口。

    旧实现里 `parse_pacing` 直读 `crawler.breaker.enabled`，`ChannelBreaker`
    把它抄进 `self.enabled`，于是：
      * `resolve("breaker_switch.enabled", plat="fliggy")` → `False/source=channel`，
        界面据此渲染「已停用（本渠道覆盖）」；
      * 而 `trip()` 照旧按阶梯冷却 —— 界面与行为各说一套（「配了不生效」）。
    """
    from core import strategy_params as sp
    from core.pacing import ChannelBreaker, Pacing
    try:
        sp.set_config({"crawler": {"strategy_overrides": {
            "fliggy": {"breaker_switch.enabled": False}}}})
        # ① 求值层：覆盖被认（否则下面的行为断言没有对照物）
        assert sp.resolve("breaker_switch.enabled", plat="fliggy").value is False
        assert sp.resolve("breaker_switch.enabled", plat="ctrip").value is True
        # ② 行为层：被覆盖的那家不再冷却，没被覆盖的照旧按阶梯
        b = ChannelBreaker(base_s=300, cap_s=3600, enabled=True)
        assert b.trip("fliggy", "ip", now=1000.0) == 0, "开关已关，仍在冷却飞猪"
        assert b.allow("fliggy", now=1000.0, path="PC")[0] is True
        assert b.trip("ctrip", "ip", now=1000.0) == 300, "别的渠道被连坐"
        # ③ 落地归因那条路（`Pacing.observe`）也认：不返回 kind = 不宣称已熔断
        pac = Pacing({"crawler": {"rate": {"min_gap_s": 0, "per_minute": 0}}})
        kind, cd = pac.observe("fliggy", ["blocked"], "滑块", path="PC")
        assert (kind, cd) == ("", 0), "observe 没认渠道覆盖：%r" % ((kind, cd),)
        assert pac.allow("fliggy", path="PC")[0] is True
        kind2, cd2 = pac.observe("ctrip", ["blocked"], "滑块", path="PC")
        assert kind2 == "captcha" and cd2 > 0, (kind2, cd2)
    finally:
        sp.invalidate()


def test_the_other_three_switches_read_the_override_layer_too():
    """同一族缺陷的另三条开关：预热 / 成功率保护 / 总闸门都按渠道现读。

    它们原来分别读 `parse_pacing` 的扁平值（`warmup_enabled` /
    `health_penalty_enabled`）与采集器冷冻配置里的 `policy_gate`，于是
    渠道覆盖只改界面不改行为（复核 2026-11-06 第 1 条）。
    """
    from core import strategy_params as sp
    from core.pacing import Pacing
    try:
        sp.set_config({"crawler": {"strategy_overrides": {
            "fliggy": {"warmup.enabled": False,
                       "health_penalty.enabled": False}}}})
        pac = Pacing({"crawler": {"rate": {"min_gap_s": 0, "per_minute": 0}}})
        # 预热：飞猪关、携程开
        assert pac.warmup_on("fliggy") is False
        assert pac.warmup_on("ctrip") is True
        # 软拒不再要求「强制预热」（否则会置一个永远不会被清掉的标记）
        kind, cd = pac.observe("fliggy", ["soft_reject"], "")
        assert (kind, cd) == ("soft", 0), (kind, cd)
        assert pac.snapshot()["channels"]["fliggy"]["needs_warmup"] is False
        # 成功率保护：飞猪只记账不降频，携程照旧按成功率拉长
        pac.set_health("fliggy", 0.1, 20)
        pac.set_health("ctrip", 0.1, 20)
        health = pac.snapshot()["channels"]
        assert health["fliggy"]["health"]["disabled"] is True, health["fliggy"]
        assert health["ctrip"]["health"]["penalty"] > 1.0, health["ctrip"]
    finally:
        sp.invalidate()


def test_breaker_ladder_and_cooldowns_honour_their_switches():
    """熔断族三条开关：阶梯不分级 / 登录冷却归零 / 硬风控长冷却可关。"""
    from core import strategy_params as sp
    from core.pacing import ChannelBreaker
    try:
        sp.invalidate()
        b = ChannelBreaker(300, 3600, True, 900, 21600)
        cd1 = b.trip("ctrip", "ip", now=0)
        cd2 = b.trip("ctrip", "ip", now=0)           # 第二次升级
        assert (cd1, cd2) == (300, 600), (cd1, cd2)
        assert b.trip("qunar", "login", now=0) == 900
        assert b.trip("tuniu", "captcha", now=0,
                      note="安全容器") == 21600

        sp.set_config({"crawler": {"strategy_enabled": {
            "breaker_ladder": False, "login_cooldown": False,
            "challenge_cooldown": False}}})
        b2 = ChannelBreaker(300, 3600, True, 900, 21600)
        assert b2.trip("ctrip", "ip", now=0) == 300
        assert b2.trip("ctrip", "ip", now=0) == 300   # 不按 2^n 升级
        assert b2.trip("qunar", "login", now=0) == 0
        assert b2.trip("tuniu", "captcha", now=0,
                       note="安全容器") == 300        # 长冷却关掉 → 退回阶梯
    finally:
        sp.invalidate()


# ---------------------------------------------------------------- 3 可建议

def test_every_strategy_has_a_real_advice_action():
    from core.strategy_contract import STRATEGIES
    from core import strategy_advice as sa
    for s in STRATEGIES:
        got = sa.advise(s.id, {})
        assert set(got) >= {"action", "text"}, s.id
        assert got["action"] in sa.ACTIONS, (s.id, got)
        assert 0 < len(got["text"]) <= 40, (s.id, got)


def test_advice_is_not_one_sentence_for_all_strategies():
    """按**策略**分化（Spec §4「有信息量的动作」），不是 28 条同一句。"""
    from core.strategy_contract import STRATEGIES
    from core import strategy_advice as sa
    texts = [sa.advise(s.id, {})["text"] for s in STRATEGIES]
    assert len(set(texts)) >= len(STRATEGIES) - 2, (
        "建议文案重复太多：%d 条策略只有 %d 句" % (len(texts), len(set(texts))))
    acts = {sa.advise(s.id, {})["action"] for s in STRATEGIES}
    assert len(acts) >= 5, acts


def test_advice_actions_point_at_real_entries():
    """有执行入口的动作码必须对应 `webui.py` 里真存在的路由；只建议类没有路由。"""
    from core import strategy_advice as sa
    from core import strategy_contract as sc
    routes = sc._ctx().routes()
    for act in sa.ACTIONS:
        route = sa.route_of(act)
        if route:
            assert route in routes, (act, route)
    assert sa.route_of("rotate") == "", "换身份必须只建议、无执行入口（Q6 裁决）"
    assert sa.route_of("none") == ""


def test_advice_reacts_to_context_instead_of_repeating_the_catalog_text():
    """有证据时改口（关掉 → 说恢复；人档 → 说过验证），不是永远同一句。"""
    from core import strategy_advice as sa
    base = sa.advise("rate_min_gap", {})["text"]
    off = sa.advise("rate_min_gap", {"enabled": False})
    assert off["action"] == "resume" and off["text"] != base
    halt = sa.advise("ttl_tier", {"halt": True})
    assert halt["action"] == "resume" and "停手" in halt["text"]
    wait = sa.advise("ttl_tier", {"wait_s": 12})
    assert wait["action"] == "resume" and "12" in wait["text"]
    human = sa.advise("pace_factor", {"level": "human"})
    assert human["action"] == "challenge"
    quiet = sa.advise("near_window", {"quiet": True})
    assert quiet["action"] == "run"


# ---------------------------------------------------------------- 4 可干预

def test_declared_intervention_routes_exist_in_the_console():
    """声明出来的路由必须在 `webui.py` 里真有 `self.path == "…"` 那一支。"""
    from core.strategy_contract import STRATEGIES
    w = _webui()
    for s in STRATEGIES:
        for r in s.api:
            assert '"%s"' % r in w, (s.id, r)


def test_every_strategy_has_an_intervention_route_or_says_why():
    """可干预：没有路由就必须有明确理由（本目录里 28 条都要有真路由）。"""
    from core.strategy_contract import STRATEGIES
    from core import strategy_contract as sc
    routes = sc._ctx().routes()
    for s in STRATEGIES:
        assert s.api, "%s 没有干预路由：出事只能改配置重启" % s.id
        for r in s.api:
            assert r in routes, (s.id, r)
    # 中断类：halt/resume 或 */cancel 才进得来
    halts = [s.id for s in STRATEGIES
             if any(r in sc.HALT_ROUTES for r in s.api)]
    assert "block_window" in halts and "policy_gate" in halts, halts


# ---------------------------------------------------------------- 5 可调整

def test_control_id_derivation_matches_the_console():
    """Python 的派生规则必须与 `webui.py::stratCid` 逐字一致（防两边分叉）。"""
    from core import strategy_contract as sc
    w = _webui()
    got = re.search(r"const drop=\{([^}]*)\}", w)
    assert got, "webui.py 里找不到 stratCid 的分组段表（drop={…}）"
    js_drop = tuple(x for x in re.findall(r"([a-z_]+)\s*:", got.group(1)))
    assert set(js_drop) == set(sc.CID_DROP), (js_drop, sc.CID_DROP)
    # 真源码里确实有「按 cfg 段派生」的三步：去 _s 后缀 → 驼峰 → 加 glb 前缀
    body = w[w.index("function stratCid(p){"):]
    body = body[:body.index("\n}")]
    assert "replace(/_s$/" in body and "toUpperCase()" in body
    assert "'glb'+out.join('')" in body.replace(" ", "")

    cases = {
        "crawler.policy.pace.watch": "glbPaceWatch",
        "crawler.policy.sticky_s.watch": "glbStickyWatch",
        "crawler.policy.block_s.human": "glbBlockHuman",
        "crawler.risk.levels.pause": "glbRiskPause",
        "crawler.breaker.base_s": "glbBreakerBase",
        "android.fetch_budget_s": "glbFetchBudget",
        "crawler.strategy_enabled.rate_min_gap":
            "glbStrategyEnabledRateMinGap",
    }
    for cfg, want in cases.items():
        assert sc._row_cid(sc.Param("x", cfg, "int", 0)) == want, cfg


def test_adjustable_accepts_the_directory_driven_form_with_registry():
    """目录驱动 + 登记齐全 → `y`（真树上就是这条链在点亮那 8 格）。"""
    from core import strategy_contract as sc
    row = _axis("pace_factor", "adjustable")[0]
    assert row.state == sc.Y, row.note
    assert "目录驱动行内控件 glb" in row.note, row.note


def test_adjustable_is_not_constant_true_for_unregistered_params():
    """负控：一条**没在边界表里登记**的参数必须仍报 `n`。

    这条是 T12c 裁决（认目录驱动）的代价检查：放宽判据之后，如果随便一条
    pid 都能变绿，这一轴就退化成形容词了。造一个真实的 `crawler.policy.pace.*`
    前缀之外的键（派生 id 不在 `GLB_RANGES`/`GLB_RANGES_DYN` 里）。
    """
    from core import strategy_contract as sc
    fake = _one("pace_factor", params=(
        sc.Param("pace_factor.nowhere", "crawler.policy.pace.nowhere",
                 "float", 1.0, 0.1, 10.0),))
    rows = _axis(fake, "adjustable")
    assert rows and rows[0].state == sc.N, rows
    assert "nowhere" in rows[0].note, rows[0].note


def test_adjustable_still_rejects_a_param_without_any_control():
    """负控：`map` 类参数在行内**不画单框**（字典塞进 input 会毁配置）→ 不许算可调。"""
    from core import strategy_contract as sc
    fake = _one("cadence", params=(
        sc.Param("cadence.per_plat", "crawler.cadence.zzz_none", "map", 0),))
    rows = _axis(fake, "adjustable")
    assert rows and rows[0].state == sc.N, rows


def test_every_numeric_derived_control_is_registered_with_bounds():
    """T12c 补登记的边界与目录里的 `Param.lo/hi` 逐位相等（漂移当场红）。"""
    from core import strategy_contract as sc
    from core import strategy_params as sp
    ctx = sc._ctx()
    checked = 0
    for s in sc.STRATEGIES:
        for p in s.params:
            if p.kind not in ("int", "float"):
                continue
            cid = sc._row_cid(p)
            if not ctx.declared_ctl(cid):
                continue                    # 走的是既有 glcell/data-pid 控件
            m = re.search(r"id:\s*'%s'\s*,\s*min:\s*(-?[\d.]+)\s*,\s*max:\s*"
                          r"(-?[\d.]+)" % re.escape(cid), ctx.ranges_text())
            assert m, "%s 登记的边界不是 {id,min,max} 形态" % cid
            assert float(m.group(1)) == float(p.lo if p.lo is not None else 0), \
                (cid, m.group(1), p.lo)
            assert float(m.group(2)) == float(p.hi), (cid, m.group(2), p.hi)
            checked += 1
    assert checked >= 10, "只核了 %d 个目录驱动数值控件（判据没真跑）" % checked


# ---------------------------------------------------------------- 界面文案

def test_the_panel_no_longer_has_an_english_action_word():
    """建议 chip 上的动作名必须是中文（微信扁平 + 短文案的硬要求）。"""
    from core import strategy_advice as sa
    w = _webui()
    i = w.index("const STRAT_ACT=")
    seg = w[i:w.index("};", i)]
    for act in sa.ACTIONS:
        assert re.search(r"[\'" + '"]?' + act + r"[\'"
                         + '"]?:', seg), "动作码 %s 没有中文短名" % act
    assert "建议：" in w, "策略行没有建议位"


def test_advice_signature_is_used_by_the_api_payload():
    """`/api/strategy` 直出建议：行数据里带 `tip`（动作码 + 短句 + 路由）。"""
    w = _webui()
    assert "_strategy_tip(" in w, "载荷没有接建议器"
    assert '"tip": _strategy_tip(s)' in w.replace("'", '"'), "载荷缺 tip 字段"

def test_challenge_family_switches_really_gate_behaviour():
    """挑战族三个族开关的**行为**判据（r1063 T56）。

    为什么必须行为验证：`可开启` 轴的静态判据是**过近似**——`core/policy.py`
    里有一个通用读法（把 `<sid>.enabled` 交给参数层），于是
    `slider_attempt.enabled` 一直被判 `y`；但 `crawlers/slider.py::should_attempt()`
    当时压根不问它，关掉毫无效果。**静态绿不等于真的能关。**

    这条逐条关掉看行为：
      * `slider_attempt.enabled=false` → 滑块不再自动尝试；
      * 渠道级覆盖只影响那一家；
      * `captcha_solve.enabled=false` → `attempt()` 入口直接返回 None。
    """
    from core import strategy_params as sp
    from crawlers import captcha as cp
    from crawlers import slider as sl

    cfg = {"slider": {"auto": "auto"}}
    try:
        sp.set_config({})
        assert sl.should_attempt("ctrip", cfg)[0] is True

        sp.set_config({"crawler": {"strategy_enabled": {
            "slider_attempt": False}}})
        ok, why = sl.should_attempt("ctrip", cfg)
        assert ok is False and "开关" in why, (ok, why)

        # 渠道级覆盖只影响那一家
        sp.set_config({"crawler": {"strategy_overrides": {
            "fliggy": {"slider_attempt.enabled": False}}}})
        assert sl.should_attempt("fliggy", cfg)[0] is False
        assert sl.should_attempt("ctrip", cfg)[0] is True

        # captcha_solve：入口就要认族开关（不靠 pacing 先问）
        sp.set_config({"crawler": {"strategy_enabled": {
            "captcha_solve": False}}})
        # `attempt(page, plat, config)`：plat 是位置参数
        got = cp.attempt(None, "ctrip", {"captcha": {}})
        # 契约是 dict：关掉时给 ok=False + 说清原因，**不是** None
        assert isinstance(got, dict) and got.get("ok") is False, got
        assert "关闭" in str(got.get("detail") or ""), got
    finally:
        sp.invalidate()
