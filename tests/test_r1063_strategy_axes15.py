# -*- coding: utf-8 -*-
"""r1063 T11b：矩阵扩到十五轴，每条策略补「可清晰 / 可意图理解」的文案。

规格见 `docs/superpowers/specs/2026-11-06-crawl-strategy-control-plane-design.md`
§4.1（目标扩句后新增的五轴）。五条新轴各自都要**可证伪**：

    可可视化 visualizable  界面上真有渲染落点（渲染器从目录取 id）
    可调整   adjustable    `/api/config` 的 glb 侧有该参数的键 + 页面上有控件 + 边界登记
    可清晰   clear         `Strategy.label`：≤20 字中文短句，不露裸 id、不带英文
    可意图理解 intent      `Strategy.intent` 与 `effect`：各 ≤40 字，说清防什么/改了什么
    可统计   stats         台账能按策略归集（`strategy:<sid>` 或 note 的 `[sid]` 前缀），
                           只建议类（`auto_default=False`）记 `na` + 理由

本文件除 brief 的四条正向外，**每条新轴都带负控**：造一个坏掉的策略或一份假源码，
证明该轴真的会报 `n`（不是恒真）；其中三条还用合成源码证明「T12 建好界面/台账后
能变 y」——判据不能只会在当前工作树上恒 n。
"""
import dataclasses

from core import strategy_contract as sc


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
