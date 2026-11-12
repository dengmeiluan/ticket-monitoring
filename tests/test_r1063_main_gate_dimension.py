# -*- coding: utf-8 -*-
"""r1063 T10：`main.py` 的闸门接**维度/链路**，且「停用通路不连坐」。

三条判据，各自钉一件事（任何一条变红都意味着一个已知的连坐/静默形态）：

1. **停用通路不连坐**：链路闸门拒掉一条通路时记的是 `paced`——语义是
   「我方主动不发请求」。它一旦被当成失败证据递进 `Pacing.observe()`，
   一条被策略停用的通路就能把**整家渠道**熔断（「停一条路 = 停一家渠道」）。
   所以 `main.py` 递证据前必须先把 `paced` 剔掉，且这件事不许依赖
   `paced` 的说明文案碰巧不含「验证码/429」这类归因词。
2. **闸门接维度**：`_timed_fetch` 必须带 `dim`（默认 `detail`），且真的
   送到 `Pacing.gate_path()`；`渠道/维度` 层的停用要生效，而且只停那一个
   维度——同一渠道的别的维度照常。
3. **user_data 只有一份口径**：`main.py` 注给采集器的根目录，与
   `webui._policy_engine()` 解析出来的必须是**同一个目录**。否则界面写下
   的 `strategy_halt.json` 落在一个没有任何采集器读的目录里——界面报
   「已停手」而采集照跑（T6 Critical 往深一层就是这个形态）。

为什么第 3 条不是「再抄一份路径」：`config.yaml` 出厂值是字面量
`user_data_dir: user_data`，`core.yield_stats.user_data_root()` 明确把
「显式传默认值」等同于「没配」（于是 `TM_USER_DATA_DIR` 可以集中重定向），
而 `main.py` 原来直接 `_anchored("user_data")` 锚成仓库里的绝对路径并注进
采集器——两边各自算一遍，必然在对的输入上算出两个目录。

运行（必须带 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，否则插件加载超时）：

    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
      tests/test_r1063_main_gate_dimension.py -q
"""
import ast
import io
import logging
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

MAIN_PATH = os.path.join(ROOT, "main.py")
MAIN = io.open(MAIN_PATH, encoding="utf-8").read()


@pytest.fixture(autouse=True)
def _clean_params():
    """`strategy_params` 是模块级单例：本文件装过覆盖必须还原。"""
    from core import strategy_params as sp
    sp.invalidate()
    yield
    sp.invalidate()


def _pacing():
    from core.pacing import Pacing
    return Pacing({"crawler": {"rate": {"min_gap_s": 0, "per_minute": 0}}})


# ---------------------------------------------------------------------------
# 0. `observe()` 调用点判据（按调用点逐个追来源，不数关键字）
# ---------------------------------------------------------------------------
def _observe_sites():
    """`main.py` 里所有 `*.observe(...)` 调用点（AST，不看文本）。"""
    out = []
    for node in ast.walk(ast.parse(MAIN)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "observe":
            out.append(node)
    return out


def _enclosing_fn(call):
    """包住这个调用的**最内层**函数（就近取赋值需要一个作用域边界）。"""
    best = None
    for node in ast.walk(ast.parse(MAIN)):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.lineno <= call.lineno <= (node.end_lineno or node.lineno):
            if best is None or node.lineno > best.lineno:
                best = node
    return best


def _assigns_in(fn):
    """函数体里的简单赋值 `名字 = 表达式`（按行号；嵌套函数不算）。"""
    out = []
    if fn is None:
        return out
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    out.append((tgt.id, node.lineno, node.value))
    return out


def _traces_to(expr, lineno, assigns, fname, depth=2):
    """`expr`（或它引用的**最近一份**赋值）必须由 `fname(...)` 产出。

    为什么顺着赋值往上追而不是只看这一行：`main.py` 两处入口的写法不同，
    主扫描处把状态列表就地写成 `[x.get("status") for x in _bad]`（`_bad`
    是上一行的筛选结果），验证窗处先落 `_st` 再调用。判据要能同时覆盖
    两种写法，又必须在**任何一处改回旧写法**时变红。
    """
    for node in ast.walk(expr):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == fname:
            return True
    if depth <= 0:
        return False
    # 推导式里被绑定的名字（`for x in ...` 的 x）不是「外部来源」，跳过
    bound = set()
    for node in ast.walk(expr):
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp,
                             ast.DictComp)):
            for gen in node.generators:
                for t in ast.walk(gen.target):
                    if isinstance(t, ast.Name):
                        bound.add(t.id)
    for node in ast.walk(expr):
        if not isinstance(node, ast.Name) or not isinstance(node.ctx,
                                                            ast.Load):
            continue
        if node.id in bound:
            continue
        prev = [(ln, val) for (n, ln, val) in assigns
                if n == node.id and ln < lineno]
        if not prev:
            continue
        _ln, _val = max(prev, key=lambda x: x[0])
        if _traces_to(_val, _ln, assigns, fname, depth - 1):
            return True
    return False


def _site_sources(call):
    """一个 `observe()` 调用点的「证据来源 / 文案来源」是否都经过筛选器。"""
    assigns = _assigns_in(_enclosing_fn(call))
    statuses = call.args[1] if len(call.args) > 1 else None
    note = call.args[2] if len(call.args) > 2 else None
    return (
        statuses is not None
        and _traces_to(statuses, call.lineno, assigns, "_fail_evidence"),
        note is not None
        and _traces_to(note, call.lineno, assigns, "_fail_note"),
    )


def test_every_observe_site_feeds_screened_evidence():
    """**每一处** `observe()` 入口都得递筛选后的证据与同源的文案。

    为什么不能数 `_fail_evidence(` 出现次数：它在 `main.py` 里出现 6 次
    （定义、docstring、函数体、验证窗重新熔断、主扫描注释与赋值），
    `MAIN.count("_fail_evidence(") >= 4` 这类断言**在两处调用点全部改回旧
    写法时仍然是绿的**——判据自己失效，正是本文件头号要防的形态。
    所以按调用点逐个追：状态参数与 note 参数，顺着「最近的同名赋值」往上
    溯源，必须落到 `_fail_evidence(` / `_fail_note(`；落到
    `c.paths` / `paths` 这类原始集合上就红。
    """
    sites = _observe_sites()
    assert len(sites) >= 2, \
        "observe() 调用点只剩 %d 处，本判据失去锚点" % len(sites)
    for call in sites:
        ev_ok, note_ok = _site_sources(call)
        assert ev_ok, (
            "第 %d 行的 observe() 直接拿未筛选的状态当证据：`paced`（我方主动"
            "不发请求）会被当成对方拒绝，一条被停用的通路就能熔断整家渠道"
            % call.lineno)
        assert note_ok, (
            "第 %d 行的 observe() 的 note 没走 `_fail_note()`：`paced` 的 why "
            "会进 `classify_failure()` 的关键词兜底" % call.lineno)


# ---------------------------------------------------------------------------
# 1. 停用通路不连坐
# ---------------------------------------------------------------------------
def test_observe_never_receives_paced_evidence():
    """brief 原文的锚点：`pac.observe()` 调用处必须点明 paced 已被剔除。

    这一条只守**接线**（真正的契约在下一条行为用例）：`paced` 出现在
    observe 的参数区一句话里，说明作者在递证据时想过这件事，而不是靠
    「今天 paced 的文案里恰好没有归因词」蒙混过去。
    """
    seg = MAIN[MAIN.index("_kind, _cd = pac.observe("):][:600]
    assert "paced" in seg, "observe 前没过滤 paced 证据"


def test_paced_evidence_never_trips_the_channel_breaker():
    """一条被策略停用的通路（记 `paced`）不许把整家渠道熔断。

    行为口径：走 `main.py` 自己的证据筛选器，再喂给**真的**
    `Pacing.observe()`，断言既不认成拒绝、渠道也不进冷却。

    这里故意让 `paced` 的说明里带上「验证码 / 429」这类归因词：
    `classify_failure()` 会从 note 文本兜底归类（`_CAPTCHA_MARKS` /
    `_IP_CODE_RE`）。真实世界完全可能这么写——闸门未来换个文案、或渠道
    把上次被拦的原因抄进 `why`。**剔除 paced 是不依赖文案的防线**，
    「今天文案里没有关键词」不是防线。
    """
    import main

    paths = [{
        "path": "PC", "status": "paced", "rows": 0, "date": "2026-12-01",
        "detail": "链路被策略停用：ctrip/intl/PC——同渠道其它链路照常"
                  "（上一次拦截原因：验证码 / 429）",
    }]
    bad = main._fail_evidence(paths)
    assert bad == [], "paced 被当成失败证据递给了 observe：%r" % (bad,)
    pac = _pacing()
    kind, cd = pac.observe(
        "ctrip", [x.get("status") for x in bad],
        main._fail_note(paths), retry_after=0)
    assert (kind, cd) == ("", 0), "停用通路触发了熔断：%r" % ((kind, cd),)
    assert pac.snapshot()["channels"]["ctrip"]["state"] == "ok"
    assert pac.snapshot()["channels"]["ctrip"]["strikes"] == 0


def test_verify_window_retrip_also_ignores_paced_evidence():
    """**第二处** `observe()` 入口：验证窗关闭后「未通过就重新熔断」。

    这条通路原来把 `c.paths` 的**全部**状态原样递上去（连 `ok`/`calendar`/
    `empty` 都不过滤），`note` 还只用旧三元组——一条 `paced` 的 `why` 会进
    note，被 `classify_failure()` 的关键词兜底归成「对方拒绝」。
    行为判据：用 `main.py` 自己的筛选器 + 说明串喂给真的 `Pacing.observe()`，
    断言既不认成拒绝、渠道也不进冷却。
    """
    import main

    paths = [{"path": "PC", "status": "paced",
              "detail": "链路被策略停用（上一次拦截原因：405 / 429 / 验证码）"},
             {"path": "H5", "status": "calendar", "detail": "日历出数"}]
    assert main._fail_note(paths) == "", "paced/calendar 的说明混进了 note"
    pac = _pacing()
    kind, cd = pac.observe(
        "ctrip", [x.get("status") for x in main._fail_evidence(paths)],
        main._fail_note(paths), retry_after=0)
    assert (kind, cd) == ("", 0)
    assert pac.snapshot()["channels"]["ctrip"]["state"] == "ok"
    # 两处入口都用同一个筛选器：这里按**调用点**核对（数 `_fail_evidence(`
    # 的出现次数证明不了什么——两处都改回旧写法时计数照样达标，见
    # `test_every_observe_site_feeds_screened_evidence`）
    retrip = [c for c in _observe_sites()
              if "pacing" in ast.unparse(c.func.value)]
    assert retrip, "验证窗那处 `rt[\"pacing\"].observe(...)` 不见了（失去锚点）"
    for call in retrip:
        ev_ok, note_ok = _site_sources(call)
        assert ev_ok and note_ok, (
            "第 %d 行（验证窗重新熔断）没走筛选器：状态=%r / note=%r"
            % ((call.lineno,) + (_site_sources(call),)))


def test_fail_evidence_normalises_status_before_comparing():
    """`"Paced"` / `" paced "` 这类写法不许静默变成「失败」。

    `path_note()` 只收 `PATH_STATUS` 的字面量，但 `main.py` 自己会往
    `c.paths` 里补行，渠道也可能直接追加。判错的表现正是本任务要挡的连坐，
    而且不报错——只有多熔断一家渠道。
    """
    import main

    got = main._fail_evidence([{"status": " Paced "}, {"status": "Paced"},
                               {"status": "OK"}, {"status": "blocked"}])
    assert [x["status"] for x in got] == ["blocked"], got


# ---------------------------------------------------------------------------
# 1b. 落地归因接链路（复核 2026-11-06 第 3 条）
# ---------------------------------------------------------------------------
def test_evidence_path_pins_the_single_path_and_blanks_on_mixed_evidence():
    """账行指向唯一一条通路才给 path；跨通路/没写 path 时只能报渠道级。"""
    import main

    assert main._evidence_path([{"path": "PC"}, {"path": "PC"}]) == "PC"
    assert main._evidence_path([{"path": "PC", "status": "blocked"}]) == "PC"
    # 跨多条链路：摊到其中一条头上会让另一条该停的照跑 → 渠道级结论
    assert main._evidence_path([{"path": "PC"}, {"path": "H5"}]) == ""
    assert main._evidence_path([{"status": "blocked"}]) == ""
    assert main._evidence_path([{"path": ""}, {"path": "  "}]) == ""
    assert main._evidence_path([]) == "" and main._evidence_path(None) == ""


def test_every_observe_site_passes_the_evidence_path():
    """**每一处** `observe()` 调用都得递 `path=`。

    不递的后果不是报错而是**静默空转**：`ChannelBreaker` 的链路级记账全在，
    但没有任何调用方写 `plat|链路` 键，`gate_path()` 的熔断腿只能看渠道键
    ——「PC 被风控」于是照样停掉整家（复核 2026-11-06 第 3 条）。
    """
    sites = _observe_sites()
    assert len(sites) >= 2, "observe() 调用点只剩 %d 处" % len(sites)
    for call in sites:
        kws = {k.arg for k in call.keywords if k.arg}
        assert "path" in kws, (
            "第 %d 行的 observe() 没递 path：链路级熔断键永远不会被创建"
            % call.lineno)


def test_timed_fetch_hands_the_success_path_to_note_ok():
    """成功出数时也要把「是哪条链路成功的」递过去（否则会误清别的链路）。"""
    fn = _timed_fetch_node()
    hits = [n for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "note_ok"]
    assert hits, "`_timed_fetch` 里没有 note_ok 调用（判据失去锚点）"
    for node in hits:
        kws = {k.arg for k in node.keywords if k.arg}
        assert "path" in kws, (
            "第 %d 行的 note_ok() 没递 path：一次 H5 成功会把 PC 的实时冷却"
            "顺手免掉" % node.lineno)


def test_fail_evidence_keeps_real_failures_and_drops_non_failures():
    """筛选器只做两件事：保留真失败、剔除「不算对方拒绝」的三类 + paced。

    `ok` / `calendar` 是成功面，`empty` 是真无票（重试也不会变好），
    `paced` 是我方主动不发——四类都不许进熔断归因。
    """
    import main

    paths = [{"status": s} for s in
             ("ok", "calendar", "empty", "paced", "blocked",
              "login", "timeout", "soft_reject", "parse_error")]
    got = [x["status"] for x in main._fail_evidence(paths)]
    assert got == ["blocked", "login", "timeout", "soft_reject",
                   "parse_error"], got
    # 真失败照旧能熔断（负控：别把筛选器写成「一律清空」）
    pac = _pacing()
    kind, _cd = pac.observe("ctrip", [x["status"] for x in
                                      main._fail_evidence(
                                          [{"status": "blocked"}])],
                            "滑块")
    assert kind == "captcha"


# ---------------------------------------------------------------------------
# 2. 闸门接维度
# ---------------------------------------------------------------------------
def _timed_fetch_node():
    tree = ast.parse(MAIN)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_timed_fetch":
            return node
    raise AssertionError("main.py 里找不到 `_timed_fetch`")


def test_timed_fetch_takes_a_dimension_defaulting_to_detail():
    """brief 的接口：`_timed_fetch(c, fc_, tc_, d_, th_min=None, gen=None,
    chans=None, dim="detail")`——旧位置参数一个都不许动。"""
    fn = _timed_fetch_node()
    args = [a.arg for a in fn.args.args]
    assert args[:7] == ["c", "fc_", "tc_", "d_", "th_min", "gen",
                        "chans"], args
    assert "dim" in args, "`_timed_fetch` 没有 dim：渠道闸门接不上维度"
    defaults = dict(zip(args[len(args) - len(fn.args.defaults):],
                        fn.args.defaults))
    dflt = defaults.get("dim")
    assert isinstance(dflt, ast.Constant) and dflt.value == "detail", \
        "dim 的缺省必须是 detail（列表/明细是主路径），得到 %r" % (dflt,)


def test_every_timed_fetch_call_site_passes_a_dimension():
    """每个提交点都要给 dim——留空串等于悄悄把维度覆盖跳过。"""
    tree = ast.parse(MAIN)
    sites = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute)
                and node.func.attr == "submit"):
            continue
        if not node.args:
            continue
        head = node.args[0]
        if isinstance(head, ast.Name) and head.id == "_timed_fetch":
            sites.append(node)
    assert sites, "找不到 `_timed_fetch` 的提交点（判据失去锚点）"
    for site in sites:
        kw = {k.arg: k.value for k in site.keywords if k.arg}
        # submit(_timed_fetch, c, fc_, tc_, d_, th_min, gen, chans, dim)
        #  → 第 0 个是函数本身，dim 是第 9 个（下标 8）
        has_pos = len(site.args) >= 9
        assert has_pos or "dim" in kw, (
            "有个提交点没传 dim（第 %d 行）：维度闸门对它形同虚设"
            % (site.lineno,))
        expr = site.args[8] if has_pos else kw.get("dim")
        # 只有「真的无法得知维度」才允许空串，且必须留注释说明为什么。
        # 当前没有这种调用点，所以一律不许写字面量空串。
        assert not (isinstance(expr, ast.Constant) and expr.value == ""), \
            "第 %d 行给 _timed_fetch 传了空维度：把该调用点的理由写进注释" \
            % (site.lineno,)


def test_query_dimension_maps_return_dates_to_round_trip():
    """维度取值必须落在 `core.channels.DIMENSIONS` 词汇里。"""
    import main
    from core.channels import DIMENSIONS

    assert main._dim_of_query(None) == "detail"
    assert main._dim_of_query([]) == "detail"
    assert main._dim_of_query(["2026-12-01"]) == "round_trip"
    assert main._dim_of_query(["", "2026-12-01"]) == "round_trip"
    for v in (main._dim_of_query([]), main._dim_of_query(["2026-12-01"])):
        assert v in DIMENSIONS, "%r 不在维度词汇表里" % (v,)


def test_dimension_reaches_the_gate():
    """`_timed_fetch` 里必须真的把 `dim` 送进 `Pacing.gate_path()`。

    `plan_query` / `allow` 是**渠道级**的（键就是渠道），维度层
    （`渠道/维度`）只有 `gate_path(plat, dim, path)` 查得到；不把 dim 递
    过去，策略里写 `ctrip/calendar: path_fallback.enabled: false` 就永远
    不生效——「配了不生效」是本仓库列的头号缺陷。
    """
    fn = _timed_fetch_node()
    hits = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr == "gate_path":
            hits.append(node)
    assert hits, "`_timed_fetch` 没有调用 `gate_path`：维度闸门没接上"
    for node in hits:
        names = {a.id for a in node.args if isinstance(a, ast.Name)}
        kws = {k.arg for k in node.keywords if k.arg}
        assert "dim" in names or "dim" in kws, (
            "第 %d 行的 gate_path 没把 dim 递进去" % (node.lineno,))


def test_a_dimension_level_disable_only_stops_that_dimension():
    """`渠道/维度` 层停用：只停那个维度，同渠道别的维度照常。

    这是「停用通路不连坐」在**维度**上的同一句话——闸门现在由 main.py
    以 `dim` 调用，这条行为就是 main.py 拿到的语义。
    """
    from core import strategy_params as sp

    sp.set_config({"crawler": {"strategy_overrides": {
        "ctrip/calendar": {"path_fallback.enabled": False}}}})
    pac = _pacing()
    ok, _wait, why = pac.gate_path("ctrip", "calendar", "")
    assert ok is False and "停用" in why, why
    for other in ("detail", "round_trip", "low_fare"):
        ok2, _w2, _why2 = pac.gate_path("ctrip", other, "")
        assert ok2 is True, "停一个维度连坐了 %s" % other


# ---------------------------------------------------------------------------
# 3. user_data 只有一份口径
# ---------------------------------------------------------------------------
def _webui_base(cfg, plat="ctrip"):
    """`webui._policy_engine()` 解析出来的停手目录（与界面同一条代码路径）。

    生产启动时 `_State.boot_cfg` 就是那份配置的深拷贝（`start_web` 里），
    而停手目录走的是**运行期**口径（启动级设置）——所以这里同时给
    `cfg`/`boot_cfg` 同一份值，避免读到别的用例留下的进程级残留。
    """
    import webui

    prev_cfg = getattr(webui._State, "cfg", None)
    prev_boot = getattr(webui._State, "boot_cfg", None)
    webui._State.cfg = cfg
    webui._State.boot_cfg = cfg
    try:
        return webui._policy_engine(plat).base_dir
    finally:
        webui._State.cfg = prev_cfg
        webui._State.boot_cfg = prev_boot


def _crawler_base(injected_root, plat="ctrip"):
    """采集器侧的决策目录：`main.py` 注进去的那份 config 喂给同一个引擎。"""
    import main
    from core.policy import default_engine

    return default_engine({"user_data_dir": injected_root},
                          repo_root=main._REPO_ROOT,
                          profile=plat).base_dir


@pytest.mark.parametrize("crawler_section, follows_env", [
    ({"user_data_dir": "user_data"}, True),   # 出厂字面量（本次缺陷的那条分支）
    ({}, True),                                # 压根没配
    ({"user_data_dir": "user_data/"}, True),   # 同义写法（normpath 后仍是默认值）
    ({"user_data_dir": "./user_data"}, True),
    ({"user_data_dir": "ud_custom"}, False),   # 真的换了相对目录 → 配置优先
])
def test_main_and_webui_resolve_the_same_user_data_root(
        tmp_path, monkeypatch, crawler_section, follows_env):
    """两边算出来的必须是**同一个目录**，否则停手落到没人读的地方。

    光断言「两者相等」不够：两侧同时退化成「都不理环境变量」也能相等。
    所以 `follows_env` 为真的输入下，还要断言结果**真的落在
    `TM_USER_DATA_DIR` 里**（本次缺陷正是「环境变量被绕过」）。
    """
    env_dir = tmp_path / "ud_env"
    env_dir.mkdir()
    monkeypatch.setenv("TM_USER_DATA_DIR", str(env_dir))

    import main
    injected = main._session_user_data(crawler_section)
    got_crawler = _crawler_base(injected)
    got_web = _webui_base({"crawler": dict(crawler_section)})
    assert got_crawler == got_web, (
        "main 注入 %r → 采集器读 %s，而 webui 解析成 %s"
        % (injected, got_crawler, got_web))
    if follows_env:
        assert os.path.abspath(injected).startswith(
            os.path.abspath(str(env_dir))), (
            "环境变量被绕过了：注入 %r 不在 %s 之下" % (injected, env_dir))
        assert os.path.abspath(got_web).startswith(
            os.path.abspath(str(env_dir))), got_web
    else:
        assert not os.path.abspath(injected).startswith(
            os.path.abspath(str(env_dir))), (
            "显式换过的目录被环境变量顶掉了：%r" % (injected,))


def test_webui_reads_the_runtime_dir_under_env_redirect(tmp_path, monkeypatch):
    """界面侧的**其它**根目录判据也必须认环境变量（复核 Important 2）。

    快照探测、打开资料目录、生效 crawler 配置——原来各自
    `_anchored(... or "user_data")` 算一遍，装了 `TM_USER_DATA_DIR` 就去看
    仓库 `user_data/`，而采集器把快照写在 env 目录里 → 界面说「未保存」、
    实际有（T6 Critical 的反方向）。
    """
    env_dir = tmp_path / "ud_env"
    snap = env_dir / "android_snapshots"
    snap.mkdir(parents=True)
    (snap / "app_ctrip.tar.gz").write_bytes(b"fake-tar")
    monkeypatch.setenv("TM_USER_DATA_DIR", str(env_dir))

    import webui

    monkeypatch.setattr(webui._State, "boot_cfg", None, raising=False)
    monkeypatch.setattr(webui._State, "cfg",
                        {"crawler": {"user_data_dir": "user_data"}}, raising=False)

    eff = webui._effective_crawler_config()["user_data_dir"]
    assert os.path.abspath(eff) == os.path.abspath(str(env_dir)), eff
    # 打开资料目录：必须是实际生效的那个
    opened = webui._OPEN_KEYS["ud"]({"crawler": {"user_data_dir": "user_data"}})
    assert os.path.abspath(opened) == os.path.abspath(str(env_dir)), opened
    # App 登录快照探测：采集器写在 env 目录里 → 界面必须看得到「已保存」
    info = webui._app_login_ctx()["snapshot_info"]("app_ctrip")
    assert info.get("exists") is True, info


def test_both_sides_resolve_through_the_one_shared_helper():
    """「一份口径」不是「两边算出一样」——是**两边调同一个函数**。

    路径算两次能碰巧相等，语义判两次永远会分叉：原来界面侧自己判「是不是
    出厂字面量 `user_data`」（是 → 当没配、放行环境变量），采集侧自己判
    「有没有这个键」（有 → 当显式目录、就地锚绝对）。两边各自加一条规则，
    第 N 次改动必然再分一次。所以这里钉住：两侧的根目录都来自
    `core.yield_stats.user_data_root()`，谁也不另起一套判据。
    """
    assert "user_data_root(" in MAIN, "main.py 没走唯一口径"
    seg = MAIN[MAIN.index("def _session_user_data("):][:1500]
    assert "user_data_root(" in seg, \
        "`_session_user_data()` 没走唯一口径（又自己判了一遍配置语义）"

    web = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    i = web.index("def _ud_root(")
    assert "user_data_root(" in web[i:i + 2000], \
        "webui 的唯一口径函数没走 `core.yield_stats.user_data_root()`"
    # 全文件扫一遍：不许再出现「把配置字面值自己锚成路径」的判据
    old = re.compile(
        r"_anchored\((?:[^()]|\([^()]*\)){0,400}?user_data_dir", re.S)
    left = [m.group(0)[:80].replace("\n", " ") for m in old.finditer(web)]
    assert not left, "webui 里还有自己算 user_data 根的判据：%r" % (left,)
    assert '!= "user_data"' not in web[i:i + 4000] and ".pop(" not in \
        web[web.index("def _policy_engine("):][:3000], (
        "`_policy_engine` 又在拿字面量 `user_data` 当哨兵自己判 / pop 掉让"
        "下游去猜——那个判据与唯一口径的分叉就是本次缺陷")
    # 每个使用者都必须走它（少一处就是一个方向相反的分叉）
    for fn in ("def _policy_engine(", "def _snapshot_info(", "def _snapshot(",
               "def _effective_crawler_config("):
        j = web.index(fn)
        assert "_ud_root" in web[j:j + 2500], "%s 没走唯一口径" % fn
    assert '"ud": lambda c: _ud_root(c)' in web, \
        "「打开资料目录」还在用配置字面值"
    assert "_ud_root_runtime()" in web, "运行期根目录没走唯一口径"


def test_explicit_absolute_user_data_dir_is_honoured_by_both(
        tmp_path, monkeypatch):
    """显式绝对路径（生产的第二形态）：config 优先于环境变量，两边都听。"""
    abs_dir = tmp_path / "ud_abs"
    abs_dir.mkdir()
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path / "ud_env"))

    import main
    injected = main._session_user_data({"user_data_dir": str(abs_dir)})
    assert os.path.normcase(os.path.abspath(injected)) == \
        os.path.normcase(os.path.abspath(str(abs_dir)))
    assert _crawler_base(injected) == _webui_base(
        {"crawler": {"user_data_dir": str(abs_dir)}})


def test_without_env_both_sides_fall_back_to_the_repo_user_data(
        tmp_path, monkeypatch):
    """没有环境变量（生产常态）：两边都锚到仓库 `user_data/`。"""
    monkeypatch.delenv("TM_USER_DATA_DIR", raising=False)

    import main
    injected = main._session_user_data({"user_data_dir": "user_data"})
    assert os.path.normcase(os.path.abspath(injected)) == \
        os.path.normcase(os.path.abspath(os.path.join(ROOT, "user_data")))
    assert _crawler_base(injected) == _webui_base(
        {"crawler": {"user_data_dir": "user_data"}})


def test_halt_written_by_the_console_is_read_by_the_crawler(
        tmp_path, monkeypatch):
    """端到端：这是 T6 Critical 的同一句话，只是再往深一层。

    出厂字面量 + `TM_USER_DATA_DIR`：界面写下的停手，采集器**必须**读到
    （它读的是 `main.py` 注进去的那份配置）。用真实 `REGISTRY` 实例对账，
    桩自证会绕过这一层。
    """
    env_dir = tmp_path / "ud_env"
    monkeypatch.setenv("TM_USER_DATA_DIR", str(env_dir))
    from core.policy import set_halt
    from crawlers import REGISTRY

    import main

    cfg = {"crawler": {"user_data_dir": "user_data"},
           "output": {"db_path": str(tmp_path / "t.db")}}
    injected = main._session_user_data(cfg["crawler"])
    inst = REGISTRY["ctrip"]({"user_data_dir": injected},
                             logging.getLogger("r1063t10"))
    halt_dir = _webui_base(cfg)
    # 停手目录必须真的落在环境变量那个根里（不只是「两边相等」）
    assert os.path.abspath(halt_dir).startswith(os.path.abspath(str(env_dir))), \
        "停手目录没跟着 TM_USER_DATA_DIR 走：%s" % (halt_dir,)
    assert set_halt(halt_dir, "ctrip", 5, "人工核查") is not False
    assert os.path.isfile(os.path.join(halt_dir, "strategy_halt.json"))
    pol = inst._policy().decide(inst.name, two_way=True)
    assert pol.allow is False, (
        "界面在 %s 写了停手，采集器却照跑（它读的是 %s）"
        % (halt_dir, injected))


# ---------------------------------------------------------------------------
# 4. 配置页的「第三套口径」：展示路径 / 按钮 / 徽标 / 迁移预案同一个目录
# ---------------------------------------------------------------------------
def test_storage_view_and_open_button_describe_the_same_ud_dir(
        tmp_path, monkeypatch):
    """一张卡上的四样东西必须指同一个目录（复核第三轮的那条链）。

    链路：`/api/config` 的 `storage.ud.abs` → 前端 `glAbs()` 优先用它画
    「→ 绝对路径」那一行；「打开资料目录」按钮走 `_OPEN_KEYS["ud"]` →
    `_ud_root`。前者原来自按配置字面值锚定，后者认环境变量——装了
    `TM_USER_DATA_DIR` 时，同一张卡上的两行说的是两个目录，用户点按钮
    打开的是上面那行没写的那个文件夹。
    """
    env_dir = tmp_path / "ud_env"
    env_dir.mkdir()
    monkeypatch.setenv("TM_USER_DATA_DIR", str(env_dir))

    import webui

    cfg = {"crawler": {"user_data_dir": "user_data"}}
    m = webui._storage_view(cfg)["ud"]
    opened = webui._OPEN_KEYS["ud"](cfg)
    # ① 展示的绝对路径 == ② 按钮目标 == 实际生效目录
    assert os.path.abspath(m["abs"]) == os.path.abspath(str(env_dir)), m["abs"]
    assert os.path.abspath(opened) == os.path.abspath(m["abs"]), opened
    # ③ 存在性徽标按实际生效目录判断（env 目录刚建好 → 目录存在）
    assert m["exists"] is True and m["is_dir"] is True, m
    # ④ 配置字面值不许被丢掉：字面值 + 它单靠自己指向的目录都要下发，
    #    界面才能并列显示「配置：user_data · 实际生效：<env>」
    assert m["configured"] == "user_data", m
    assert os.path.abspath(m["configured_abs"]) == os.path.abspath(
        os.path.join(webui._ROOT, "user_data")), m["configured_abs"]
    assert m["diverged"] is True and m["source"] == "env", m
    # ⑤ 迁移预案的**目标**也走同一口径：预览「user_data」= 现状，无需迁移
    assert webui._path_meta("ud", "user_data", cfg)["abs"] == m["abs"]
    # 真的换一个目录时，目标是那个目录（字面值优先于环境变量）
    other = webui._path_meta("ud", "ud_new", cfg)
    assert os.path.abspath(other["abs"]) == os.path.abspath(
        os.path.join(webui._ROOT, "ud_new")), other["abs"]
    assert other["diverged"] is False and other["source"] == "config", other


def test_startup_vals_resolve_ud_through_the_one_helper(tmp_path, monkeypatch):
    """重启差量 / 迁移预览也认环境变量（原来按字面值比，会说「没变」）。

    `db`/`log` 是启动级键、语义不同（配置改了重启才生效、迁移要给目标），
    仍按字面值锚定——这条用例顺带把「别顺手一起改」钉住。
    """
    env_dir = tmp_path / "ud_env"
    env_dir.mkdir()
    monkeypatch.setenv("TM_USER_DATA_DIR", str(env_dir))

    import webui

    v = webui._startup_vals({"crawler": {"user_data_dir": "user_data"}})
    assert os.path.abspath(v["user_data_dir"]) == os.path.abspath(
        str(env_dir)), v["user_data_dir"]
    assert os.path.abspath(v["db_path"]) == os.path.abspath(
        os.path.join(webui._ROOT, "data", "prices.db")), v["db_path"]


def test_config_page_renders_configured_and_effective_side_by_side():
    """前端必须把「配置 / 实际生效」并列画出来（不只下发字段）。

    只有 `_m.abs` 一处展示时，装了 `TM_USER_DATA_DIR` 的机器上那行写的是
    env 目录，而输入框里明明是 `user_data`——用户看到的是两个互相打脸的
    数字，却没有任何一句话解释。所以钉住渲染分支里同时出现这两个词。
    """
    web = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    seg = web[web.index("function glAbs("):][:1200]
    assert "实际生效" in seg and "_m.configured" in seg, \
        "路径行没把「配置字面值」和「实际生效目录」并列显示"
    assert "→ 绝对路径：" in web, "r341 的绝对路径行被删了"
    pre = web[web.index("async function pathPreview("):][:2500]
    assert "实际生效" in pre and "current_abs" in pre, \
        "迁移预览没说清「当前生效」与「目标」，也没并列配置字面值"


# ---------------------------------------------------------------------------
# 5. `/api/round/abort` 不再靠闭包猜 rt
# ---------------------------------------------------------------------------
def test_main_hands_the_runtime_dict_to_webui_state():
    """`_State.rt = rt` 这一句是「中断本轮」的唯一正经接线。

    main.py 无法在单测里跑（`main()` 要读配置/开线程/起浏览器），所以这
    一条只能是**接线钉**：断言那一句在、且就在控制台挂接那一段里，而不是
    靠 webui 的闭包兜底猜出来。
    """
    assert "_WS.rt = rt" in MAIN, \
        "main.py 没把 rt 挂到 webui._State 上，/api/round/abort 只能靠闭包猜"
    i = MAIN.index("_WS.rt = rt")
    around = MAIN[max(0, i - 800):i + 400]
    assert "from webui import _State as _WS" in around, \
        "`_WS.rt = rt` 不在控制台挂接那一段里（挂到了别处/挂早挂晚）"
    assert "_WS.pacing" in around, "挂接段落不再是控制台那一段"
    # webui 侧必须仍然认这一步（`_runtime_rt()` 优先 `_State.rt`）
    web = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert re.search(r"def _runtime_rt\(", web), "webui 的运行时探针没了"
    seg = web[web.index("def _runtime_rt("):][:900]
    assert "_State.rt" in seg, "webui 不再优先读 `_State.rt`"
