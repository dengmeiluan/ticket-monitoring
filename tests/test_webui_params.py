# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_cfg_snapshot.py
- tests/test_r1063_hot_reload.py
- tests/test_r1063_risk_params_equivalent.py
- tests/test_r1063_scoped_reads_all.py
- tests/test_r1063_snapshot_ui.py
- tests/test_r1063_ttl_scoped.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import copy
import io
import os
import pytest
import sys
import time

from core import cfg_snapshot as cs, strategy_contract as sc, strategy_params as sp
from core.pacing import Pacing
from core.strategy_contract import STRATEGIES


# ---- merged from tests/test_r1063_cfg_snapshot.py ----

P_NUM = ("rate_min_gap.value", "crawler.rate.min_gap_s")
P_BOOL = ("ttl_tier.enabled", "crawler.strategy_enabled.ttl_tier")


def _nest(dotted, value):
    segs = [x for x in dotted.split(".") if x]
    root = {}
    node = root
    for s in segs[:-1]:
        node[s] = {}
        node = node[s]
    node[segs[-1]] = value
    return root


def test_export_only_carries_deviations():
    default_cfg = {}
    assert cs.export(default_cfg)["values"] == {}, "默认配置导出来必须是空表"
    cfg = _nest(P_NUM[1], 9)
    snap = cs.export(cfg)
    assert snap["values"] == {P_NUM[0]: 9}, snap["values"]


def test_export_keeps_overrides_and_drops_users():
    cfg = {"crawler": {"strategy_overrides": {"ctrip": {P_NUM[0]: 7}}},
           "users": [{"name": "alice", "token": "secret"}]}
    snap = cs.export(cfg)
    assert snap["overrides"] == {"ctrip": {P_NUM[0]: 7}}
    assert "users" not in snap
    assert "secret" not in str(snap), "快照里不许出现凭证"


def test_no_halt_unless_asked():
    """默认不含停手：它是运行期状态，搬过去会把"临时停"变成"永久停"。"""
    assert "halt" not in cs.export({})


def test_round_trip_is_exact():
    cfg = _nest(P_NUM[1], 9)
    cfg["crawler"]["strategy_overrides"] = {"ctrip/intl": {P_NUM[0]: 11}}
    snap = cs.export(cfg)
    fresh = {}
    got = cs.apply(fresh, snap)
    assert got["applied"] >= 1 and not got["rejected"], got
    assert cs.export(fresh)["values"] == snap["values"]
    assert cs.export(fresh)["overrides"] == snap["overrides"]


def test_scope_rows_never_leak_into_the_global_layer():
    """作用域覆盖**不许**被当成全局值写进去（真实踩过的坑）。"""
    cfg = _nest(P_NUM[1], 9)
    cfg["crawler"]["strategy_overrides"] = {"ctrip": {P_NUM[0]: 11}}
    fresh = {}
    cs.apply(fresh, cs.export(cfg))
    from core.cfg_snapshot import _get_path
    assert _get_path(fresh, P_NUM[1]) == 9, "渠道覆盖值 11 漏进了全局层"
    # pid 里本身带点（`rate_min_gap.value`），这里直接索引，别走点路径解析
    ovr = (fresh.get("crawler") or {}).get("strategy_overrides") or {}
    assert (ovr.get("ctrip") or {}).get(P_NUM[0]) == 11, ovr


def test_apply_clears_when_snapshot_says_default():
    """快照里的值是默认值 → 应用时应当把它**清回默认**，而不是留一份冗余。"""
    cfg = _nest(P_NUM[1], 9)
    snap = {"version": 1, "values": {P_NUM[0]: 3}, "overrides": {}}   # 3 = 默认
    got = cs.apply(cfg, snap)
    assert got["cleared"] == 1, got
    from core.cfg_snapshot import _get_path
    assert _get_path(cfg, P_NUM[1]) is None


def test_unknown_pid_is_rejected_loudly():
    got = cs.apply({}, {"version": 1, "values": {"nope.pid": 1},
                        "overrides": {}})
    assert got["rejected"] == [{"pid": "nope.pid", "scope": ""}], got


def test_future_version_is_refused():
    with pytest.raises(ValueError) as e:
        cs.apply({}, {"version": 99, "values": {}, "overrides": {}})
    assert "版本" in str(e.value)


def test_diff_is_readable_and_idempotent():
    cfg = _nest(P_NUM[1], 9)
    snap = cs.export(cfg)
    assert cs.diff(cfg, snap) == [], "同一份配置对比自己必须没有差异"
    other = _nest(P_NUM[1], 12)
    rows = cs.diff(other, snap)
    assert len(rows) == 1
    r = rows[0]
    assert (r["pid"], r["before"], r["after"], r["action"]) == (
        P_NUM[0], 12, 9, "set"), r


def test_dry_run_changes_nothing():
    cfg = _nest(P_NUM[1], 9)
    snap = {"version": 1, "values": {P_NUM[0]: 12}, "overrides": {}}
    before = copy.deepcopy(cfg)
    got = cs.apply(cfg, snap, dry_run=True)
    assert got["applied"] == 1
    assert cfg == before, "dry_run 不许改 cfg"


def test_values_are_clamped_on_import():
    """越界的快照值必须被夹到声明区间（与界面同一条边界）。"""
    p = [pp for s in STRATEGIES for pp in s.params if pp.pid == P_NUM[0]][0]
    cfg = {}
    cs.apply(cfg, {"version": 1, "values": {P_NUM[0]: (p.hi or 0) + 9999},
                   "overrides": {}})
    from core.cfg_snapshot import _get_path
    got = _get_path(cfg, P_NUM[1])
    assert got is not None and float(got) <= float(p.hi), (got, p.hi)


# ---- merged from tests/test_r1063_hot_reload.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _clean_params():
    """参数层是模块级单例：本文件装过的覆盖必须还原。

    不还原的后果很实在：`tests/test_r913_policy_engine.py` 之类断言默认
    1.0× 的用例会读到本文件留下的 1.3×，红在一个跟它无关的地方。
    """
    yield
    sp.invalidate()


def _main_src() -> str:
    with io.open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
        return f.read()


def _reload_seg() -> str:
    """`reload_config()` 的**整个函数体**（从定义处到模块级 `if __name__`）。

    `reload_config()` 是 `main()` 里的闭包，测试够不着（也没法只跑它：
    它前面是整套启动步骤）。所以「有没有接线」这一条只能读源码段落——但
    **只读这一段**：整份 main.py 里别处出现 `set_config(` 不算数（那可能
    在注释或另一条分支里）。

    边界按**代码边界**取（下一个模块级语句），不按字数：这段原来卡 3000
    字符，而 fix-wave 1 往里加注释时实测只剩 84 字符余量——注释多写两行就
    会把真正的接线挤出窗口，红在一个跟判据无关的地方。闭包体本身仍不越出，
    `if __name__ == "__main__":` 之后才是启动流程。
    """
    body = _main_src()
    assert "def reload_config():" in body, "main.py 里找不到 reload_config()"
    seg = body[body.index("def reload_config():"):]
    cut = seg.find('\nif __name__ == "__main__":')
    return seg[:cut] if cut > 0 else seg


# ---------------------------------------------------------------------------
# 1. 接线：reload_config 喂提供者
# ---------------------------------------------------------------------------
def test_reload_config_feeds_the_param_provider():
    seg = _reload_seg()
    assert "strategy_params.set_config(" in seg, (
        "热重载没喂参数提供者：改完配置保存，`resolve()` 还按目录默认值求值，"
        "界面上的「生效值/来源」永远是 default（配了不生效）")
    assert "set_config(cfg)" in seg, (
        "喂进去的必须就是刚读到的那份 cfg（不能是 {} 或启动时的旧 cfg）")
    assert seg.count("set_config(cfg)") == 1, (
        "reload_config 里只该有一处装载：两处会让人以为「多喂一次更保险」，"
        "实际只会让后来者分不清哪处是权威")


def test_startup_feeds_the_param_provider_before_the_first_round():
    """启动路径也要喂一次，且在**第一轮扫描之前**（`make_sweep_job` 之前）。

    只靠 reload_config 的话，装好程序后的第一轮（乃至用户从没打开过保存
    按钮的那一整天）全都按目录默认值跑——「配了不生效」的另一种形态。
    """
    body = _main_src()
    first = body.index("sweep = make_sweep_job(")
    head = body[:first]
    # 去掉 reload_config 那段再数：那一段本来就有一处（上一条用例钉的就是它），
    # 混进来会让「启动路径也喂了」恒真。
    seg_start = head.index("def reload_config():")
    startup = head[:seg_start]
    assert "strategy_params.set_config(" in startup, (
        "启动路径没有喂参数提供者：首轮决策看的还是目录默认值")
    assert "set_config(cfg)" in startup, "启动时喂的应该就是这份 cfg"


# ---------------------------------------------------------------------------
# 2. 行为：同一个引擎对象，换配置就换结论
# ---------------------------------------------------------------------------
def _engine(tmp_path, profile="hot"):
    from core.policy import PolicyEngine
    return PolicyEngine({}, repo_root=str(tmp_path), profile=profile)


def test_changed_value_reaches_decide_on_a_preexisting_engine(tmp_path):
    """brief 原文用例：引擎**先建好**，改配置后 `decide()` 必须换数字。

    这条是 T14 的存在理由：`set_config()` 只换 cfg、不重建对象。谁要是把
    参数抄进 `__init__`（`self.pace_healthy = sp.resolve(...)`），这里当场红。
    """
    sp.set_config({})
    eng = _engine(tmp_path)
    assert eng.decide("ctrip", two_way=True).pace_factor == 1.0
    sp.set_config({"crawler": {"policy": {"pace": {"healthy": 1.3}}}})
    got = eng.decide("ctrip", two_way=True)
    assert got.pace_factor == 1.3, "改配置后仍是 %s：参数被抄进实例了" % (
        got.pace_factor,)


def test_decide_detail_names_the_new_source(tmp_path):
    """明细里的 `source` 也要跟着变（界面「来源」列读的是它）。

    只看数值不够：`default → global` 才是「这条值真的从配置来」的证据。
    数值巧合相等（配置里就写着默认值）时，来源仍能分辨。
    """
    sp.set_config({})
    eng = _engine(tmp_path)
    row = [d for d in eng.decide("ctrip", two_way=True).decisions
           if d.get("pid") == "pace_factor.healthy"][0]
    assert row["value"] == 1.0 and row["source"] == "default"
    sp.set_config({"crawler": {"policy": {"pace": {"healthy": 1.3}}}})
    row = [d for d in eng.decide("ctrip", two_way=True).decisions
           if d.get("pid") == "pace_factor.healthy"][0]
    assert row["value"] == 1.3 and row["source"] == "global", row


def test_channel_override_reaches_an_existing_engine(tmp_path):
    """渠道级覆盖同理（`crawler.strategy_overrides`，作用域串 → {pid: 值}）。"""
    sp.set_config({})
    eng = _engine(tmp_path)
    assert eng.decide("ctrip", two_way=True).pace_factor == 1.0
    sp.set_config({"crawler": {"strategy_overrides": {
        "ctrip": {"pace_factor.healthy": 2.0}}}})
    assert eng.decide("ctrip", two_way=True).pace_factor == 2.0
    # 同一份配置对别的渠道不许连坐（覆盖是按作用域求值的）
    assert eng.decide("qunar", two_way=True).pace_factor == 1.0


# ---------------------------------------------------------------------------
# 3. 行为：`Pacing`（闸门）也在决策那一刻现读
# ---------------------------------------------------------------------------
def test_gate_path_sees_the_new_rate_on_a_preexisting_pacing():
    """同一个 `Pacing` 对象：改配置后 `gate_path()` 立刻按新速率拦。

    `Pacing` 的私有 `cfg` 只在 `refresh()` 时重读，但**限速值走参数层**
    （`_rate_limits` 优先 `strategy_params`）——这就是「列表里的阈值要重建、
    策略参数不用」的分界线，本用例钉的是后者。
    """
    from core.pacing import Pacing
    sp.set_config({"crawler": {"rate": {"min_gap_s": 0}}})
    pac = Pacing({"crawler": {"rate": {"min_gap_s": 0, "per_minute": 0}}})
    pac.record("ctrip", path="PC")
    ok, wait, _ = pac.gate_path("ctrip", "", "PC")
    assert ok is True and wait == 0, "配的是 0 间隔，不该等（实测 %s）" % (wait,)
    # 保存一改：同一对象，下一次闸门问话就要等
    sp.set_config({"crawler": {"rate": {"min_gap_s": 20}}})
    ok2, wait2, why2 = pac.gate_path("ctrip", "", "PC")
    assert ok2 is True and wait2 > 0, "改完配置仍不等（%s）：闸门没读参数层" % (
        why2,)


def test_path_switch_flips_the_gate_on_a_preexisting_pacing():
    """策略开关同理：`path_fallback.enabled` 一改，同一条链路当场改判。"""
    from core.pacing import Pacing
    sp.set_config({})
    pac = Pacing({"crawler": {"rate": {"min_gap_s": 0, "per_minute": 0}}})
    assert pac.gate_path("tongcheng", "intl", "PC")[0] is True
    sp.set_config({"crawler": {"path_fallback": {"enabled": False}}})
    ok, _, why = pac.gate_path("tongcheng", "intl", "PC")
    assert ok is False and "策略" in why, why
    # 恢复配置 → 又放行（热链路是双向的，不是一次性开关）
    sp.set_config({})
    assert pac.gate_path("tongcheng", "intl", "PC")[0] is True


# ---------------------------------------------------------------------------
# 3b. 四个「老开关」也要热：它们原来读的是冷冻配置/扁平值（复核 Important）
# ---------------------------------------------------------------------------
def test_policy_gate_switch_reaches_an_existing_crawler():
    """总闸门开关必须在**同一个采集器对象**上立刻改判（不重建实例）。

    旧实现读 `self.config.get("policy_gate")`：`main.reload_config()` 只喂
    参数提供者、从不重建采集器，于是界面写着「保存即生效」、实际要等重启。
    """
    import logging

    from crawlers import REGISTRY

    inst = REGISTRY["ctrip"]({"policy_gate": True}, logging.getLogger("hot"))
    sp.set_config({})
    assert inst._policy_enabled() is True
    sp.set_config({"crawler": {"policy_gate": False}})
    assert inst._policy_enabled() is False, \
        "全局关掉总闸门后同一个采集器仍放行：开关只在重启后才生效"
    sp.set_config({"crawler": {"strategy_overrides": {
        "ctrip": {"policy_gate.enabled": False}}}})
    assert inst._policy_enabled() is False, "渠道覆盖没到采集器"
    assert sp.resolve("policy_gate.enabled", plat="qunar").value is True
    sp.set_config({})
    assert inst._policy_enabled() is True, "热链路是双向的"


def test_policy_gate_switch_reaches_an_existing_app_crawler():
    """App 侧同一把开关、同一个冷冻配置问题（`AppCrawler._policy_enabled`）。"""
    from crawlers.app_base import AppCrawler

    inst = AppCrawler.__new__(AppCrawler)     # 桩对象：不跑 __init__（无 config）
    inst.config = {"policy_gate": True}
    inst.name = "app_ctrip"
    sp.set_config({})
    assert inst._policy_enabled() is True
    sp.set_config({"crawler": {"policy_gate": False}})
    assert inst._policy_enabled() is False, "App 采集器仍按冷冻配置判"
    sp.set_config({"crawler": {"strategy_overrides": {
        "app_ctrip": {"policy_gate.enabled": False}}}})
    assert inst._policy_enabled() is False
    sp.set_config({})
    assert inst._policy_enabled() is True


def test_policy_gate_switch_reaches_the_crawlers_dimension_scope():
    """总闸门开关也要能按**维度**关（r1063 fix-wave 2）。

    波次 1 只把 `plat` 递给参数层，于是 `crawler.strategy_overrides` 里
    `渠道/维度` 那一层写了 `policy_gate.enabled: false` 也是白写——采集器
    看不到，界面却按 `source=dimension` 显示「已停用」。两侧（浏览器 / App）
    同一把开关、同一个作用域参数。
    """
    import logging

    from crawlers import REGISTRY
    from crawlers.app_base import AppCrawler

    b = REGISTRY["ctrip"]({"policy_gate": True}, logging.getLogger("hot"))
    a = AppCrawler.__new__(AppCrawler)
    a.config = {"policy_gate": True}
    a.name = "ctrip"
    sp.set_config({"crawler": {"strategy_overrides": {
        "ctrip/detail": {"policy_gate.enabled": False}}}})
    for inst in (b, a):
        assert inst._policy_enabled(dim="detail") is False, \
            "维度级 policy_gate 覆盖没到采集器（%s）" % type(inst).__name__
        assert inst._policy_enabled(dim="round_trip") is True, \
            "停 detail 连坐了 round_trip（%s）" % type(inst).__name__
        # 不给 dim = 只看渠道层：与波次 1 逐位相同
        assert inst._policy_enabled() is True
    # App 侧入口真的把维度递下去：`_policy_gate(dim=…)` 是采集入口，
    # 作用域丢了就等于白算一次维度（这里直接盯它递给开关的那一句）。
    seen = []

    def _spy(dim=""):
        seen.append(dim)
        return True

    a._policy_enabled = _spy
    assert a._policy_gate(dim="detail") is True
    assert seen == ["detail"], "采集入口没有把维度递给闸门开关：%s" % (seen,)


def test_safe_fetch_hands_a_dimension_to_the_policy_gate():
    """两个入口（浏览器 / App 的 `safe_fetch`）必须把维度递给闸门。

    只加 `dim=` 参数不算接线：`_policy_gate()` 默认空串，入口不传就等于维度
    级覆盖仍然是死配置。维度取值与 `main._dim_of_query()` 同一句（挂了返程日
    = 往返，否则明细），所以这里同时钉「递了」与「不是个字面量空串」。
    """
    import ast
    import os as _os

    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    for rel in ("crawlers/base.py", "crawlers/app_base.py"):
        path = _os.path.join(root, rel.replace("/", _os.sep))
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name == "safe_fetch"), None)
        assert fn is not None, "%s 里没有 safe_fetch" % rel
        sites = [n for n in ast.walk(fn)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "_policy_gate"]
        assert sites, "%s 的 safe_fetch 没调策略闸门" % rel
        for site in sites:
            kw = {k.arg: k.value for k in site.keywords if k.arg}
            assert "dim" in kw, (
                "%s:%d 的 _policy_gate 没递维度：维度级 policy_gate 覆盖"
                "配了也不会生效" % (rel, site.lineno))
            expr = kw["dim"]
            assert not (isinstance(expr, ast.Constant) and expr.value == ""), (
                "%s:%d 递了空维度" % (rel, site.lineno))


def test_private_pacing_refresh_picks_up_the_disclosed_switches():
    """静默窗 / 错峰 / 并发是 `parse_pacing` 的**产物**，`refresh()` 要重算。

    这三条开关不进参数层的逐次求值（它们改的是扁平配置的成型结果），所以
    热生效只能靠「重跑 `parse_pacing`」。`reload_config()` 现在对
    `rt["pacing"]` 与**采集器私有实例**都做这一步——本用例钉住这一步真的
    把三条开关算进去（否则「保存后生效」又是一句空话）。
    """
    from core.pacing import Pacing

    cfg = {"schedule": {"scan_quiet_start": "01:00",
                        "scan_quiet_end": "07:00",
                        "stagger_seconds": 25},
           "crawler": {"max_concurrency": 3}}
    sp.set_config({})
    pac = Pacing(cfg)
    assert pac.cfg["scan_quiet_start"] == "01:00"
    assert pac.cfg["stagger_seconds"] == 25 and pac.cfg["max_concurrency"] == 3

    sp.set_config({"crawler": {"strategy_enabled": {
        "quiet_window": False, "schedule_clock": False, "concurrency": False}}})
    pac.refresh(cfg)                  # ← reload_config 对私有实例做的就是这一步
    assert pac.cfg["scan_quiet_start"] == "" and pac.cfg["scan_quiet_end"] == ""
    assert pac.cfg["stagger_seconds"] == 0
    assert pac.cfg["max_concurrency"] == 0


def test_reload_config_also_refreshes_the_crawler_private_pacing():
    """接线钉：`reload_config()` 必须把私有节流实例也刷一遍（不是只刷 rt 那份）。"""
    seg = _reload_seg()
    assert "pacing_cfg_for(" in seg, (
        "热重载只刷了 rt[\"pacing\"]：采集器私有实例（静默窗/错峰/并发）"
        "要等到下一轮重建实例才生效")
    assert "_pacing" in seg, "热重载里没有找到对采集器私有实例的引用"


# ---------------------------------------------------------------------------
# 4. 边界：启动级键不在热链路里（写下来，免得后来者「顺手补全」）
# ---------------------------------------------------------------------------
def test_reload_config_documents_the_startup_only_boundary():
    """端口/路径/内核这几类仍要重启：注释与界面必须说同一件事。

    这条是**反向**门禁：如果有人把「全部配置都热生效」写进 reload_config 的
    说明里，用户就会以为改端口也不用重启，然后遇到「保存了但页面还在旧端口」
    ——那又是一次「配了不生效」。
    """
    seg = _reload_seg()
    assert "启动级" in seg, "reload_config 没写清哪些键要重启就热生效"
    assert "重启" in seg


# ---- merged from tests/test_r1063_risk_params_equivalent.py ----

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


# ---- merged from tests/test_r1063_scoped_reads_all.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCOPES = {"channel", "dimension", "path"}

# 结构上不是「按渠道取一个值」的参数（键/元素本身就是渠道），不算缺口
STRUCTURAL = {
    "cadence.per_plat": "map：键就是渠道（crawler.cadence: {qunar: 20}）",
    "proxy_route.map": "map：键就是渠道（plat → 代理）",
    "proxy_route.global": "单个全局出口；按渠道不同不是它的语义",
    "warmup.platforms": "list：元素就是渠道名（哪几家要预热）",
}

# 已知还没接作用域求值的参数：**减少一条就删一行**。
# r1063 T62：最后 5 条（health_penalty 的阈值/倍数/最小样本）也接上了 —— 现在是空的。
# 空表是有意义的状态：**所有声明了渠道级作用域的参数，都真的按作用域求值**。
KNOWN_GAPS = {}


def _scoped_reads():
    """返回 `{pid: (读点文件, …)}`：真按作用域求值的参数。"""
    ctx = sc._Ctx()
    out = {}
    for s in sc.STRATEGIES:
        if not (set(s.scope) & SCOPES):
            continue
        for p in s.params:
            via = ctx.read_by_switch(p.pid) or ctx.read_by_param(p.pid)
            if via:
                out[p.pid] = via
    return out


def test_every_channel_scoped_param_is_read_or_explicitly_accounted_for():
    got = _scoped_reads()
    missing = []
    for s in sc.STRATEGIES:
        if not (set(s.scope) & SCOPES):
            continue
        for p in s.params:
            if p.pid in got or p.pid in STRUCTURAL or p.pid in KNOWN_GAPS:
                continue
            missing.append("%s（%s）" % (p.pid, s.id))
    assert not missing, (
        "这些参数声明了渠道级作用域、却没有任何按作用域求值的读点"
        "（界面能按渠道改但不会生效）：\n  " + "\n  ".join(missing)
        + "\n修好一条，或加进 STRUCTURAL / KNOWN_GAPS 并写清原因。")


def test_ttl_and_near_window_are_scoped():
    """本轮修掉的四个必须留在 `_scoped(...)` 读法里。"""
    src = io.open(os.path.join(ROOT, "core", "pacing.py"),
                  encoding="utf-8").read()
    for pid in ("ttl_tier.fast", "ttl_tier.slow", "near_window.ratio",
                "near_window.days"):
        assert 'self._scoped("%s"' % pid in src, pid


def test_known_gaps_are_still_real_gaps():
    """清单不许过期还挂着：已经修好的参数要从中删掉。"""
    got = _scoped_reads()
    stale = [pid for pid in KNOWN_GAPS if pid in got]
    assert not stale, ("这些参数已经按作用域求值了，从 KNOWN_GAPS 删掉：%s"
                       % stale)


def test_structural_list_only_contains_maps_or_lists():
    by_id = {p.pid: p for s in sc.STRATEGIES for p in s.params}
    for pid in STRUCTURAL:
        assert pid in by_id, pid
        assert by_id[pid].kind in ("map", "list", "str"), (
            "%s 是 %s，不像结构上不需要作用域" % (pid, by_id[pid].kind))


# ---- merged from tests/test_r1063_snapshot_ui.py ----

SRC = webui_full_src()


def _fn(name):
    i = SRC.index("function %s(" % name)
    j = SRC.index("\nfunction ", i + 10)
    return SRC[i:j]


def test_toolbar_has_both_buttons_and_no_new_visual():
    assert "function stratSnapHTML(){" in SRC
    seg = _fn("stratSnapHTML")
    assert "导出配置" in seg and "导入配置" in seg
    assert 'class="btn2"' in seg            # 复用既有按钮尺寸，不新起视觉
    assert 'type="file"' in seg


def test_export_uses_the_readonly_endpoint_and_downloads():
    seg = _fn("stratExportSnap")
    assert "/api/strategy/snapshot" in seg
    assert "Blob(" in seg and "download=" in seg


def test_import_writes_into_the_same_dirty_state_not_a_new_path():
    seg = _fn("stratImportSnap")
    # 只写 GLB（面板的脏状态）；**不出现任何 POST**，否则就是第三条写通路
    assert "GLB.strategy_values" in seg
    assert "GLB.strategy_overrides" in seg
    assert "fetch(" not in seg, "导入不该自己发写请求"
    assert "method:'POST'" not in seg


def test_import_previews_before_overwriting():
    seg = _fn("stratImportSnap")
    assert "confirm(" in seg, "没有差异预览就直接覆盖了"
    assert "→" in seg, "预览里要看到 before→after"


def test_import_refuses_unknown_pid_in_the_preview():
    seg = _fn("stratImportSnap")
    assert "未识别" in seg
    assert "点「保存配置」" in SRC or "保存配置" in seg


def test_toolbar_is_mounted_in_the_panel():
    assert "h+=stratSnapHTML();" in SRC


# ---- merged from tests/test_r1063_ttl_scoped.py ----

BASE = {"schedule": {"fast_ttl_min": 15, "slow_ttl_min": 120},
        "crawler": {"health_ok_ratio": 0.85, "health_min_samples": 5}}


@pytest.fixture(autouse=True)
def _clean():
    sp.invalidate()
    yield
    sp.invalidate()


def _pacing():
    # `clock` 必须返回浮点（早先写成返回 list，age 算出来是垃圾）
    return Pacing(dict(BASE), clock=lambda: NOW[0])


NOW = [1_800_000_000.0]


def _seed_last(p, plat, minutes_ago, key=("a", "b", "2026-12-01")):
    p._last[(plat,) + key] = (NOW[0] - minutes_ago * 60, 1000.0)


def test_channel_override_changes_the_tier_for_that_channel_only():
    sp.set_config({"schedule": {"fast_ttl_min": 15, "slow_ttl_min": 120},
                   "crawler": {"health_ok_ratio": 0.85,
                               "health_min_samples": 5,
                               "strategy_overrides": {
                                   "fliggy": {"ttl_tier.fast": 5}}}})
    p = _pacing()
    # 10 分钟前刚采过：全局 15 分钟还新鲜；覆盖成 5 分钟的那家该重采了
    for plat in ("fliggy", "ctrip"):
        _seed_last(p, plat, 10)
    tier_f, _ = p.plan_query("fliggy", ("a", "b", "2026-12-01"),
                             days_ahead=60)
    tier_c, _ = p.plan_query("ctrip", ("a", "b", "2026-12-01"),
                             days_ahead=60)
    assert tier_f == "fast", tier_f
    assert tier_c != "fast", tier_c


def test_no_override_keeps_the_global_ttl():
    """没配过覆盖时行为**不变**（参数层只是默认来源）。"""
    sp.set_config({"schedule": {"fast_ttl_min": 15, "slow_ttl_min": 120},
                   "crawler": {"health_ok_ratio": 0.85,
                               "health_min_samples": 5}})
    p = _pacing()
    _seed_last(p, "fliggy", 10)
    tier, _ = p.plan_query("fliggy", ("a", "b", "2026-12-01"), days_ahead=60)
    assert tier != "fast", tier


def test_scoped_reads_reach_path_scope_too():
    sp.set_config({"schedule": {"fast_ttl_min": 15, "slow_ttl_min": 120},
                   "crawler": {"strategy_overrides": {
                       "ctrip/intl/H5/API": {"ttl_tier.fast": 6}}}})
    p = _pacing()
    # 声明下限是 5，所以覆盖值取 6（4 会被夹到 5）
    assert p._scoped("ttl_tier.fast", "ctrip", "intl", "H5/API", 15) == 6
    assert p._scoped("ttl_tier.fast", "ctrip", "intl", "PC", 15) == 15
    assert p._scoped("ttl_tier.fast", "ctrip", "", "", 15) == 15


def test_near_days_override_is_scoped():
    sp.set_config({"schedule": {"fast_ttl_min": 15, "slow_ttl_min": 120},
                   "crawler": {"strategy_overrides": {
                       "qunar": {"near_window.days": 30}}}})
    p = _pacing()
    assert p._scoped("near_window.days", "qunar", "", "", 3) == 30
    assert p._scoped("near_window.days", "ctrip", "", "", 3) == 3


def test_scoped_helper_never_raises():
    """参数层炸了也不能把"排期"搞挂——回落全局值。"""
    p = _pacing()
    assert p._scoped("不存在的.pid", "fliggy", "", "", 7) == 7


def test_no_leftover_bare_ttl_reads():
    """门禁：TTL/近窗的三个值必须经 `_scoped`（否则渠道覆盖又会失效）。"""
    import io
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = io.open(os.path.join(root, "core", "pacing.py"),
                  encoding="utf-8").read()
    for pid in ("ttl_tier.fast", "ttl_tier.slow", "near_window.ratio"):
        assert 'self._scoped("%s"' % pid in src, pid
