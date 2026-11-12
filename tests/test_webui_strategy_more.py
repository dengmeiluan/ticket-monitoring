# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_strategy_axes15.py
- tests/test_r1063_strategy_params.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import dataclasses
import pytest

from core import strategy_contract as sc, strategy_params as sp


# ---- merged from tests/test_r1063_strategy_axes15.py ----

def _one(sid, **kw):
    """取目录里的一条策略，按需替换字段（负控用）。"""
    s = [x for x in sc.STRATEGIES if x.id == sid][0]
    return dataclasses.replace(s, **kw) if kw else s


def _ctx_with(webui=None, storage=None):
    """造一个只读上下文：`webui` / `storage` 用合成源码，不真去读 4.4MB。"""
    ctx = sc._Ctx()
    if webui is not None:
        ctx._webui = webui
    if storage is not None:
        ctx._storage = storage
    return ctx


def _axis_rows(item, axis, **audit_kw):
    """只取某条策略×某条轴的格（item 可以是 sid 字符串）。"""
    if isinstance(item, str):
        item = _one(item)
    kw = {"strategies": (item,), "plats": ("*",)}
    kw.update(audit_kw)
    return [r for r in sc.audit(**kw) if r.axis == axis]


# ---------------------------------------------------------------- 正向外框

def test_axes_are_fifteen_and_include_the_objective_extension():
    assert len(sc.AXES) == 15
    for a in ("visualizable", "adjustable", "clear", "intent", "stats"):
        assert a in sc.AXIS_IDS, "缺轴 " + a
    # 原十轴一个都不许掉（`semantics` 语义清晰保留）
    for a in ("configurable", "observable", "intervenable", "toggleable",
              "interruptible", "distinguishable", "identifiable", "advisable",
              "independent", "semantics"):
        assert a in sc.AXIS_IDS, "丢了原轴 " + a
    # 中文名唯一（表头按中文名出列）
    assert len(set(sc.AXIS_CN.values())) == 15


def test_every_strategy_has_a_short_clear_label():
    """可清晰：≤20 字的中文短句，不许露裸 id。"""
    for s in sc.STRATEGIES:
        assert 0 < len(s.label) <= 20, (s.id, s.label)
        assert s.id not in s.label, (s.id, s.label)
        assert all("\u4e00" <= ch <= "\u9fff" or ch in "·（）0123456789/"
                   for ch in s.label), (s.id, s.label)


def test_every_strategy_states_intent_and_effect():
    for s in sc.STRATEGIES:
        assert s.intent and s.effect, s.id
        assert len(s.intent) <= 40 and len(s.effect) <= 40, s.id


def test_stats_axis_is_evaluated_not_dropped():
    rows = [r for r in sc.audit() if r.axis == "stats"]
    assert rows, "stats 轴没求值"
    assert not [r for r in rows if r.state == "y" and not r.note.strip()], \
        "y 必须有可数的口径说明"


# ---------------------------------------------------------------- 可清晰（负控）

def test_clear_axis_reports_n_for_bad_labels():
    good = _one("ttl_tier")
    assert [r.state for r in _axis_rows(good, "clear")] == [sc.Y]

    cases = {
        "空标签": dataclasses.replace(good, label=""),
        "标签里露裸 id": dataclasses.replace(good, label="ttl_tier 分层"),
        "标签带英文": dataclasses.replace(good, label="TTL 分层抓取"),
        "超过 20 字": dataclasses.replace(
            good, label="快慢两档抓取间隔按健康度自动伸缩的一整句话"),
        "照抄中文名": dataclasses.replace(good, label=good.cn),
        "只有空白": dataclasses.replace(good, label="   "),
    }
    for why, s in cases.items():
        rows = _axis_rows(s, "clear")
        assert rows and all(r.state == sc.N for r in rows), (why, rows)
        assert all(r.note.strip() for r in rows), why


# ---------------------------------------------------------------- 可意图理解（负控）

def test_intent_axis_reports_n_for_missing_or_overlong_text():
    good = _one("block_window")
    assert [r.state for r in _axis_rows(good, "intent")] == [sc.Y]

    cases = {
        "缺 intent": dataclasses.replace(good, intent=""),
        "缺 effect": dataclasses.replace(good, effect=""),
        "intent 超 40 字": dataclasses.replace(good, intent="防" * 41),
        "effect 超 40 字": dataclasses.replace(good, effect="改" * 41),
    }
    for why, s in cases.items():
        rows = _axis_rows(s, "intent")
        assert rows and all(r.state == sc.N for r in rows), (why, rows)
        assert all(r.note.strip() for r in rows), why


# ---------------------------------------------------------------- 可可视化

def test_visualizable_axis_needs_a_renderer_that_reads_the_catalog():
    """渲染级证据：`data-strategy` 模板 + 目录驱动 + 每行带族。

    判据三件（`_ax_visualizable`）一个字符没改，**翻的是事实**：

    * T11b 当时 `webui.py` 里没有任何渲染器 → 真树报 `n`，说明里点名
      「缺 `data-strategy` 行模板、`data-family`」——那是对的，缺口不许藏；
    * T12b 把「配置 › 渠道节流」重构为「策略控制」，渲染器按
      `GET /api/strategy` 的 `strategies` 逐条出行（`data-strategy` +
      `data-family`，模板里没有逐条写死的 id）→ 现在报 `y`。
      uitest 那半（真点到行）仍由 T14 补，本条不替它作证。

    负控照旧（下一条用例）：逐条写死 id 的模板仍然报 `n`。
    """
    real = _axis_rows("ttl_tier", "visualizable")
    assert [r.state for r in real] == [sc.Y], real
    assert "data-strategy" in real[0].note, real[0].note

    renderer = """
<div class="srow" data-strategy="${s.id}" data-family="${s.family}">
/* 行数据来自 GET /api/strategy 的 strategies（目录驱动，不逐条写死） */
const ROWS = await (await fetch('/api/strategy')).json();
for (const sid of STRATEGIES) { /* 目录 */ }
"""
    ctx = _ctx_with(webui=renderer)
    rows = _axis_rows("ttl_tier", "visualizable", ctx=ctx)
    assert [r.state for r in rows] == [sc.Y], rows


def test_visualizable_axis_rejects_a_hardcoded_template():
    """逐条写死 id 的模板不算「目录驱动」：那是第二份声明。"""
    hand_written = """
<div class="srow" data-strategy="ttl_tier" data-family="节奏"></div>
<div class="srow" data-strategy="near_window" data-family="节奏"></div>
"""
    ctx = _ctx_with(webui=hand_written)
    rows = _axis_rows("ttl_tier", "visualizable", ctx=ctx)
    assert [r.state for r in rows] == [sc.N], rows


# ---------------------------------------------------------------- 可调整

def test_adjustable_axis_reads_save_control_and_boundary():
    """三件齐了才算可调整：glb 保存侧 + 页面控件 + 数值边界。

    `rate_min_gap` 今天就是「网页能改、能存回 yaml」的（`GLB.min_gap_s` +
    `{id:'glbGap'}`），判据若在这里报 n，说明探针根本没读对登记点。
    """
    real = _axis_rows("rate_min_gap", "adjustable")
    assert [r.state for r in real] == [sc.Y], real

    # 负控伪键（生产代码里根本没有这个 cfg）不许被放过
    fake = _one("rate_min_gap",
                params=(sc.Param("rate_min_gap.value", "crawler.nowhere_xyz",
                                 "float", 3.0, 0, 300),))
    rows = _axis_rows(fake, "adjustable")
    assert [r.state for r in rows] == [sc.N], rows
    assert "nowhere_xyz" in rows[0].note, rows[0].note


def test_adjustable_axis_rejects_a_control_without_range_registration():
    """有控件、有保存侧，但数值参数没登记边界 → n（越界值会静默失效）。"""
    webui = """
        if self.path == "/api/config":
            with _CFG_SAVE_LOCK:
                    glb = body.get("globals") or {}
                    if glb.get("min_gap_s") is not None:
                        _crw["rate"]["min_gap_s"] = int(glb["min_gap_s"])
  +glcell('最小间隔','glbGap','GLB.min_gap_s=Math.max(0,parseInt(this.value)||3)',esc(GLB.min_gap_s),'提示',null,'秒')
const GLB_RANGES=[];
const GLB_RANGES_DYN=[];
"""
    ctx = _ctx_with(webui=webui)
    rows = _axis_rows("rate_min_gap", "adjustable", ctx=ctx)
    assert [r.state for r in rows] == [sc.N], rows
    assert "边界" in rows[0].note, rows[0].note


def test_adjustable_axis_accepts_the_directory_driven_control_shape():
    """T12 的形态：值控件按 `data-pid` 出、边界随身带（`data-min`/`data-max`）。"""
    webui = """
        if self.path == "/api/config":
                    glb = body.get("globals") or {}
                    if glb.get("strategy_overrides") is not None:
                        _crw["strategy_overrides"] = dict(glb["strategy_overrides"])
<div class="srow" data-strategy="${s.id}"><input data-pid="rate_min_gap.value"
 data-min="0" data-max="300"></div>
const GLB_RANGES=[];
const GLB_RANGES_DYN=[{pre:'glbStg_',min:0,max:300,label:'最小间隔须为 0-300 秒'}];
"""
    ctx = _ctx_with(webui=webui)
    rows = _axis_rows("rate_min_gap", "adjustable", ctx=ctx)
    assert [r.state for r in rows] == [sc.Y], rows


def test_adjustable_axis_rejects_a_pid_control_without_bounds():
    """T12 形态也一样：数值控件不带边界 → n。"""
    webui = """
        if self.path == "/api/config":
                    glb = body.get("globals") or {}
                    if glb.get("strategy_overrides") is not None:
                        pass
<div class="srow" data-strategy="${s.id}"><input data-pid="rate_min_gap.value"></div>
const GLB_RANGES=[];
const GLB_RANGES_DYN=[];
"""
    ctx = _ctx_with(webui=webui)
    rows = _axis_rows("rate_min_gap", "adjustable", ctx=ctx)
    assert [r.state for r in rows] == [sc.N], rows
    assert "边界" in rows[0].note, rows[0].note


# ---------------------------------------------------------------- 可统计

def test_stats_axis_is_na_for_advice_only_strategies():
    """只建议、从不执行 → `na` + 理由（规格 §4.1 只允许这一种 na）。"""
    advice_only = [s for s in sc.STRATEGIES if s.auto_default is False]
    assert advice_only, "目录里必须有只建议类（rotate_advice 等）"
    for s in advice_only:
        rows = _axis_rows(s, "stats")
        assert [r.state for r in rows] == [sc.NA], (s.id, rows)
        assert "只建议" in rows[0].note, (s.id, rows[0].note)


def test_stats_axis_is_green_now_that_the_ledger_aggregates_by_strategy():
    """T12a 起 `stats` 轴为 `y`：台账能按策略归集 + `/api/strategy` 售出计数。

    这条**原来是「今天红」**的断言（`..._reports_n_without_a_ledger_key`）：当时
    `core/storage.py` 没有按策略归集的口径、`webui.py` 也没有该路由，判据读真实
    登记点，只能报 `n`。T12a 把两半都补上了（`PriceStorage.strategy_stats()` 按
    note 的 `[<sid>]` 前缀归集 + `GET /api/strategy` 的 `stats` 三键），所以这里
    翻成 `y`——**翻的是事实，判据一个字符没改**（这正是「不写第二份声明」该有的
    样子：代码变了，矩阵跟着变，没有人去同步一张表）。
    """
    rows = _axis_rows("block_window", "stats", plats=("*",))
    assert [r.state for r in rows] == [sc.Y], rows
    assert rows[0].note.strip()


def test_stats_axis_still_reports_n_when_the_ledger_cannot_group():
    """负控：台账里没有归集口径、路由也没有 → 仍然 `n`（判据不是恒真）。"""
    ctx = _ctx_with(webui="        elif self.path == \"/api/strategy\":\n            pass\n",
                    storage="def only_prices(self):\n    return []\n")
    rows = _axis_rows("block_window", "stats", ctx=ctx)
    assert [r.state for r in rows] == [sc.N], rows
    assert "storage" in rows[0].note or "台账" in rows[0].note, rows[0].note


def test_stats_axis_accepts_the_t6_ledger_convention():
    """T6 的账本约定：策略 id 写在 note 的 `[<sid>]` 前缀里（不在 scope 列），
    所以「能按策略聚数」= storage.py 有策略族前缀 + note 前缀的计数口径，
    并且 `/api/strategy` 把它售出。合成源码证明这条判据不是恒 n。"""
    storage = '''
    def strategy_interventions(self, sid, hours=24):
        """按策略归集：`strategy:<sid>` 口径。"""
        key = "strategy:%s" % sid
        return self._q("SELECT action, ok, COUNT(*) FROM interventions "
                       "WHERE substr(note,1,?) = ? GROUP BY action, ok",
                       (len(key) - len(sid), "[" + sid + "]"))
'''
    webui = '        elif self.path == "/api/strategy":\n            pass\n'
    ctx = _ctx_with(webui=webui, storage=storage)
    rows = _axis_rows("block_window", "stats", ctx=ctx)
    assert [r.state for r in rows] == [sc.Y], rows
    assert rows[0].note.strip()


# ---------------------------------------------------------------- 十五列展示

def test_matrix_and_json_tolerate_fifteen_columns():
    txt = sc.matrix_text(plats=("*",))
    head = txt.splitlines()[0]
    for a in sc.AXIS_IDS:
        assert sc.AXIS_CN[a] in head, ("矩阵表头缺列：%s" % a, head)
    body = [ln for ln in txt.splitlines()[2:] if ln.strip()
            and not ln.startswith("缺陷") and not ln.startswith("汇总")
            and not ln.startswith("  [") and not ln.startswith("全部")]
    assert len(body) == len(sc.STRATEGIES)
    for ln in body:
        got = sum(ln.count(g) for g in "√×—")
        assert got == 15, ("每行必须是 15 格", ln, got)

    payload = [{"sid": r.sid, "plat": r.plat, "axis": r.axis,
                "state": r.state, "note": r.note}
               for r in sc.audit(plats=("*",))]
    assert {r["axis"] for r in payload} == set(sc.AXIS_IDS)


# ---- merged from tests/test_r1063_strategy_params.py ----

@pytest.fixture(autouse=True)
def _cfg():
    sp.set_config({"schedule": {"fast_ttl_min": 30},
                   "crawler": {"rate": {"per_minute": 0},
                               "policy": {"pace": {"watch": 2.0}},
                               "strategy_overrides": {
                                   "fliggy": {"rate_per_minute.value": 9},
                                   "tongcheng/intl/PC":
                                       {"rate_per_minute.value": 3}}}})
    yield
    sp.invalidate()


def test_default_when_nothing_configured():
    # 本用例的前提是「什么都没配」，而 autouse 夹具给每个用例都塞了 cfg，
    # 所以先回到默认态（否则它与 test_global_beats_default 会对**同一状态**
    # 断言两个不同的值：15/default vs 30/global）。
    sp.invalidate()
    got = sp.resolve("ttl_tier.fast")
    assert (got.value, got.source) == (15, "default")


def test_global_beats_default():
    got = sp.resolve("ttl_tier.fast")
    assert got.value == 30 and got.source == "global"


def test_channel_override_beats_global():
    assert sp.resolve("rate_per_minute.value", plat="fliggy").value == 9
    assert sp.resolve("rate_per_minute.value", plat="ctrip").source == "global"


def test_path_override_beats_channel_override():
    got = sp.resolve("rate_per_minute.value", plat="tongcheng",
                     dim="intl", path="PC")
    assert (got.value, got.source) == (3, "path")
    # 只给渠道、不给维度时落在渠道（已配的渠道覆盖）
    assert sp.resolve("rate_per_minute.value",
                      plat="tongcheng").source == "global"


def test_override_key_rejects_unknown_segments():
    with pytest.raises(ValueError):
        sp.parse_override_key("nosuchchan/intl/PC")
    with pytest.raises(ValueError):
        sp.parse_override_key("ctrip/nosuchdim/PC")
    with pytest.raises(ValueError):
        sp.parse_override_key("ctrip/intl/nosuchpath")


def test_non_dict_override_block_is_rejected():
    """整块覆盖写成非字典 → 装载即报错（不许「配了不生效」）。

    复核指出的真实缺陷：`strategy_overrides: [...]` 曾能被静默接受，
    装载不报错、求值全走默认值——用户以为配了，实际什么都没发生。
    """
    for bad in ([], ["fliggy"], "fliggy", 5, True):
        with pytest.raises(ValueError):
            sp.set_config({"crawler": {"strategy_overrides": bad}})
    # 空字典是合法的「没有覆盖」，不能被当成错误
    sp.set_config({"crawler": {"strategy_overrides": {}}})
    assert sp.resolve("rate_per_minute.value", plat="fliggy").source == "default"


def test_bad_load_does_not_pollute_previous_config():
    """坏装载必须在**替换之前**被挡住：上一份好配置仍原样生效。

    复核指出：`test_non_dict_override_block_is_rejected` 的注释声称验这件事，
    但它先装载坏配置（抛错）再装载空字典、断言的是 `default`——两种情形都成立，
    等于没验「旧配置有没有被搞坏」。这里补真断言：好配置 → 装载失败 → 好值还在。
    """
    sp.set_config({"crawler": {"strategy_overrides": {
        "fliggy": {"rate_per_minute.value": 9}}}})
    assert sp.resolve("rate_per_minute.value", plat="fliggy").value == 9
    with pytest.raises(ValueError):
        sp.set_config({"crawler": {"strategy_overrides": ["fliggy"]}})
    got = sp.resolve("rate_per_minute.value", plat="fliggy")
    assert (got.value, got.source) == (9, "channel"), (
        "装载失败之后旧配置被污染了：%r/%r" % (got.value, got.source))


def test_override_key_roundtrips_paths_containing_slash():
    """真实通路 id 里有 "/"（`H5/API`）：分隔符最多切两刀，段三允许含 "/"。

    复核裁决：`key.split("/", 2)`——plat/dim 永不含 "/"，段三可以含。
    `override_key` 与 `parse_override_key` 必须互为逆运算。
    """
    for plat, dim, path in (("ctrip", "intl", "H5/API"),
                            ("fliggy", "domestic", "PC"),
                            ("app_zhixing", "domestic", "app-city-%s"),
                            ("app_qunar", "domestic", "app-city-bjs")):
        key = sp.override_key(plat, dim, path)
        assert sp.parse_override_key(key) == (plat, dim, path), key
    assert sp.override_key("ctrip", "intl", "H5/API") == "ctrip/intl/H5/API"
    # 含 "/" 不等于免检：未知段照样抛
    with pytest.raises(ValueError):
        sp.parse_override_key("ctrip/intl/H5/API2")
    with pytest.raises(ValueError):
        sp.parse_override_key("ctrip/intl/nosuch/path")
    # 端到端：段三带 "/" 的链路覆盖真的能生效
    sp.set_config({"crawler": {"strategy_overrides": {
        "ctrip/intl/H5/API": {"rate_per_minute.value": 4}}}})
    got = sp.resolve("rate_per_minute.value", plat="ctrip",
                     dim="intl", path="H5/API")
    assert (got.value, got.source) == (4, "path")


def test_template_path_must_be_consumed_whole():
    """`app-city-*` 类模板通路：模板前缀必须吃掉**整段**，不许再带 `/`。

    复核指出的洞：`ctrip/domestic/app-city-bjs/x` 走前缀匹配能装载，但求值时
    永远命不中 `PATH_CN` 里的任何通路名——装载成功、永不生效，正是本项目定义
    为最糟的「配了不生效」。字面量键（`H5/API`）不受影响，它自己就含 `/`。
    """
    assert sp.parse_override_key("ctrip/domestic/app-city-bjs") == \
        ("ctrip", "domestic", "app-city-bjs")
    with pytest.raises(ValueError):
        sp.parse_override_key("ctrip/domestic/app-city-bjs/x")
    with pytest.raises(ValueError):
        sp.parse_override_key("ctrip/domestic/app-city-%s/x")
    # 判据本身也钉一下（装载与求值必须同一口径）
    assert sp._path_ok("app-city-bjs") is True
    assert sp._path_ok("app-city-bjs/x") is False
    assert sp._path_ok("H5/API") is True
    assert sp._path_ok("ctrip/intl/H5/API") is False


def test_clamp_returns_note_so_ui_can_write_back():
    v, note = sp.clamp("ttl_tier.fast", 99999)
    assert v == 1440 and note


def test_container_kinds_are_map_and_list_and_pass_through():
    """容器键的 `kind` 必须如实：两个映射 + 一个列表。

    T12 照 `Param.kind` 画控件——把 `{渠道: 分钟}` 登记成 `int`，界面就会画一个
    数字框，填进去的东西谁也不读，正是本项目头号缺陷「配了不生效」。同时
    `resolve`/`clamp` 对容器值必须**原样透传**：不转类型、不夹取、不重写。
    """
    from core.strategy_contract import KINDS
    assert ("map" in KINDS) and ("list" in KINDS)
    assert sp.PARAMS["cadence.per_plat"].kind == "map"
    assert sp.PARAMS["proxy_route.map"].kind == "map"
    assert sp.PARAMS["warmup.platforms"].kind == "list"

    raw = {"crawler": {"cadence": {"ctrip": 30},
                       "proxy_map": {"ctrip": "socks5://127.0.0.1:1080"},
                       "warmup": {"platforms": ["ctrip", "qunar"]}}}
    sp.set_config(raw)
    assert sp.resolve("cadence.per_plat").value == {"ctrip": 30}
    assert sp.resolve("proxy_route.map").value == \
        {"ctrip": "socks5://127.0.0.1:1080"}
    assert sp.resolve("warmup.platforms").value == ["ctrip", "qunar"]

    for pid, val in (("cadence.per_plat", {"fliggy": 15}),
                     ("proxy_route.map", {"fliggy": "http://127.0.0.1:9"}),
                     ("warmup.platforms", ["tuniu"])):
        got, note = sp.clamp(pid, val)
        assert (got, note) == (val, ""), pid


# 模块级可写状态白名单：除了 cfg 单例与**声明索引**，这里不该有第二处状态。
# 声明索引只装 `core/strategy_contract.py` 里不可变的 `Param`，从不装求值结果。
_WRITABLE = frozenset({
    "_CFG",          # 唯一的状态：当前装入的配置（引用语义 = 热生效）
    "PARAMS",        # 声明索引（pid → Param），不装值
    "DUP_PIDS",      # 重复 pid 名单（导入期算一次）
    "_MISSING",      # 取值哨兵
    "_TRUE", "_FALSE",   # 真假字面量表
    "OVERRIDE_CFG", "SOURCES", "PLATS", "Resolved",
    # r1063 波次 2 起：`switch_on()` 的「同一次坏值只告警一次」去重集合。
    # 它只装 `(pid, repr(值))` 这类**已告警过**的键，从不装求值结果，
    # 因此不构成第二处参数状态；下面三条断言仍然保证它不缓存值。
    "TRUE_WORDS", "FALSE_WORDS", "_SWITCH_WARNED",
})


def test_hot_singleton_carries_no_second_writable_state():
    """热链路的硬约束：参数只在提供者里现算，模块级没有第二处可写状态。

    旧版这条断言 `core/policy.py` 里不含 `self._pace =` / `self._block_s =`
    ——两个标识符**根本不存在**，用例恒真（复核实测：policy.py:108 的真实
    风险形态是 `self.pace_factor = …`，扫不到）。改成行为型断言：
    """
    import types

    # ① 行为：同一进程两次 set_config 立刻生效——不重建、不 invalidate
    sp.set_config({"schedule": {"fast_ttl_min": 40}})
    assert sp.resolve("ttl_tier.fast").value == 40
    sp.set_config({"schedule": {"fast_ttl_min": 7}})
    assert sp.resolve("ttl_tier.fast").value == 7

    # ② 求值结果是不可变值对象（没人能往实例上挂缓存）
    assert issubclass(sp.Resolved, tuple)
    assert sp.Resolved._fields == ("value", "source", "pid")

    # ③ 模块级名字集合：白名单之外不许出现可写容器/对象
    extra = []
    for name, obj in vars(sp).items():
        if name.startswith("__") or name in _WRITABLE:
            continue
        if isinstance(obj, (types.FunctionType, types.ModuleType, type)):
            continue                      # 函数/模块/类：引用，不是状态
        if isinstance(obj, (str, int, float, bool, tuple, frozenset,
                            type(None))):
            continue                      # 不可变字面量/常量
        if type(obj).__module__ in ("typing", "__future__"):
            continue                      # typing 构造子 / `annotations` 标志
        extra.append(name)
    assert not extra, "模块里出现了白名单外的模块级状态：%s" % extra
