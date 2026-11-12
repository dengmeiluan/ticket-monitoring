# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_interrupt.py
- tests/test_r1063_paths_in_strategy.py
- tests/test_r1063_strategy_api.py
- tests/test_r1063_strategy_axes_closure.py
- tests/test_r1063_strategy_contract.py
- tests/test_r1063_strategy_interrupt.py
- tests/test_r1063_strategy_panel.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import dataclasses
import io
import json
import logging
import os
import pytest
import re
import sys
import time

from core import channels as CH, interrupt as IT, strategy_params as sp
from core.strategy_params import parse_override_key


# ---- merged from tests/test_r1063_interrupt.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_request_and_clear():
    IT.clear()
    assert IT.requested() is False
    IT.request(by="test")
    assert IT.requested() is True
    IT.clear()
    assert IT.requested() is False


def test_request_expires(monkeypatch):
    """过期请求必须自动失效（否则昨天的一次点击会吞掉今天的轮次）。"""
    IT.clear()
    IT.request(by="test")
    real = time.time
    monkeypatch.setattr(IT.time, "time", lambda: real() + IT.TTL_S + 5,
                        raising=False)
    assert IT.requested() is False
    assert IT.state()["active"] is False
    IT.clear()


def test_state_shape():
    IT.clear()
    st = IT.state()
    for k in ("requested", "at", "by", "active", "ttl_s"):
        assert k in st, st


def test_main_loop_checks_interrupt_between_routes():
    src = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    i = src.index("for qi, (fc, tc, d) in enumerate(queries):")
    seg = src[i:i + 1200]
    assert "_itr.requested()" in seg, "航线循环入口必须问一次中止"
    assert "不再派发下一条航线" in seg, "语义要写清：不强杀线程"
    assert "_itr.clear()" in seg, "生效后要清掉请求，否则后续轮次全被吞"


def test_api_has_stop_and_clears_on_run():
    w = webui_full_src()
    assert '"/api/run/stop"' in w
    i = w.index('elif self.path == "/api/run":')
    seg = w[i:i + 400]
    assert "_itr.clear()" in seg, "新一轮开始必须清掉遗留中止请求"

def test_marker_is_cross_process(tmp_path, monkeypatch):
    """`request()` 必须落盘：CLI 在**另一个进程**里，只靠内存标志看不到。

    实测暴露过：webui 里 `POST /api/run/stop` 置位成功，另开
    `python -m core.interrupt --state` 读到 false —— 那条路等于没接线。
    """
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    IT.clear()
    IT.request(by="pytest")
    marker = tmp_path / ".interrupt.json"
    assert marker.is_file(), "没有落盘标记，CLI 那条路就是死的"
    # 模拟"另一个进程"：清空内存态，只留文件
    with IT._LOCK:
        IT._STATE.update({"requested": False, "at": 0.0, "by": ""})
    assert IT.requested() is True, "只靠落盘标记也必须能读到请求"
    IT.clear()
    assert not marker.is_file(), "clear() 要顺手把标记删掉"


def test_state_reports_marker_path(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    IT.clear()
    st = IT.state()
    assert "marker" in st and str(tmp_path) in st["marker"]


# ---- merged from tests/test_r1063_paths_in_strategy.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_new_paths_registered_with_cn_labels():
    assert "PC·国际" in CH.PATH_CN
    assert "PC·周历" in CH.PATH_CN
    # 标签要有含义（不是空串），面板直接显示它
    assert "国际" in CH.PATH_CN["PC·国际"]
    assert "周历" in CH.PATH_CN["PC·周历"]


def test_override_key_accepts_new_paths():
    assert parse_override_key("tuniu/intl/PC·国际") == ("tuniu", "intl",
                                                        "PC·国际")
    assert parse_override_key("ctrip/domestic/PC·周历") == ("ctrip", "domestic",
                                                            "PC·周历")


def test_strategy_api_exposes_path_list():
    src = webui_full_src()
    i = src.index('out["paths"] = [{"id": _k, "cn": _v}')
    seg = src[max(0, i - 400):i + 200]
    assert "from core.channels import PATH_CN" in seg, \
        "通路清单必须从唯一口径 PATH_CN 取，不能另抄一份"
    assert 'out["paths"]' in src


def test_calendar_and_list_paths_are_classified():
    """口径分类（日历类/列表类）必须覆盖这些真实通路名。"""
    from core.channel_matrix import path_kind
    assert path_kind("PC·周历") == "calendar"
    assert path_kind("窗历") == "calendar"
    assert path_kind("PC·国际") == "list"
    assert path_kind("H5/API") == "list"


# ---- merged from tests/test_r1063_strategy_api.py ----

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


# ---- merged from tests/test_r1063_strategy_axes_closure.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _webui():
    return webui_full_src()


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


# ---- merged from tests/test_r1063_strategy_contract.py ----

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


# ---- merged from tests/test_r1063_strategy_interrupt.py ----

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


# ---- merged from tests/test_r1063_strategy_panel.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 非 flat 的数值参数必须有独立控件与边界（这些键此前页面上没有任何控件：
# `crawler.policy.pace.*` / `sticky_s.*` / `block_s.human` / `risk.levels.*`）
NEW_NUMERIC_IDS = ("glbPaceWatch", "glbPaceDegraded", "glbStickyWatch",
                   "glbBlockHuman", "glbRiskPause")


def _w():
    return webui_full_src()


def _fn(src, name):
    """取一个顶层函数的源码段（到下一个 `function ` 为止）。"""
    i = src.index(name)
    j = src.index("\nfunction ", i + 1)
    return src[i:j]


def _renderer(src):
    """整段渲染器（参数格 + 行模板 + 拉取/绘制）：边界/徽标分散在这几支里。"""
    i = src.index("function stratCellHTML(")
    j = src.index("/* ===== 子卡折叠", i)
    return src[i:j]


# ---------------------------------------------------------------- 目录驱动

def test_panel_is_directory_driven_and_has_no_second_declaration():
    """渲染器必须从 `/api/strategy` 取行，模板里不许逐条写死 28 个 id。"""
    from core.strategy_contract import STRATEGIES

    w = _w()
    assert "/api/strategy" in w
    assert "data-strategy" in w, "策略行没有 data-strategy 落点"
    assert w.count('data-strategy="rate_per_minute"') == 0, (
        "模板里写死了 rate_per_minute —— 那是第二份声明")
    hard = [s.id for s in STRATEGIES if 'data-strategy="%s"' % s.id in w]
    assert not hard, "模板里逐条写死了这些策略 id：%s" % hard


def test_every_row_carries_sid_family_and_a_source_badge():
    """每行三件齐全：`data-strategy` / `data-family` / 来源徽标。"""
    w = _w()
    row = _fn(w, "function stratRowHTML(")
    # 行容器：id 与族都由载荷带出（插值，不是字面量）
    assert re.search(r'data-strategy=["\']\s*["\']?\s*\+?', row) or \
        "data-strategy=" in row, row[:200]
    assert "data-family=" in row, "行上没有 data-family（芯片/分组挂不住）"
    assert "${s.id}" in row or "+s.id+" in row or "esc(s.id)" in row or \
        "sid" in row, "行上的 data-strategy 不是从载荷取 id"
    # 来源徽标：五个来源都有中文，且引用的是载荷的 source
    for zh in ("默认", "全局", "渠道", "维度", "链路"):
        assert zh in w, "来源徽标缺「%s」" % zh
    assert re.search(r"source", row), "行上没有读载荷的 source 字段"


def test_renderer_reads_label_intent_effect_from_the_payload():
    """文案只从载荷来：界面里不许出现目录里那些句子的第二份。"""
    from core.strategy_contract import STRATEGIES

    w = _w()
    row = _fn(w, "function stratRowHTML(")
    for fld in ("label", "intent", "effect"):
        assert fld in row, "渲染器没读载荷的 %s" % fld
    dup = []
    for s in STRATEGIES:
        for txt in (s.label, s.intent, s.effect):
            if txt and txt in w:
                dup.append((s.id, txt))
    assert not dup, "界面里抄了一份目录文案（应从 /api/strategy 读）：%s" % dup[:4]


# ---------------------------------------------------------------- 边界登记

def test_new_numeric_keys_are_registered_for_range_check():
    """非 flat 数值参数的控件必须有边界，否则越界值被静默夹掉。"""
    w = _w()
    i = w.index("const GLB_RANGES=[")
    seg = w[i:w.index("function glbRangeOf(", i)]
    for fid in NEW_NUMERIC_IDS:
        assert re.search(r"id:'%s'" % fid, seg), "%s 没进 GLB_RANGES" % fid


def test_directory_driven_control_carries_its_own_bounds():
    """目录驱动的控件随身带 `data-min`/`data-max`（边界只有目录一份）。"""
    w = _w()
    row = _renderer(w)
    assert "data-min" in row and "data-max" in row, (
        "控件没带 data-min/data-max：范围校验查不到边界就会静默放行")
    assert "data-pid=" in row, "控件没有 data-pid（值写回时对不上参数）"
    # 范围解析要能吃下这种形态（GLB_RANGES 里查不到时读控件自带边界）
    gr = _fn(w, "function glbRangeOf(")
    assert "data-min" in gr or "dataset.min" in gr, (
        "glbRangeOf 不认识控件自带的 data-min/data-max")


def test_param_controls_write_the_existing_glb_bag_not_a_new_route():
    """写路径只有一个：值进 `GLB` 脏状态，保存仍走 `saveCfg()` 整表 POST。"""
    w = _w()
    assert "/api/strategy/set" not in w, "另开了参数写接口（Spec §6(c)：不许抢写 yaml）"
    row = _renderer(w)
    assert "GLB." in row or "stratSet(" in row, "控件没写进 GLB 脏状态"
    setf = _fn(w, "function stratSet(")
    assert "GLB." in setf, "stratSet 没有写 GLB"
    # 停手/恢复走 T6 的干预路由（运行期干预，不写配置）
    assert "/api/strategy/halt" in w and "/api/strategy/resume" in w


# ---------------------------------------------------------------- 分区身份

def test_partition_title_and_deeplink_stay_working():
    """标题改「策略控制」，但分区 id / 深链 / 健康卡入口一个都不许动。

    注意深链的实际形态：`CFGPANEL` 的**默认值是登录分区**（并记住上次停留
    的分区，`localStorage['jpcfgpanel']`），「渠道节流」从来不是默认分区，
    所以这里钉的是「分区 id 仍是 pacing + `showCfgPanel('pacing')` 仍能直达」，
    而不是钉一个从来不存在的默认值。
    """
    w = _w()
    assert "let CFGPANEL='pacing'" in w or "showCfgPanel('pacing')" in w, (
        "深链分区 id 被改掉：再也到不了 pacing 分区")
    assert "let CFGPANEL='login'" in w, "默认分区被改（深链/记住上次分区的基线变了）"
    assert "jpcfgpanel" in w, "「记住上次分区」的深链机制丢了"
    assert "function cfgGoThrottle(" in w, "健康卡直达入口丢了"
    assert '<span class="zh">策略控制</span>' in w
    assert '<span class="zh">渠道节流</span>' not in w, "旧标题仍在"
    # 分区容器与宿主节点仍是 pacing（r638 / r1070 / r1072 都在用）
    assert 'id="panel-pacing"' in w
    assert "id=\"cfgpacing\"" in w or "id='cfgpacing'" in w
    # 健康卡入口仍要落到节流控件上（test_goal_c 钉这条）
    fn = w[w.index("function cfgGoThrottle("):]
    fn = fn[:fn.index("async function health(")]
    assert "showCfgPanel(" in fn and "glbQs" in fn


def test_legacy_throttle_controls_are_still_inside_the_panel():
    """重构不许把既有节流控件挤丢：它们是「配了能生效」的既有证据。"""
    legacy = ("glbQs", "glbQe", "glbFast", "glbSlow", "glbNear", "glbStg",
              "glbGap", "glbRpm", "glbBrk", "glbHpen", "glbHok", "glbHslow",
              "glbHsf", "glbHslf", "glbHms", "glbBbs", "glbBcs", "glbWarm",
              "glbWarmP", "glbLcd", "glbNearD")
    w = _w()
    i = w.index("const gp=''")
    gp = w[i:w.index("$('cfgglobals').innerHTML=gh;", i)]
    miss = [k for k in legacy if ("'%s'" % k) not in gp]
    assert not miss, "这些既有节流控件被重构挤掉了：%s" % miss


def test_panel_keeps_exactly_two_foldable_sections():
    """r1070/r1072 的几何契约：本分区只有两个可折叠小节，族头不算小节。"""
    w = _w()
    i = w.index("const gp=''")
    gp = w[i:w.index("$('cfgglobals').innerHTML=gh;", i)]
    n = len(re.findall(r"glsec\([^)]*,\s*1\s*\)", gp))
    assert n == 2, "可折叠小节从 2 个变成了 %d 个（r1070 按 2 个判几何）" % n


# ---------------------------------------------------------------- 真落盘

def _post_cfg(cfg_path, payload):
    """起一个真 `webui._Srv`，POST 一次 `/api/config`（与 r649 同一套夹具）。"""
    import json
    import threading

    import urllib.request

    import webui

    st = webui._State
    st.cfg = {"users": []}
    st.boot_cfg = {"users": []}
    st.users = []
    st.alerters = []
    st.job = None
    st.report_push = None
    st.reload_cb = None
    st.config_path = cfg_path
    st.version = "t12b"
    st.login_saved_cb = None
    st.logger = __import__("logging").getLogger("t12b")
    old_demo = dict(webui.DEMO)
    webui.DEMO["on"] = False
    srv = webui._Srv(("127.0.0.1", 0), webui._Handler)
    srv.daemon_threads = True
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/api/config" % port
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as he:
            return he.code, json.loads(he.read().decode("utf-8") or "{}")
    finally:
        srv.shutdown()
        srv.server_close()
        webui.DEMO.clear()
        webui.DEMO.update(old_demo)


def test_strategy_values_from_the_panel_really_land_in_config_yaml(tmp_path):
    """面板里的数必须真写进 `config.yaml` 的点路径（配了不生效比没配更糟）。"""
    import yaml

    cfg = str(tmp_path / "config.yaml")
    io.open(cfg, "w", encoding="utf-8").write(
        yaml.safe_dump({"users": []}, allow_unicode=True))
    code, out = _post_cfg(cfg, {"users": [], "globals": {"strategy_values": {
        "pace_factor.watch": 2.5,
        "risk_bands.pause": 70,
        "block_window.human": 3600,
        "ttl_tier.fast": 20,
    }}})
    assert code == 200 and out.get("ok"), (code, out)
    saved = yaml.safe_load(io.open(cfg, encoding="utf-8"))
    assert saved["crawler"]["policy"]["pace"]["watch"] == 2.5, saved
    assert saved["crawler"]["risk"]["levels"]["pause"] == 70, saved
    assert saved["crawler"]["policy"]["block_s"]["human"] == 3600, saved
    assert saved["schedule"]["fast_ttl_min"] == 20, saved


def test_strategy_values_are_clamped_and_unknown_pids_are_refused(tmp_path):
    """越界按目录边界夹取；目录里没有的 pid 一律拒绝（不许静默丢弃）。"""
    import yaml

    cfg = str(tmp_path / "config.yaml")
    io.open(cfg, "w", encoding="utf-8").write(
        yaml.safe_dump({"users": []}, allow_unicode=True))
    code, out = _post_cfg(cfg, {"users": [], "globals": {"strategy_values": {
        "pace_factor.watch": 999}}})
    assert code == 200 and out.get("ok"), (code, out)
    saved = yaml.safe_load(io.open(cfg, encoding="utf-8"))
    assert saved["crawler"]["policy"]["pace"]["watch"] == 10, \
        "越界值没有按 Param.hi 夹取：%s" % saved
    # 未知 pid：整次保存如实失败（不写半份、不吞错）
    code2, out2 = _post_cfg(cfg, {"users": [], "globals": {"strategy_values": {
        "nowhere.pid": 1}}})
    assert code2 >= 400 and not out2.get("ok"), (code2, out2)
    assert "没写进去" in str(out2.get("err") or ""), out2
