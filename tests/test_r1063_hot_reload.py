# -*- coding: utf-8 -*-
r"""r1063 T14：热链路收口——改一份配置，**下一次决策**就用新值（不重启）。

为什么这个门禁必须存在
----------------------
`core/strategy_params.py` 是**唯一求值入口**，可它自己不会去读配置文件：
必须有人把 cfg 喂进 `set_config()`。T14 之前全仓没有一个生产读点调它，于是
「界面上改了值 → 保存 → 落进 config.yaml」这条链走到最后一步就断了：
`resolve()` 照旧返回目录默认值，界面上的「生效值/来源」恒为 `default`。
这正是本项目定义为**头号缺陷**的「配了不生效」，所以这里用**行为**钉住，
而不是「代码里提过这个词」。

四条判据（每条各钉一件事）
--------------------------
1. `reload_config()` 真的喂提供者——它是 web 保存后的**唯一**热重载出口；
2. **启动时也喂一次**，且发生在 `make_sweep_job(...)` 之前：首次决策就该
   看得见配置，而不是「首轮按默认、次轮才对」；
3. 同一个 `PolicyEngine` 对象，换 cfg 再 `decide()` 就拿到新数字
   （`set_config()` 只换 cfg、不重建对象）；
4. 同一个 `Pacing` 对象，换 cfg 再 `gate_path()` 就按新速率/新开关判。

**本文件不替启动级键作证**：端口 / db 路径 / 浏览器内核这类改动仍要重启
（界面已经写明「需重启」），`reload_config()` 的注释里也写死了这条边界。
把它们也说成热生效，就是在制造下一条「配了不生效」。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r1063_hot_reload.py -q
"""
import io
import os

import pytest

from core import strategy_params as sp

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
