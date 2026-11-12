# -*- coding: utf-8 -*-
r"""r1063 T12a：`GET /api/strategy`（目录 + 生效值 + 来源 + 矩阵 + 停手）与按策略台账聚合。

规格见 `docs/superpowers/specs/2026-11-06-crawl-strategy-control-plane-design.md`
§6(c)（接口）与 §4.1（`stats` 轴：台账能按策略聚出「干预 N 次 / 生效 M 次」）。

本文件钉五件事，每件都**先红后绿**：

1. **接口形状**：30 条策略一个不少，每条都带
   `id/cn/family/trigger/scope/label/intent/effect/auto_default/api/advice`
   + `params[{pid,value,source,default,lo,hi}]` + `stats{interventions,healed,unhealed}`；
   `plats` 是 10 家渠道、`overrides` 是 `crawler.strategy_overrides` 原样、`matrix`
   与 CLI 同源（同一份 `audit()` 的聚合）。
2. **绝不缺键**：台账里一条记录都没有时，`stats` 也必须三个键齐全且为 0——
   面板上「没有数字」与「数字是 0」是两件事，缺键会让界面画成 `undefined`。
3. **按策略归集只认 `note` 的 `[<sid>]` 前缀**：`strategy_*` 动作族的干预记到
   那条策略的 `interventions` 上，同一行**不许**顺带漏进人工干预成功率
   （T6 钉过的分界：调一次参不该冲掉「人救过一次」的统计）。
4. **判不了 ≠ 失败**（r506）：窗口内零采集样本记 `unjudged`，不许算成
   `unhealed`——干预刚做完还没采集，把成功率压成噪声。
5. **既有 `/api/pacing` 形状不变**：健康面板与既有门禁都在消费它，本任务只新增
   路由，不许动它的键。

`observable` 轴同时被收紧成「**精确**路由 `self.path == "/api/strategy"` + 该分支里
真调了 `audit(`/`matrix_text(`」——旧判据被子串 `/api/strategy`（`/api/strategy/halt`
也含它）与子串 `audit`（一个 CSS 类名就能点亮）满足，等于白送分。负控在本文件
末尾用合成源码证明判据不是恒真。

运行（必须带 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，否则插件加载超时）：

    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
      tests/test_r1063_strategy_api.py -q
"""
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 一条策略行必须具备的键（缺一个界面就会画空/画 undefined）
ROW_KEYS = ("id", "cn", "family", "trigger", "scope", "label", "intent",
            "effect", "auto_default", "api", "advice", "params", "stats")
PARAM_KEYS = ("pid", "value", "source", "default", "lo", "hi")
STATS_KEYS = ("interventions", "healed", "unhealed")


# ---------------------------------------------------------------------------
# 替身：只实现 `do_GET` 真正用到的那几样（path / command / headers / _json）
# ---------------------------------------------------------------------------
class _Get:
    """把 `_Handler.do_GET` 拉进进程内跑的最小鸭子类型 handler。

    为什么不用真起服务：本文件要断言的是**载荷内容**（28 行、键齐全、计数正确），
    起 HTTP 只会多一层端口与时序噪声；而 `do_GET` 的每个分支本来就只依赖
    `self.path` 与 `self._json`，替身足够真。
    """

    command = "GET"

    def __init__(self, path):
        self.path = path
        self.headers = {}
        self.captured = None
        self.code = 200

    def _json(self, obj, code=200):
        self.captured, self.code = obj, code


class _Web:
    """夹具返回值：`m`=webui 模块 / `ps`=临时台账 / `base_dir`=资料目录。"""

    def __init__(self, m, ps, base_dir):
        self.m = m
        self.ps = ps
        self.base_dir = base_dir


@pytest.fixture
def web(tmp_path, monkeypatch):
    """把三处落盘接到 tmp：配置、干预台账、策略引擎（停手文件所在目录）。"""
    import webui
    from core.storage import PriceStorage

    ps = PriceStorage(str(tmp_path / "t.db"))
    base_dir = str(tmp_path / "profile")
    os.makedirs(base_dir, exist_ok=True)

    class _Eng:
        def __init__(self):
            self.base_dir = base_dir

    monkeypatch.setattr(webui._State, "cfg", {
        "output": {"db_path": str(tmp_path / "t.db")},
        "crawler": {"strategy_overrides":
                    {"fliggy": {"rate_per_minute.value": 6}}},
    }, raising=False)
    monkeypatch.setattr(webui, "_strategy_storage", lambda: ps, raising=False)
    monkeypatch.setattr(webui, "_policy_engine", lambda plat="": _Eng(),
                        raising=False)
    return _Web(webui, ps, base_dir)


def _get(m, path):
    """跑一次 `do_GET`，返回替身（载荷在 `.captured`，状态码在 `.code`）。"""
    h = _Get(path)
    m._Handler.do_GET(h)
    return h


# ---------------------------------------------------------------------------
# 1. 接口形状：28 条 × 每个字段
# ---------------------------------------------------------------------------
def test_route_returns_28_strategies_with_every_field(web):
    from core.strategy_contract import AXIS_IDS, STRATEGIES

    h = _get(web.m, "/api/strategy")
    assert h.code == 200, h.captured
    d = h.captured
    assert d.get("ok") is True, d.get("errors")

    rows = d["strategies"]
    # r1063 T22/T31：30 条（新增「换跑道」与「渠道内限速档」）
    assert len(rows) == 31, len(rows)          # r1063 T47 起 31 条
    assert [r["id"] for r in rows] == [s.id for s in STRATEGIES], \
        "目录顺序被改了：界面按目录顺序出行"
    for row in rows:
        sid = row.get("id")
        for k in ROW_KEYS:
            assert k in row, (sid, "缺字段 " + k)
        assert row["cn"] and row["family"] and row["label"], sid
        assert isinstance(row["scope"], list) and row["scope"], sid
        assert isinstance(row["auto_default"], bool), sid
        assert isinstance(row["api"], list), sid
        for p in row["params"]:
            for k in PARAM_KEYS:
                assert k in p, (sid, p.get("pid"), "缺参数字段 " + k)
            assert p["source"] in ("default", "global", "channel",
                                   "dimension", "path"), (sid, p)

    # 矩阵段与 CLI 同源：每条策略 × 每条轴一格，状态只许三态
    cells = {(r["sid"], r["axis"]): r["state"] for r in d["matrix"]}
    assert len(cells) == len(STRATEGIES) * len(AXIS_IDS), len(cells)
    assert {st for st in cells.values()} <= {"y", "n", "na"}
    assert "defects_n" in d, "缺陷计数缺失（`--strict` 的界面同源面）"


def test_plats_are_the_ten_channels(web):
    from core.channels import APP_CHANNELS, BROWSER_CHANNELS

    d = _get(web.m, "/api/strategy").captured
    assert set(d["plats"]) == set(BROWSER_CHANNELS) | set(APP_CHANNELS), d["plats"]
    assert len(d["plats"]) == 10, d["plats"]


def test_overrides_are_the_raw_cfg_mapping(web):
    d = _get(web.m, "/api/strategy").captured
    assert d["overrides"] == {"fliggy": {"rate_per_minute.value": 6}}, \
        d["overrides"]


def test_params_carry_value_and_source_not_just_the_catalog_default(web):
    """生效值走 `strategy_params.resolve()`（唯一求值入口），不自己读 cfg。"""
    from core import strategy_params as sp

    d = _get(web.m, "/api/strategy").captured
    row = [r for r in d["strategies"] if r["id"] == "rate_min_gap"][0]
    assert row["params"], "限速策略必须有参数行"
    got = {p["pid"]: p for p in row["params"]}
    pid = row["params"][0]["pid"]
    want = sp.resolve(pid)
    assert got[pid]["value"] == want.value, (got[pid], want)
    assert got[pid]["source"] == want.source, (got[pid], want)


# ---------------------------------------------------------------------------
# 2. 台账没有记录时也要三键齐全（给 0，不给 undefined）
# ---------------------------------------------------------------------------
def test_stats_has_all_keys_even_without_ledger_rows(web):
    d = _get(web.m, "/api/strategy").captured
    for row in d["strategies"]:
        for k in STATS_KEYS:
            assert k in row["stats"], (row["id"], "缺 stats." + k)
            assert isinstance(row["stats"][k], int), (row["id"], k)
    row = [r for r in d["strategies"] if r["id"] == "block_window"][0]
    assert row["stats"]["interventions"] == 0
    assert row["stats"]["healed"] == 0
    assert row["stats"]["unhealed"] == 0


# ---------------------------------------------------------------------------
# 3. 按策略归集：`[<sid>]` 前缀 + `strategy_*` 族
# ---------------------------------------------------------------------------
def test_strategy_halt_row_lands_in_the_right_strategys_interventions(web):
    web.ps.save_intervention("ctrip", "strategy_halt", ok=True, scope="ctrip",
                             note="[block_window] 人工停手 30 分钟")
    web.ps.save_fetch_path("ctrip", "上海", "北京", "2026-12-01", "PC", "ok")

    d = _get(web.m, "/api/strategy").captured
    by = {r["id"]: r for r in d["strategies"]}
    assert by["block_window"]["stats"]["interventions"] == 1, by["block_window"]
    assert by["block_window"]["stats"]["healed"] == 1, by["block_window"]
    assert by["block_window"]["stats"]["unhealed"] == 0, by["block_window"]
    # 别的策略不许被顺带记上
    assert by["ttl_tier"]["stats"]["interventions"] == 0
    # 同一行也不许漏进人工干预成功率（T6 的分界：strategy_* 不进这一族）
    assert "strategy_halt" not in web.ps.intervention_success_rate()


def test_strategy_stats_groups_by_note_prefix_only(tmp_path):
    """只认 `[<sid>]` 前缀 + `strategy_*` 族；人工族/自动族/无前缀一律不进。"""
    from core.storage import PriceStorage

    ps = PriceStorage(str(tmp_path / "s.db"))
    ps.save_intervention("ctrip", "strategy_halt", ok=True,
                         note="[block_window] 人工停手 5 分钟")
    ps.save_intervention("ctrip", "strategy_set", ok=True,
                         note="[rate_min_gap] 最小间隔 5 秒")
    ps.save_intervention("ctrip", "probe", ok=True,
                         note="[block_window] 这是人工干预，不许算策略干预")
    ps.save_intervention("ctrip", "auto_trip", ok=True,
                         note="[block_window] 自动事件也不算策略变更")
    ps.save_intervention("ctrip", "strategy_halt", ok=True,
                         note="没有前缀，归不到任何策略")

    st = ps.strategy_stats()
    assert set(st) == {"block_window", "rate_min_gap"}, st
    assert st["block_window"]["interventions"] == 1, st
    assert st["rate_min_gap"]["interventions"] == 1, st


def test_unjudged_window_is_not_counted_as_unhealed(web):
    """干预刚做完还没有采集样本 → `unjudged`，不是「没救回来」（r506 同条裁决）。"""
    web.ps.save_intervention("ctrip", "strategy_halt", ok=True, scope="ctrip",
                             note="[block_window] 人工停手 30 分钟")
    d = _get(web.m, "/api/strategy").captured
    st = [r for r in d["strategies"] if r["id"] == "block_window"][0]["stats"]
    assert st["interventions"] == 1, st
    assert st["healed"] == 0 and st["unhealed"] == 0, st
    assert st.get("unjudged") == 1, st


def test_failed_sample_makes_the_intervention_unhealed(web):
    web.ps.save_intervention("ctrip", "strategy_halt", ok=True, scope="ctrip",
                             note="[block_window] 人工停手 30 分钟")
    web.ps.save_fetch_path("ctrip", "上海", "北京", "2026-12-01", "PC", "fail")
    d = _get(web.m, "/api/strategy").captured
    st = [r for r in d["strategies"] if r["id"] == "block_window"][0]["stats"]
    assert st["interventions"] == 1 and st["unhealed"] == 1, st
    assert st["healed"] == 0, st


# ---------------------------------------------------------------------------
# 4. 停手段：只读、按 profile 读、坏掉不许把整条路由带成 500
# ---------------------------------------------------------------------------
def test_halt_section_reports_the_profile_halt_file(web):
    from core.policy import set_halt

    set_halt(web.base_dir, "ctrip", 30, "人工停手")
    d = _get(web.m, "/api/strategy").captured
    assert d["halt"]["ctrip"]["until"] > 0, d["halt"]
    assert d["halt"]["ctrip"]["note"] == "人工停手", d["halt"]
    assert d["halt"]["ctrip"]["left_s"] > 0, d["halt"]
    assert "qunar" not in d["halt"], "没停手的渠道不许出现在停手表里"


def test_halt_section_failure_degrades_to_empty_not_500(web, monkeypatch):
    """策略层炸了只让 `halt` 这段空掉：其余四段照出（段内降级，不整条 500）。"""

    def _boom(plat=""):
        raise RuntimeError("策略层不可用")

    monkeypatch.setattr(web.m, "_policy_engine", _boom, raising=False)
    h = _get(web.m, "/api/strategy")
    assert h.code == 200, h.captured
    assert h.captured["halt"] == {}
    assert len(h.captured["strategies"]) == 31, "停手段失败不该拖垮目录段"


def test_ledger_failure_degrades_stats_to_zero_not_500(web, monkeypatch):
    """账本读不出来时给 0 并在 `errors.stats` 写清原因，不许整条路由 500。"""

    def _boom():
        raise RuntimeError("数据库被锁")

    monkeypatch.setattr(web.m, "_strategy_storage", _boom, raising=False)
    h = _get(web.m, "/api/strategy")
    assert h.code == 200, h.captured
    assert "stats" in h.captured["errors"], h.captured["errors"]
    row = [r for r in h.captured["strategies"] if r["id"] == "block_window"][0]
    assert row["stats"]["interventions"] == 0, row["stats"]


# ---------------------------------------------------------------------------
# 5. 既有 `/api/pacing` 形状不变（健康面板与既有门禁都在吃它）
# ---------------------------------------------------------------------------
def test_pacing_route_keeps_its_shape(web, monkeypatch):
    class _Pace:
        def snapshot(self):
            return {"channels": {"ctrip": {"pace": 1.0}},
                    "quiet": {"on": False}}

    monkeypatch.setattr(web.m._State, "pacing", _Pace(), raising=False)
    monkeypatch.setattr(web.m, "_paths_payload",
                        lambda h=24, demo=False: {"platforms": {}},
                        raising=False)
    h = _get(web.m, "/api/pacing")
    assert h.code == 200, h.captured
    assert h.captured["ok"] is True, h.captured
    assert "ctrip" in h.captured["channels"], "既有载荷键被改了"


# ---------------------------------------------------------------------------
# 6. `observable` 轴收紧：精确路由 + 真调审计（负控，证明判据不是恒真）
# ---------------------------------------------------------------------------
def _observable_state(webui_src):
    from core import strategy_contract as sc

    ctx = sc._Ctx()
    ctx._webui = webui_src
    one = [s for s in sc.STRATEGIES if s.id == "block_window"][0]
    rows = [r for r in sc.audit(strategies=(one,), plats=("*",), ctx=ctx)
            if r.axis == "observable"]
    assert rows, "可观测轴没求值"
    return rows[0]


def test_observable_rejects_the_halt_route_substring():
    """`/api/strategy/halt` 含 `/api/strategy` 子串——但它是停手路由，不是目录接口。"""
    src = '        elif self.path == "/api/strategy/halt":\n            pass\n'
    row = _observable_state(src)
    assert row.state == "n", row.note
    assert "/api/strategy" in row.note or "路由" in row.note, row.note


def test_observable_rejects_a_mention_without_a_real_call():
    """路由在、但分支里只「提到」audit 这个词（注释/类名）→ 仍然 n。"""
    src = ('        elif self.path == "/api/strategy":\n'
           '            # audit 一下就好了（注释里提一句不算接到界面）\n'
           '            self._json({"cls": "auditbox"})\n')
    row = _observable_state(src)
    assert row.state == "n", row.note
    assert "matrix_text" in row.note or "audit" in row.note, row.note


def test_observable_accepts_an_exact_route_that_calls_the_audit():
    src = ('        elif self.path == "/api/strategy":\n'
           '            out["matrix"] = matrix_text()\n')
    row = _observable_state(src)
    assert row.state == "y", row.note


def test_real_webui_serves_observable_through_the_exact_route():
    """真 webui.py：精确路由 + 该分支真调 `audit(`（不是靠子串点亮）。"""
    from core import strategy_contract as sc

    ctx = sc._ctx()
    assert "/api/strategy" in ctx.routes(), "缺精确路由 self.path == \"/api/strategy\""
    body = ctx.strategy_route_body()
    assert body, "取不到 /api/strategy 分支源码（路由字面量不精确？）"
    assert "audit(" in body or "matrix_text(" in body, body[:400]
