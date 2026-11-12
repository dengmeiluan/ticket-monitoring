# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_health_by_dimension.py
- tests/test_r1063_health_row_scope.py
- tests/test_r1063_health_scope_paths.py
- tests/test_r1063_health_scoped.py
- tests/test_r1063_health_strategy_strip.py
- tests/test_r1063_pace_readout_dedup.py
- tests/test_r355_health_semantics.py
- tests/test_r489_health_five_dims_rendered.py
- tests/test_v194_health_geo.py
- tests/test_v295_health_ui.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import json
import os
import pytest
import re
import sys
import tempfile
import threading

from core import strategy_params as sp
from core.pacing import Pacing
from core.storage import PriceStorage, dim_of_path
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


# ---- merged from tests/test_webui_health.py ----

# ---- merged from tests/test_r1063_health_by_dimension.py ----

@pytest.fixture()
def ps():
    d = tempfile.mkdtemp()
    return PriceStorage(os.path.join(d, "t.db"))


def _seed(ps, n=6):
    """同一渠道：日历通路全失败、PC（明细）全成功。"""
    for i in range(n):
        ps.save_fetch_path("ctrip", "SHA", "BJS", "2027-01-29", "日历",
                           "error", attempt_id="cal-%d" % i)
        ps.save_fetch_path("ctrip", "SHA", "BJS", "2027-01-30", "PC",
                           "ok", rows=3, attempt_id="det-%d" % i)


def test_dimension_mapping_is_single_source():
    """维度归属只有一份映射：通路名 → 维度。"""
    assert dim_of_path("日历") == "calendar"
    assert dim_of_path("窗历") == "calendar"
    assert dim_of_path("app-calendar") == "calendar"
    assert dim_of_path("往返") == "round_trip"
    assert dim_of_path("TRIP") == "round_trip"
    assert dim_of_path("多程") == "multi_city"
    assert dim_of_path("low-fare") == "low_fare"
    # 其余一律 detail（含 PC/H5/API/App 及各细段）
    for p in ("PC", "H5", "H5/API", "API", "QUERY", "app-list", "app-date"):
        assert dim_of_path(p) == "detail", p
    assert dim_of_path("") == "detail"


def test_path_stats_exposes_dimension_nodes(ps):
    _seed(ps)
    node = ps.path_stats(24)["ctrip"]
    dims = node.get("dims") or {}
    assert set(dims) >= {"calendar", "detail"}, sorted(dims)
    assert dims["calendar"]["attempts"] == 6
    assert dims["calendar"]["ok"] == 0
    assert dims["calendar"]["rate"] == 0.0
    assert dims["detail"]["attempts"] == 6
    assert dims["detail"]["ok"] == 6
    assert dims["detail"]["rate"] == 1.0
    # 渠道级仍是两维之和（今天的口径不变）
    assert node["attempts"] == 12
    assert node["ok"] == 6


def test_dimension_query_rate_counts_once_per_dimension(ps):
    """查询口径在维度内同样成立：一次查询一条路径出数即算该维度成功。"""
    _seed(ps)
    node = ps.path_stats(24)["ctrip"]
    cal = node["dims"]["calendar"]
    det = node["dims"]["detail"]
    assert (cal["query_attempts"], cal["query_ok"]) == (6, 0)
    assert (det["query_attempts"], det["query_ok"]) == (6, 6)


def _pacing_with_baseline(minutes_ago=30):
    """造一个带基线的 Pacing：假时钟 + 30 分钟前采过一条贴近阈值的价。

    `plan_query` 的档位由「距上次采集多久」决定（TTL 内 skip / 过了就 fast），
    而成功率保护的作用是**把 TTL 拉长**——所以要看它生效，必须有一条基线，
    否则永远返回「无历史基线 → fast」，测不出惩罚。
    """
    from core.pacing import Pacing

    now = 1_000_000.0
    pac = Pacing({"schedule": {"fast_ttl_min": 15, "slow_ttl_min": 120,
                               "near_ratio": 0.15}}, clock=lambda: now)
    pac.seed_fetch("ctrip", ("SHA", "BJS", "2027-01-29"), 1000.0,
                   now - minutes_ago * 60)
    return pac, now


def test_dimension_penalty_does_not_leak_to_other_dimensions():
    """日历烂（×3）→ 日历查询被 skip；明细好（×1）→ 明细查询照常 fast。"""
    from core import strategy_params as sp

    sp.set_config({})
    try:
        pac, _now = _pacing_with_baseline(minutes_ago=30)
        pac.set_health("ctrip", 0.05, 10, dim="calendar")
        pac.set_health("ctrip", 0.95, 10, dim="detail")
        cal, why_cal = pac.plan_query("ctrip", ("SHA", "BJS", "2027-01-29"),
                                      threshold=1000.0, dim="calendar")
        det, why_det = pac.plan_query("ctrip", ("SHA", "BJS", "2027-01-29"),
                                      threshold=1000.0, dim="detail")
        assert cal == "skip", (cal, why_cal)      # 15×3=45 分钟 TTL，30 分钟内
        assert det == "fast", (det, why_det)      # 15 分钟 TTL 已过
    finally:
        sp.invalidate()


def test_thin_dimension_falls_back_to_channel_level():
    """维度样本不足（2 条 < 下限 5）时回落渠道级：不让噪声决定速度。"""
    from core import strategy_params as sp

    sp.set_config({})
    try:
        pac, _now = _pacing_with_baseline(minutes_ago=30)
        pac.set_health("ctrip", 0.05, 10)                 # 渠道级烂 → ×3
        pac.set_health("ctrip", 0.95, 2, dim="detail")    # 维度只有 2 条样本
        det, why = pac.plan_query("ctrip", ("SHA", "BJS", "2027-01-29"),
                                  threshold=1000.0, dim="detail")
        assert det == "skip", ("维度样本不足却没回落渠道级", det, why)
    finally:
        sp.invalidate()


def test_channel_level_key_still_present_in_snapshot():
    """快照仍按渠道暴露 health（界面/门禁读这个形状），维度读数另挂 health_dims。"""
    from core import strategy_params as sp
    from core.pacing import Pacing

    sp.set_config({})
    try:
        pac = Pacing({})
        pac.set_health("ctrip", 0.5, 10)
        pac.set_health("ctrip", 0.1, 10, dim="calendar")
        snap = pac.snapshot()
        ch = snap["channels"].get("ctrip") or {}
        assert (ch.get("health") or {}).get("rate") == 0.5
        assert "calendar" in (ch.get("health_dims") or {})
    finally:
        sp.invalidate()


def test_the_pipeline_actually_wires_dimension_health():
    """接线钉子：`main.py` 必须真的把维度级读数喂进去、并带 dim 查 TTL。

    只钉「调用形态在」，不重复它的判据——判据在上面几条行为用例里。
    少了这两处，`path_stats` 出了 `dims` 也没人用，等于维度级降频是空转。
    """
    import io
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = io.open(os.path.join(root, "main.py"), encoding="utf-8").read()
    assert 'for _d, _dn in (_node.get("dims") or {}).items():' in src, \
        "main.py 没有遍历 path_stats 的 dims（维度级读数没人用）"
    assert "dim=_d" in src, "main.py 没把维度传给 set_health"
    assert "days_ahead=_days, dim=dim" in src, \
        "main.py 没把维度传给 plan_query（TTL 仍按渠道级降频）"
    # r1063 T16：链路级
    assert 'for _pth, _pn in (_node.get("paths") or {}).items():' in src, \
        "main.py 没有遍历 path_stats 的 paths（链路级读数没人用）"
    assert "path=_pth" in src, "main.py 没把链路传给 set_health"


# ---------------- 链路级（r1063 T16）：H5/API、PC、API 各自独立 ----------------

def test_path_level_penalty_does_not_leak_to_sibling_paths():
    """同一维度下的两条链路互不连坐：H5/API 烂，PC 照常。"""
    from core import strategy_params as sp

    sp.set_config({})
    try:
        pac, _now = _pacing_with_baseline(minutes_ago=30)
        pac.set_health("ctrip", 0.02, 10, dim="detail", path="H5/API")
        pac.set_health("ctrip", 0.98, 10, dim="detail", path="PC")
        assert pac._health_penalty("ctrip", "detail", "H5/API") == 3.0
        assert pac._health_penalty("ctrip", "detail", "PC") == 1.0
    finally:
        sp.invalidate()


def test_path_penalty_scales_only_that_paths_gate_wait():
    """`gate_path` 的限速只按该链路自己的成功率放大。"""
    from core import strategy_params as sp
    from core.pacing import Pacing

    sp.set_config({"crawler": {"rate": {"min_gap_s": 10}}})
    try:
        now = 1_000_000.0
        pac = Pacing({"crawler": {"rate": {"min_gap_s": 10}},
                      "schedule": {"fast_ttl_min": 15, "slow_ttl_min": 120}},
                     clock=lambda: now)
        # 只让 H5/API 这一条链路"刚发过"，其余链路没发过
        pac.record("ctrip", path="H5/API")
        pac.set_health("ctrip", 0.02, 10, dim="detail", path="H5/API")
        _ok, wait_bad, why = pac.gate_path("ctrip", "detail", "H5/API")
        _ok2, wait_ok, why_ok = pac.gate_path("ctrip", "detail", "PC")
        # 同一渠道的令牌桶是共享的（`record(path=…)` 同时记渠道桶，那是
        # per_minute 的渠道上限），所以 PC 也会等渠道级的 10s——这**不是**
        # 连坐；连坐会表现为 PC 也被乘上 3 倍。
        assert wait_bad >= 10 * 3.0 - 1e-6, ("链路级降频没进限速", wait_bad, why)
        assert "成功率保护" in why, why
        assert wait_ok <= 10.0 + 1e-6, ("同维度的另一条链路被乘了倍数", wait_ok, why_ok)
        assert "成功率保护" not in why_ok, why_ok
    finally:
        sp.invalidate()


def test_snapshot_exposes_path_level_readings():
    """快照给策略面板逐链路读数：键是 `维度/通路`。"""
    from core import strategy_params as sp
    from core.pacing import Pacing

    sp.set_config({})
    try:
        pac = Pacing({})
        pac.set_health("ctrip", 0.02, 10, dim="detail", path="H5/API")
        pac.set_health("ctrip", 0.9, 10, dim="calendar", path="日历")
        ch = (pac.snapshot()["channels"] or {}).get("ctrip") or {}
        hp = ch.get("health_paths") or {}
        assert "detail/H5/API" in hp, sorted(hp)
        assert hp["detail/H5/API"]["penalty"] == 3.0
        assert hp["calendar/日历"]["penalty"] == 1.0
    finally:
        sp.invalidate()


# ---- merged from tests/test_r1063_health_row_scope.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _js():
    return webui_full_src()


def test_health_row_renders_per_scope_penalty():
    """行内必须把 snapshot 的逐作用域倍数渲染出来（不是只下发不消费）。"""
    js = _js()
    seg = js[js.index("const _pen2=(()=>{"):]
    seg = seg[:1400]
    assert "v.health_paths" in seg and "v.health_dims" in seg, seg[:200]
    assert ".penalty" in seg
    # 只列 >1 的；没有降频时返回空串（不占位，几何不变）
    assert "if(p>1)" in seg and "return ''" in seg
    # 消费点真的在行模板里
    assert "'<i class=\"e2k\">降频</i>'+" in js, "行模板没挂降频读数"


def test_scope_readout_dedupes_dimension_when_path_exists():
    """同维度已有链路读数时不重复列维度（与策略面板同一去重规则）。"""
    js = _js()
    seg = js[js.index("const _pen2=(()=>{"):][:1400]
    assert "split('/')[0]===kk" in seg, "维度与链路会重复列同一件事"


def test_scope_readout_adds_no_new_css_or_tokens():
    """不新增样式：复用既有 .e2/.e2k（微信扁平铁律：禁止新视觉、新字号档）。"""
    js = _js()
    seg = js[js.index("const _pen2=(()=>{"):][:1400]
    for banned in ("#", "style=", "font-size", "border", "radius"):
        assert banned not in seg, ("_pen2 里出现了样式（%s）" % banned)


# ---- merged from tests/test_r1063_health_scope_paths.py ----

def _pacing(clock=None):
    from core.pacing import Pacing
    return Pacing({"crawler": {"rate": {"min_gap_s": 10}},
                   "schedule": {"fast_ttl_min": 15, "slow_ttl_min": 120,
                                "near_ratio": 0.15}},
                  clock=(clock or (lambda: 1_000_000.0)))


@pytest.fixture(autouse=True)
def _clean_params():
    from core import strategy_params as sp
    sp.invalidate()
    yield
    sp.invalidate()


# ---------------- 单一状态 ----------------

def test_health_state_is_one_store_with_a_compat_view():
    """渠道级读数仍能从 `_health[plat]` 读到（老契约），但内部只有一份状态。"""
    pac = _pacing()
    pac.set_health("ctrip", 0.5, 10)
    pac.set_health("ctrip", 0.1, 10, dim="calendar")
    pac.set_health("ctrip", 0.02, 10, dim="detail", path="H5/API")
    assert pac._health["ctrip"]["rate"] == 0.5          # 兼容视图：只含渠道级
    keys = sorted(k for k in pac._health_all)
    assert ("ctrip", "", "") in keys
    assert ("ctrip", "calendar", "") in keys
    assert ("ctrip", "detail", "H5/API") in keys
    # 兼容视图是**投影**，不是第二份状态：往它写不会改真状态
    pac._health["ctrip"]["rate"] = 0.99
    assert pac._health["ctrip"]["rate"] == 0.5


# ---------------- 逐级回落 ----------------

def test_precedence_path_over_dimension_over_channel():
    pac = _pacing()
    pac.set_health("ctrip", 0.05, 10)                        # 渠道 ×3
    pac.set_health("ctrip", 0.5, 10, dim="calendar")         # 维度 ×1.5
    pac.set_health("ctrip", 0.02, 10, dim="calendar",
                   path="日历")                              # 链路 ×3
    assert pac._health_penalty("ctrip", "calendar", "日历") == 3.0
    assert pac._health_penalty("ctrip", "calendar", "窗历") == 1.5   # 回落维度
    assert pac._health_penalty("ctrip", "detail", "PC") == 3.0       # 回落渠道


def test_thin_path_sample_falls_back_to_dimension_then_channel():
    pac = _pacing()
    pac.set_health("ctrip", 0.05, 10)                        # 渠道 ×3
    pac.set_health("ctrip", 0.02, 2, dim="detail", path="H5/API")   # 样本不足
    assert pac._health_penalty("ctrip", "detail", "H5/API") == 3.0


# ---------------- 精准控制：只压那一条 ----------------

def test_gate_path_scales_only_the_bad_links_wait():
    from core import strategy_params as sp
    # 限速基数走参数层（`rate_min_gap` 的读点就是 `sp.resolve`），
    # 所以这里显式装一份配置，别依赖出厂默认 3s。
    sp.set_config({"crawler": {"rate": {"min_gap_s": 10}}})
    pac = _pacing()
    pac.record("ctrip", path="H5/API")      # 让这条链路刚发过、需要等
    pac.set_health("ctrip", 0.02, 10, dim="detail", path="H5/API")
    _ok, bad, why = pac.gate_path("ctrip", "detail", "H5/API")
    _ok2, ok_wait, why2 = pac.gate_path("ctrip", "detail", "PC")
    assert bad >= 30.0 - 1e-6, (bad, why)          # 10s × 3
    assert "成功率保护" in why
    assert ok_wait <= 10.0 + 1e-6, (ok_wait, why2)  # 只等渠道级 10s，不被乘
    assert "成功率保护" not in why2


# ---------------- 统一状态：面板读数来自同一份 snapshot ----------------

def test_snapshot_carries_channel_dimension_and_path_scopes():
    pac = _pacing()
    pac.set_health("ctrip", 0.5, 10)
    pac.set_health("ctrip", 0.1, 10, dim="calendar")
    pac.set_health("ctrip", 0.02, 10, dim="detail", path="H5/API")
    ch = pac.snapshot()["channels"]["ctrip"]
    assert (ch.get("health") or {}).get("rate") == 0.5
    assert "calendar" in (ch.get("health_dims") or {})
    assert "detail/H5/API" in (ch.get("health_paths") or {})


def test_strategy_payload_exposes_scoped_health_and_row_renders_it():
    """面板行必须能看到「哪一条被压到几倍」，且判据是目录的 scope 字段。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = webui_full_src()
    # 载荷：从 snapshot 取，不在 webui 里另算
    assert 'out["health"] = health' in src
    assert '_ch.get("health_paths")' in src
    # 渲染：按 scope 判定（不写死策略 id）
    fn = src[src.index("function stratScopeHTML(s){"):]
    fn = fn[:fn.index("function stratRowHTML(s){")]
    assert "indexOf('path')" in fn and "indexOf('dimension')" in fn
    assert "health_penalty" not in fn, "写死策略 id 就是第二份声明"
    assert "stratScopeHTML(s)" in src, "行模板没挂上逐作用域读数"


# ---- merged from tests/test_r1063_health_scoped.py ----

CFG = {"crawler": {"health_min_samples": 5, "health_ok_ratio": 0.7,
                   "health_slow_ratio": 0.4, "health_slow_factor": 1.5,
                   "health_slowest_factor": 3.0}}


@pytest.fixture(autouse=True)
def _clean():
    sp.invalidate()
    yield
    sp.invalidate()


def _p(overrides=None):
    cfg = {"crawler": dict(CFG["crawler"])}
    if overrides:
        cfg["crawler"]["strategy_overrides"] = overrides
    sp.set_config(cfg)
    return Pacing(dict(CFG))


def _pen(p, plat, rate=0.2, n=10):
    p.set_health(plat, rate, n)
    return (p.snapshot()["channels"].get(plat) or {}).get("health", {}).get(
        "penalty")


def test_slowest_factor_follows_the_channel_override():
    p = _p({"fliggy": {"health_penalty.slowest_factor": 6.0}})
    assert _pen(p, "fliggy") == 6.0
    assert _pen(p, "ctrip") == 3.0        # 别家不受影响


def test_ok_ratio_override_changes_the_band():
    """把 ok 线抬到 0.95 → 0.8 的成功率也算"差"，该降频。"""
    p = _p({"fliggy": {"health_penalty.ok_ratio": 0.95}})
    assert _pen(p, "fliggy", rate=0.8) == 1.5      # 落进 slow 档
    assert _pen(p, "ctrip", rate=0.8) == 1.0       # 全局 0.7 线 → 算好


def test_min_samples_override_gates_the_judgement():
    """样本门槛按渠道定：fliggy 要求 20 条，5 条样本时**不下判**。"""
    p = _p({"fliggy": {"health_penalty.min_samples": 20}})
    assert _pen(p, "fliggy", rate=0.1, n=5) == 1.0
    assert _pen(p, "ctrip", rate=0.1, n=5) == 3.0


def test_path_scope_reaches_the_thresholds():
    p = _p({"ctrip/intl/H5/API": {"health_penalty.slowest_factor": 8.0}})
    p.set_health("ctrip", 0.1, 10, dim="intl", path="H5/API")
    p.set_health("ctrip", 0.1, 10, dim="intl", path="PC")
    ch = p.snapshot()["channels"]["ctrip"]
    assert ch["health_paths"]["intl/H5/API"]["penalty"] == 8.0
    assert ch["health_paths"]["intl/PC"]["penalty"] == 3.0


def test_no_override_keeps_global_behaviour():
    p = _p()
    assert _pen(p, "fliggy", rate=0.6) == 1.5   # 0.4 ≤ 0.6 < 0.7 → slow
    assert _pen(p, "fliggy", rate=0.8) == 1.0   # ≥ 0.7 → 不降频


def test_read_points_are_present():
    import io
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = io.open(os.path.join(root, "core", "pacing.py"),
                  encoding="utf-8").read()
    for pid in ("health_penalty.min_samples", "health_penalty.ok_ratio",
                "health_penalty.slow_ratio", "health_penalty.slow_factor",
                "health_penalty.slowest_factor"):
        assert 'self._scoped("%s"' % pid in src, pid


# ---- merged from tests/test_r1063_health_strategy_strip.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _w():
    return webui_full_src()


def _fn(src, decl):
    """取一个顶层函数（或 `async function`）的源码段。

    到下一个顶层 `function` / `async function` / 顶层 `const` / 段落注释为止。
    """
    i = src.index(decl)
    j = len(src)
    for pat in ("\nfunction ", "\nasync function ", "\nconst ", "\n/* ===== "):
        k = src.find(pat, i + len(decl))
        if k > 0:
            j = min(j, k)
    return src[i:j]


def _strip_fn():
    return _fn(_w(), "function paceStripHTML(")


# ---------------------------------------------------------------- 骨架与入口


def test_health_card_renders_a_strategy_strip_with_actions():
    """策略条必须真在健康卡里渲染，且停手/恢复复用同一套接口。"""
    w = _w()
    assert "function paceStripHTML(" in w
    assert 'data-strip="' in w
    assert "function cfgGoStrategy(" in w
    # 停手/恢复必须复用同一套接口，不许另写一条
    assert "/api/strategy/halt" in w and "/api/strategy/resume" in w


def test_strip_chips_are_wechat_flat_and_speak_chinese_short():
    """微信级扁平化 + 可清晰：芯片长在既有家族里，文案是短句，不露裸 id。"""
    w = _w()
    assert ".pchip{" in w, "芯片没自己的扁平样式"
    seg = w[w.index(".pchip{"):][:400]
    assert "background:var(--r-surface)" in seg or "var(--r-blue-soft)" in seg
    assert "border-radius:var(--pill)" in seg or "border-radius:12px" in seg
    assert "border:0" in seg.replace(" ", "") or "border:none" in seg
    # 芯片文案来自策略目录的 label（≤20 字），不是拼 id
    fn = w[w.index("function paceStripHTML("):][:1500]
    assert "s.label" in fn or "st.label" in fn, "芯片没消费目录的 label"


def test_strip_sits_inside_the_channel_row_not_beside_it():
    """策略条是渠道行的一部分：.pace-ch 的直接子节点仍是 10 个 .pace-row。

    r1058 的窄档裁量按 `#paceBox .pace-ch:not(.all)>.pace-row:nth-child(n+5)`
    数行——策略条若另起兄弟节点，行序号会整体错位、前 4 行之外被误藏。
    """
    w = _w()
    fn = _fn(w, "async function loadPacing(")
    assert "+paceStripHTML(k)" in fn, "loadPacing 没在渠道行里插策略条"
    # 插在行内（`</span>` 之后、行尾 `</div>` 之前），不是另起一行 div
    i = fn.index("+paceStripHTML(k)")
    tail = fn[i:i + 120]
    assert "</div>" in tail, tail
    assert "'<div class=\"pace-row\"" in fn[:i], "找不到渠道行模板"
    assert '#paceBox .pace-row .pstrip{grid-column:1/-1' in w, \
        "策略条没有铺满整行（会被挤进 4 列里）"


# ---------------------------------------------------------------- 该列谁

def test_strip_only_lists_non_default_or_channel_scoped_strategies():
    """全默认 → 一条都不列；渠道覆盖的项只出现在那个渠道的策略条上。"""
    import webui
    from core import strategy_params as sp

    old = sp.get_config()
    try:
        sp.invalidate()
        rows = webui._strategy_strip_rows(["ctrip"])
        assert rows["ctrip"]["strategies"] == [], (
            "全默认时不该有任何芯片：%s" % rows)

        sp.set_config({"crawler": {"strategy_overrides": {
            "ctrip": {"rate_per_minute.value": 7},
            "qunar": {"ttl_tier.fast": 30}}}})
        got = webui._strategy_strip_rows(["ctrip", "qunar"])

        c_ids = {r["id"]: r for r in got["ctrip"]["strategies"]}
        assert "rate_per_minute" in c_ids, got["ctrip"]
        assert c_ids["rate_per_minute"]["state"] == "cover"
        assert c_ids["rate_per_minute"]["src"] == "channel"
        assert "ttl_tier" not in c_ids, "别家渠道的覆盖跑到这一行了"
        # 芯片文案来自目录 label（≤20 字），不是拼 id
        assert c_ids["rate_per_minute"]["label"]
        assert len(c_ids["rate_per_minute"]["label"]) <= 20
        assert c_ids["rate_per_minute"]["id"] not in c_ids["rate_per_minute"]["label"]

        q_ids = {r["id"]: r for r in got["qunar"]["strategies"]}
        assert "ttl_tier" in q_ids and "rate_per_minute" not in q_ids
    finally:
        if isinstance(old, dict) and old:
            sp.set_config(old)
        else:
            sp.invalidate()


def test_strip_is_capped_at_six_and_folds_the_rest_into_more():
    w = _w()
    assert "PACE_STRIP_MAX=6" in w, "没有「最多 6 颗」的上限"
    fn = _strip_fn()
    assert "PACE_STRIP_MAX" in fn, "上限没用在策略条上"
    assert "更多 " in fn, "超出的芯片没折进「更多」"
    assert "paceStripMore(" in w, "「更多」点不开"


# ---------------------------------------------------------------- 可区分

def test_halted_channel_reads_manual_halt_distinct_from_auto_cooldown():
    """人工停手必须与自动冷却**一眼可分**：不同底色 + 剩余分钟数。"""
    w = _w()
    fn = _strip_fn()
    assert "人工停手 " in fn, "停手中的渠道没写「人工停手 N 分钟」"
    assert "pc-halt" in fn and "pc-auto" in fn, "人工/自动共用一个颜色"
    # 剩余分钟由 `until` 现算（10 秒一拍的轮询跟不上倒计时走字）
    assert "halt.until" in fn and "60000" in fn, "剩余时间不是按 until 现算的"
    for cls in (".pchip.pc-halt{", ".pchip.pc-auto{", ".pchip.pc-cover{"):
        assert cls in w, "三态缺独立底色规则：%s" % cls
    # 停手 chip 有自己的颜色 token，不许和自动档撞色
    a = w[w.index(".pchip.pc-halt{"):]
    a = a[:a.index("}")]
    b = w[w.index(".pchip.pc-auto{"):]
    b = b[:b.index("}")]
    assert a.strip() != b.strip(), "人工停手与自动处置仍是同一套配色"


def test_payload_sells_manual_halt_and_per_channel_rows(tmp_path, monkeypatch):
    """载荷必须直出「人工停手」与逐渠道策略行——界面不许自己猜。

    真落盘一次人工停手（`core.policy.set_halt` 写 `strategy_halt.json`），再问
    一次载荷：那个渠道必须带 `halt`（含策略 id、中文名、到期时刻），且建议改成
    「恢复」；别的渠道不许被顺带标成停手。
    """
    import inspect
    import types

    import webui
    from core import policy

    body = inspect.getsource(webui._strategy_payload)
    assert "_strategy_strip_rows(" in body, "载荷没有逐渠道策略条"
    assert 'out["channels"]' in body or "out['channels']" in body, \
        "载荷没把逐渠道策略条售出"

    monkeypatch.setattr(webui, "_policy_engine",
                        lambda plat="": types.SimpleNamespace(
                            base_dir=str(tmp_path)))
    monkeypatch.setattr(webui, "_strategy_storage",
                        lambda: (_ for _ in ()).throw(RuntimeError("台账不可用")))
    rec = policy.set_halt(str(tmp_path), "ctrip", 15, "人工停手 15 分钟")
    assert rec is not False, "停手没落盘（夹具坏了，不是被测代码的锅）"

    out = webui._strategy_payload()
    assert out["ok"] is True, out.get("errors")
    ch = (out.get("channels") or {}).get("ctrip") or {}
    halt = ch.get("halt") or {}
    assert halt.get("id"), "停手渠道没带策略 id（芯片点不回配置页）：%s" % ch
    assert halt.get("label"), "停手芯片缺中文名（会露裸 id）"
    assert int(halt.get("left_s") or 0) > 0
    assert float(halt.get("until") or 0) > 0, "没有到期时刻，界面算不出剩余分钟"
    tip = ch.get("tip") or {}
    assert tip.get("action") == "resume", "停手中的渠道没有先劝恢复：%s" % tip
    assert tip.get("route") == "/api/strategy/resume", tip
    assert ((out.get("channels") or {}).get("qunar") or {}).get("halt") is None, \
        "停手串到别的渠道上了"
    # 停手归哪条策略由目录派生，不是写死一个 id
    owner = webui._strategy_halt_owner()
    assert owner.get("id") == halt.get("id"), (owner, halt)


# ---------------------------------------------------------------- 一键停手


def test_halt_and_resume_buttons_tell_you_they_are_in_flight():
    """在途必须**改文案**（不是只置灰），成功后回读载荷。"""
    w = _w()
    halt = _fn(w, "async function paceHalt(")
    assert "/api/strategy/halt" in halt
    assert "停手中…" in halt, "在途没改文案"
    assert "btn.textContent=" in halt, "在途没改文案"
    assert "loadPacing(true)" in halt, "成功后没回读载荷"
    assert "minutes:15" in halt.replace(" ", ""), "默认停手分钟数不是 15"

    resume = _fn(w, "async function paceResume(")
    assert "/api/strategy/resume" in resume
    assert "恢复中…" in resume
    assert "loadPacing(true)" in resume

    fn = _strip_fn()
    assert "paceHalt(this" in fn and "paceResume(this" in fn, \
        "渠道行上没有停手/恢复按钮"


# ---------------------------------------------------------------- 建议行


def test_advice_row_button_lands_on_a_real_handler():
    """`tip` 的动作有真路由 → 必须有按钮，且按钮落到真实处理函数。"""
    from core.strategy_advice import ROUTES

    w = _w()
    i = w.index("const PACE_ADVH={")
    j = w.index("};", i)
    table = dict(re.findall(r"(\w+):'(\w+)'", w[i:j]))
    routed = {a for a, r in ROUTES.items() if str(r).strip()}
    missing = sorted(routed - set(table))
    assert not missing, "这些有路由的动作在健康卡里没有落点：%s" % missing
    # 没有路由的动作（换身份 / 无需动作）不许硬塞按钮
    assert "rotate" not in table, "换身份没有执行入口，不许出按钮"

    for act, handler in table.items():
        assert ("function %s(" % handler) in w or \
               ("async function %s(" % handler) in w, \
               "动作 %s 指向的 %s() 不存在（点了没落点）" % (act, handler)

    go = _fn(w, "function paceAdviceGo(")
    for act in table:
        if act == "config":            # 兜底分支就是「去这条策略」
            continue
        assert ("'%s'" % act) in go, "paceAdviceGo 没有分发 %s" % act
    assert "cfgGoStrategy(" in go, "没有兜底落点"


def test_chip_copy_is_the_catalog_label_not_a_literal_table():
    """界面里不许出现 label 的第二份（抄一份的下场是目录改了界面说谎）。"""
    from core.strategy_contract import STRATEGIES

    w = _w()
    dup = [s.id for s in STRATEGIES if s.label and s.label in w]
    assert not dup, "界面里抄了目录 label：%s" % dup[:4]
    fn = _strip_fn()
    assert "esc(s.label)" in fn, "芯片文案不是从载荷 label 来的"
    assert re.search(r"esc\(String\(r\.id", fn) or "data-strip=" in fn


def test_cfg_go_strategy_opens_and_highlights_the_row():
    """点芯片要落到配置页那条策略行上：切分区 + 展开 + 滚动 + 高亮。"""
    w = _w()
    fn = _fn(w, "function cfgGoStrategy(")
    assert "switchView('cfg')" in fn
    assert "showCfgPanel('pacing')" in fn
    assert "data-strategy=" in fn, "没按 data-strategy 找行"
    assert "scrollIntoView" in fn, "没滚动到该行"
    assert "stratFold(" in fn, "没展开该行（收起时点进去看不到控件）"
    assert "hit" in fn, "没有落点高亮"
    assert "#cfgview #cfgpacingRows .srow.hit{" in w, "高亮样式不存在"


# ---------------------------------------------------------------- 扁平几何


def test_strip_geometry_stays_32px_chips_and_28px_buttons():
    """芯片 32px、按钮 ≥28px、零描边、白底：Spec §0.7 的控件节奏。"""
    w = _w()
    seg = w[w.index(".pchip{"):][:400]
    assert "height:32px" in seg, "芯片不是 32px"
    assert "box-shadow" not in seg, "芯片带了投影（卡中卡）"
    pact = w[w.index("#paceBox .pstrip .pact button{"):]
    pact = pact[:pact.index("}")]
    h = int(re.search(r"height:(\d+)px", pact).group(1))
    assert h >= 28, "行内按钮高 %dpx < 28px" % h
    adv = w[w.index("#paceBox .pstrip .pace-adv button{"):]
    adv = adv[:adv.index("}")]
    assert int(re.search(r"height:(\d+)px", adv).group(1)) >= 28
    # 芯片容器必须允许折行：390/320 零横向溢出
    strip = w[w.index("#paceBox .pace-row .pstrip{"):]
    strip = strip[:strip.index("}")]
    assert "flex-wrap:wrap" in strip, "390/320 会横向溢出"
    assert "min-width:0" in strip
    # 复用既有家族：hbadge / snote / chip 都在策略条上出现过
    fn = _strip_fn()
    assert "hbadge" in fn, "来源徽标没复用既有 hbadge 家族"
    assert "snote" in _fn(w, "function paceAdviceHTML("), \
        "建议行没复用既有 snote 家族"
    assert "class=\"chip\"" not in fn and "chip" in fn


def test_strip_css_only_uses_the_panels_three_type_steps():
    """节流面板字号只有 11/12/16 三档（`tools/uitest.py` 逐元素量 computedStyle）。

    r1130：策略条样式随健康页重排分成基础段 + 恢复段，按「选择器规则」
    全仓取样，不再用注释段首尾锚点（锚点会随 CSS 分区迁移而跑偏）。
    """
    w = _w()
    rules = re.findall(r"#paceBox \.(?:pstrip|pchip)[^{]*\{[^}]*\}", w)
    assert len(rules) >= 3, "策略条 CSS 规则不足：%d" % len(rules)
    sizes = set()
    for r in rules:
        sizes |= set(re.findall(r"font-size:(\d+)px", r))
    assert sizes <= {"11", "12", "16"}, "策略条引入了字号档：%s" % sorted(sizes)
    for r in rules:
        assert not re.findall(r"#[0-9a-fA-F]{3,8}", r),             "策略条里硬编码了颜色（走 --r-* 令牌）：%r" % r[:80]


# ---------------------------------------------------------------- 真渲染几何
#
# 上面几条是源码契约；这一条是**渲染级**证据（Spec §4.1 的「可可视化」不接受
# 「代码里有这行」）：真起 demo、把 `/api/strategy` 换成一只有内容的载荷（含
# 渠道覆盖、已停用、人工停手、建议），再逐元素量 computedStyle。
#
# 为什么用 route 拦截而不是往页面里塞全局变量：`loadChannelState()` 在会话槽
# 变化时会 `loadPacing(true)`，那一拍会**强制重读** `/api/strategy`——塞进去的
# 缓存会被真载荷顶掉，量到的就是「全默认」的空条。走真的读路径才量得准。

_STRIP_PAYLOAD = {
    "ok": True, "plats": ["ctrip", "qunar"], "strategies": [],
    "overrides": {}, "halt": {}, "errors": {},
    "channels": {
        "ctrip": {
            "strategies": [
                {"id": "rate_per_minute", "label": "每分钟请求上限",
                 "src": "channel", "state": "cover", "enabled": True},
                {"id": "ttl_tier", "label": "快慢两档抓取间隔",
                 "src": "global", "state": "auto", "enabled": True},
                {"id": "health_penalty", "label": "成功率低自动降频",
                 "src": "global", "state": "auto", "enabled": False},
                {"id": "cadence", "label": "各渠道最少间隔分钟",
                 "src": "global", "state": "auto", "enabled": True},
                {"id": "quiet_window", "label": "静默窗不发起采集",
                 "src": "global", "state": "auto", "enabled": True},
                {"id": "budget", "label": "单次采集请求预算",
                 "src": "global", "state": "auto", "enabled": True},
                {"id": "warmup", "label": "深链前先打首页",
                 "src": "global", "state": "auto", "enabled": True},
                {"id": "proxy_route", "label": "出口与代理选择",
                 "src": "global", "state": "auto", "enabled": True}],
            "halt": None,
            "tip": {"id": "rate_per_minute", "action": "config",
                    "text": "分钟上限用完了就排队：把上限调大再跑",
                    "route": "/api/config"}},
        "qunar": {
            "strategies": [
                {"id": "block_window", "label": "人工停手窗口",
                 "src": "channel", "state": "cover", "enabled": True}],
            "halt": {"id": "block_window", "label": "人工停手窗口",
                     "until": 0, "left_s": 247},
            "tip": {"id": "block_window", "action": "resume",
                    "text": "人工停手生效中：确认过验证后点恢复立刻回到正常节奏",
                    "route": "/api/strategy/resume"}},
    },
}

def _strip_payload():
    """现算 `until`：停手芯片的剩余分钟是按到期时刻现算的，写死 0 会渲染成 1 分钟。"""
    import copy
    import time

    p = copy.deepcopy(_STRIP_PAYLOAD)
    p["channels"]["qunar"]["halt"]["until"] = time.time() + 247
    return p


_MEASURE = r"""() => {
  const box=document.getElementById('paceBox');
  const strips=[...box.querySelectorAll('.pstrip')];
  const vis=e=>e.getBoundingClientRect().height>1;
  const chips=[...box.querySelectorAll('.pstrip .pchip')].filter(vis);
  const fonts=new Set();
  box.querySelectorAll('.pstrip *').forEach(e=>{const v=getComputedStyle(e).fontSize;
    if(v)fonts.add(v);});
  const halt=[...box.querySelectorAll('.pchip.pc-halt')];
  const cover=[...box.querySelectorAll('.pchip.pc-cover')];
  return {strips:strips.length, nchips:chips.length,
    chipH:[...new Set(chips.map(c=>+c.getBoundingClientRect().height.toFixed(1)))],
    actH:[...box.querySelectorAll('.pstrip .pact button')].filter(vis)
      .map(b=>+b.getBoundingClientRect().height.toFixed(1)),
    advH:[...box.querySelectorAll('.pstrip .pace-adv button')].filter(vis)
      .map(b=>+b.getBoundingClientRect().height.toFixed(1)),
    fonts:[...fonts],
    over:document.documentElement.scrollWidth-document.documentElement.clientWidth,
    haltTxt:halt.length?(halt[0].textContent||'').trim():'',
    haltCls:halt.length?halt[0].className:'',
    coverCls:cover.length?cover[0].className:'',
    advTxt:(box.querySelector('.pstrip .pace-adv .txt')||{}).textContent||''};
}"""






# ---- merged from tests/test_r1063_pace_readout_dedup.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = webui_full_src()


def _timeline():
    i = SRC.index("const _timeline=(()=>{")
    j = SRC.index("})();", i)
    return SRC[i:j]


def test_paced_is_not_reported_twice():
    """「节流跳过」只在配额轨图例里出现一次（耗时行是讲时间的）。"""
    seg = _timeline()
    assert "次节流跳过" not in seg, "耗时行又重复报了节流跳过"
    assert "主动未发" in SRC, "图例里也要有同一个数"


def test_wait_terminology_is_distinct():
    """闸门（我方睡眠占比）与等待（单渠道秒数）必须用不同的词。"""
    seg = _timeline()
    assert "闸门等待" in seg
    assert "限速等待" not in seg, "「限速等待」容易和行内「等 Ns」混淆"
    # title 要把两个词的关系讲清
    i = SRC.index("闸门等待＝我方限速睡眠")
    assert "单渠道" in SRC[i:i + 120]


def test_failover_line_says_this_round():
    """「本轮」与「近 7 天」是两个尺度，前缀不能省。"""
    assert ">本轮换道：'" in SRC
    assert "近 '+(Number(_h.days||7))+' 天" in SRC or "近 " in SRC


def test_no_new_visible_nodes():
    """这轮只改文案，不新增可见元素。"""
    seg = _timeline()
    assert seg.count("<div class=") == 1, "耗时行不该新增 div"


# ---- merged from tests/test_r355_health_semantics.py ----

def _hl(ts, lvl, name, msg):
    return f"{ts} [{lvl}] {name}: {msg}"


def _round(lines):
    return "\n".join([
        _hl("2026-10-21 22:00:00", "INFO", "t", "===== 开始一轮扫描 ====="),
        *lines,
        _hl("2026-10-21 22:01:00", "INFO", "t", "===== 本轮扫描结束 ====="),
    ])


def test_calendar_price_is_available_not_failure():
    from core.health import parse_health
    log = _round([
        _hl("2026-10-21 22:00:10", "INFO", "t",
            "[ctrip][intl] 2026-11-16 日历最低含税价 ￥719（1 行）"),
        _hl("2026-10-21 22:00:20", "INFO", "t",
            "[fliggy][intl] 2026-11-16 日历最低含税价 ￥719（税 569）"),
    ])
    out = parse_health(log, now="2026-10-21 23:00:00")
    r = out["rounds"][0]["plats"]
    for p in ("ctrip", "fliggy"):
        assert r[p]["s"] == "ok", r[p]
        assert r[p]["ok"] == 1 and r[p]["tot"] == 1
        assert r[p]["cal"] == 1 and r[p]["detail"] == 0
        assert "日历" in r[p]["note"]
    assert out["stats"]["ctrip"]["cal"] == 1
    assert out["stats"]["ctrip"]["detail"] == 0


def test_detail_success_reports_detail_kind():
    from core.health import parse_health
    log = _round([
        _hl("2026-10-21 22:00:10", "INFO", "t",
            "[tuniu][intl] 2026-11-16 最低含税价 ￥739 "
            "(ZH9516/ZH305)（明细 150 条：直飞 27 / 中转 123）"),
        _hl("2026-10-21 22:00:20", "INFO", "t",
            "[qunar] 2026-11-16 最低价 ￥1526（航班明细 70 条：直飞 44 / 中转 26）"),
    ])
    out = parse_health(log, now="2026-10-21 23:00:00")
    r = out["rounds"][0]["plats"]
    for p in ("tuniu", "qunar"):
        assert r[p]["s"] == "ok", r[p]
        assert r[p]["detail"] == 1 and r[p]["cal"] == 0
    assert out["stats"]["tuniu"]["detail"] == 1


def test_login_rejection_is_actionable():
    from core.health import parse_health
    log = _round([
        _hl("2026-10-21 22:00:10", "WARNING", "t",
            "[qunar][intl] 2026-11-16 未登录硬拒（1999/8）"
            "——请在配置页「渠道登录」重登 qunar；本轮放弃不压制"),
    ])
    out = parse_health(log, now="2026-10-21 23:00:00")
    p = out["rounds"][0]["plats"]["qunar"]
    assert p["s"] == "fail"
    assert p["need_login"] is True
    assert "需登录" in p["note"]
    assert out["stats"]["qunar"]["auth"] == 1


def test_invalid_link_444_is_risk_evidence_not_login_rejection():
    from core.health import parse_health
    log = _round([
        _hl("2026-10-21 22:00:10", "WARNING", "t",
            "[tongcheng][intl] 2026-11-16 会话门拒（code=444 非法链接，"
            "body 55B）——请在配置页「渠道登录」重登 tongcheng"),
    ])
    out = parse_health(log, now="2026-10-21 23:00:00")
    p = out["rounds"][0]["plats"]["tongcheng"]
    assert p["s"] == "fail"
    assert p["need_login"] is False
    assert p["note"] and "重登" not in p["note"] and "需登录" not in p["note"]
    assert out["stats"]["tongcheng"]["auth"] == 0


def test_calendar_plus_failure_is_partial_and_counts_calendar():
    from core.health import parse_health
    log = _round([
        _hl("2026-10-21 22:00:10", "INFO", "t",
            "[ctrip][intl] 2026-11-16 日历最低含税价 ￥719（1 行）"),
        _hl("2026-10-21 22:00:20", "WARNING", "t",
            "[ctrip][intl] 2026-11-17 未拿到日历价"),
    ])
    out = parse_health(log, now="2026-10-21 23:00:00")
    p = out["rounds"][0]["plats"]["ctrip"]
    assert p["s"] == "part"
    assert p["ok"] == 1 and p["tot"] == 2
    assert p["cal"] == 1
    assert "未拿到日历价" in p["note"]


def test_calendar_empty_body_note_is_preserved():
    from core.health import parse_health
    log = _round([
        _hl("2026-10-21 22:00:10", "WARNING", "t",
            "[tongcheng][intl] 2026-11-16 未拿到日历价（body 55B）"),
    ])
    out = parse_health(log, now="2026-10-21 23:00:00")
    p = out["rounds"][0]["plats"]["tongcheng"]
    assert p["s"] == "fail"
    assert "未拿到日历价" in p["note"]


def test_demo_health_carries_semantic_counts():
    from core.demo import demo_health
    out = demo_health(hours=2)
    for plat, st in out["stats"].items():
        assert "cal" in st and "detail" in st and "auth" in st, plat
    assert out["stats"]["fliggy"]["cal"] > 0


def test_search_kpi_separates_fallback_from_anomaly():
    src = webui_full_src()
    start = src.index("function srxRenderKpis(){")
    end = src.index("function srxRenderChips(){", start)
    block = src[start:end]
    # 补位/异常降为 KPI 次级行，不再各占一张零值主卡。
    assert "补位 " in block and "fallback" in block and "bad" in block
    assert "k('异常'" not in block
    assert "srx-kpi-sub" in block and "本次明细" in block


def test_read_log_tail_keeps_oldest_line_beyond_2mb_tail(tmp_path, monkeypatch):
    """5MiB 轮转文件必须整读：旧的 2MiB 尾读会静默丢掉窗口最早轮次。"""
    import webui
    log = tmp_path / "monitor.log"
    old = "2026-10-22 09:00:00 [INFO] t: ===== 开始一轮扫描 =====\n"
    (tmp_path / "monitor.log.1").write_text(
        old + "x" * 2_300_000 + "\n", encoding="utf-8")
    log.write_text("2026-10-22 10:00:00 [INFO] t: latest\n", encoding="utf-8")
    monkeypatch.setattr(webui._State, "cfg",
                        {"output": {"log_path": str(log)}})
    text = webui._read_log_tail(max_age_h=48)
    assert old.strip() in text
    assert "latest" in text


def test_read_log_tail_never_glues_rotated_boundary_lines(tmp_path, monkeypatch):
    import webui
    log = tmp_path / "monitor.log"
    (tmp_path / "monitor.log.1").write_text(
        "2026-10-22 09:00:00 [INFO] t: 旧文件末行", encoding="utf-8")
    log.write_text("2026-10-22 10:00:00 [INFO] t: 新文件首行\n",
                   encoding="utf-8")
    monkeypatch.setattr(webui._State, "cfg",
                        {"output": {"log_path": str(log)}})
    text = webui._read_log_tail(max_age_h=48)
    assert "旧文件末行\n2026-10-22 10:00:00" in text


# 当前认证按钮和国际能力条由 test_channel_ui_status 的真实脚本行为
# 覆盖：历史失败不可生成当前登录动作，明确新拒绝才跨页面显示同一动作。


# ---- merged from tests/test_r489_health_five_dims_rendered.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SLOTS = {"ok": True, "plats": {"fliggy": {"status": "saved", "saved": True}},
         "slots": {
             "fliggy": {"plat": "fliggy", "name": "飞猪 PC", "surface": "pc",
                        "surface_label": "PC", "status": "saved",
                        "saved": True, "needs_login": False, "account": "a"},
             "fliggy_h5": {"plat": "fliggy", "name": "飞猪 H5", "surface": "h5",
                           "surface_label": "H5", "status": "login_required",
                           "needs_login": True, "saved": True, "account": "a"},
         }}

# 与 /api/health 的 paths 同形：
#   - retired 不是 retired_paths
#   - scopes 的 key 是 dom/intl（path_stats 原始口径），不是 domestic/international
#     （前端 _scTxt 会把 dom 显示成「国内」）
PATHS = {"fliggy": {
    "paths": {"PC": {"attempts": 12, "ok": 11, "rate": 0.917},
              "H5": {"attempts": 28, "ok": 12, "rate": 0.429},
              "日历": {"attempts": 6, "ok": 1, "rate": 0.167}},
    "retired": ["日历"],
    "scopes": {"dom": {"query_rate": 0.95, "query_attempts": 20},
               "intl": {"query_rate": 0.7, "query_attempts": 20}},
    "query_rate_live": 0.825, "query_attempts_live": 40}}

HEALTH = {
    "ok": True,
    "rounds": [{"ts": "2026-10-29 02:50", "plats": {
        "fliggy": {"s": "part", "ok": 2, "tot": 3, "cal": 0, "detail": 2}}}],
    "stats": {"fliggy": {"ok": 33, "part": 2, "fail": 5, "maint": 0,
                         "rate": 0.825, "cal": 0, "detail": 33, "auth": 3}},
    "push": {"channels": {}}, "paths": PATHS,
    "diag": [{"plat": "fliggy", "name": "飞猪", "kind": "login",
              "label": "登录态失效", "action": "打开登录窗口重存会话",
              "s": "fail", "login": "login_required", "cookie": "missing",
              "evidence": "H5 会话被拒",
              "slots": [{"slot": "fliggy", "surface": "PC",
                         "needs_login": False, "status": "saved"},
                        {"slot": "fliggy_h5", "surface": "H5",
                         "needs_login": True, "status": "login_required"}],
              "dead_surfaces": ["H5"], "slot_action": "fliggy_h5"}],
    "coverage": {},
}






def test_backend_scope_fields_match_what_the_frontend_reads():
    """后端下发的分域字段名必须与前端读取的一致。

    实测缺陷（r490）：后端只发 `{rate, attempts}`，前端分域读的是
    `query_attempts[_live]` / `query_rate[_live]` —— 两侧不同名，
    「分域」这一维**在真实页面上从未渲染出来过**。
    `test_goal_d` 只查源码里有 `scoped('dom','国内')`，看不见字段名错配。

    上面那条渲染契约是**注入载荷**测的，打不到后端字段；这条直接钉后端。
    """
    import io
    import re as _re
    w = webui_full_src()
    # 前端实际读取的键
    i = w.index("const _qsc=((j.paths||{})[p]||{}).scopes||{};")
    front = set(_re.findall(r"_q\.([a-z_]+)", w[i:i + 700]))
    assert front, "未能解析前端分域字段"
    # 后端构造 _sc[_sn] 的分支
    j = w.index("_sc[_sn] = {")
    back_src = w[j:w.index("paths[_p] = {", j)]
    for k in front:
        assert '"%s":' % k in back_src, \
            "后端未下发前端要读的分域字段 %s（分域这一维渲染不出来）" % k


def test_badge_fallback_never_mixes_attempt_level_into_query_rate():
    """徽标兜底（`_liveRate` 不可用时）也必须按**查询**口径加权。

    `qRate` 曾用 `_q.rate × _q.attempts`——那是「尝试级 × 尝试数」，
    和分域小标（查询级）不是一个分母。`query_*_live` 缺失时同一行又
    会「13% 国际 73%」打架。现在：有查询字段就按查询加权；缺任一域的
    查询字段就整段作废（回落到轮次口径并在 title 里如实标注），
    绝不混着算。
    """
    import io
    import os
    import re

    src = webui_full_src()
    i = src.index("const _qscope=((_qp.scopes)||{});")
    seg = src[i:i + 1200]
    assert "query_attempts_live" in seg and "query_rate_live" in seg, (
        "徽标兜底没有用查询口径字段：%s" % seg[:400])
    assert "(_q.rate||0)*_q.attempts" not in seg, (
        "徽标兜底仍在用尝试级 rate 加权（与分域小标不同分母）：%s"
        % seg[:400])
    assert "_qmiss" in seg, "缺少「查询字段不全就别算」的标记"


# ---- merged from tests/test_v194_health_geo.py ----

class TestHealthCellsNoScrollbar:
    """webui.py 源码级钉死（渠道健康格带零滚动条/零重排）。"""

    @staticmethod
    def _src():
        import webui as _w
        with io.StringIO(webui_full_src()) as f:
            return f.read()

    @staticmethod
    def _rule(src, marker):
        """取以 marker 开头的那条 CSS 声明（到 '}' 为止）。"""
        i = src.index(marker)
        return src[i:src.index("}", i) + 1]

    @staticmethod
    def _media(src, marker):
        """取 marker 那个 @media 块的整段（到首个行首收尾括号为止）。

        收尾括号在本文件有两种缩进形态（`\\n}` 与 `\\n }`，块内语句
        另起一行时缩进一格），取先到者。"""
        i = src.index(marker)
        ends = [j for j in (src.find("\n}", i), src.find("\n }", i)) if j >= 0]
        j = min(ends)
        return src[i:j + 3]

    # ---- 修 A：基础规则掐掉被强制出来的纵向滚动条 ----

    def test_base_rule_y_axis_clipped(self):
        """.hcells 基础规则：x 窄档仍需可滚，y 必须恒定裁剪。

        `overflow-x:auto` 单独出现会让 overflow-y 计算值变 auto，
        hover 放大 ::after 即出纵滚条（真机 scrollHeight 37→43）。"""
        seg = self._rule(self._src(), ".hcells{display:flex")
        assert "overflow-x:auto" in seg, "窄档横向滚动能力被误删（390 档退化）"
        assert "overflow-y:hidden" in seg, \
            ".hcells 未把 y 轴改为恒定裁剪（hover 仍会闪纵滚条）"

    # ---- 修 B：桌面弹性档不再是滚动容器 ----

    def test_desktop_tier_not_scroll_container(self):
        """弹性档：格带恒等于容器宽 → 必须非滚动容器。

        否则 1px 热点外扩 → 横滚条恒在；纵滚条闪现 → 弹性格全行重排。
        r322 改写：弹性档从静态媒体块改 .fit 实判定类承载（格带放得
        下即挂），非滚动语义由 .fit 类规则担保、全带宽生效。"""
        src = self._src()
        assert ".hcells.fit{overflow:hidden;overflow:clip}" in src, \
            "弹性档 .hcells 仍是滚动容器（滚动条→弹性格重排=抖动）"
        assert ".hcells.fit .hc{width:auto;flex:1 1 6px}" in src, \
            "弹性格铺满规则丢失"

    # ---- 回归护栏：不得把 v1.5.91 的触控热区修复一起改坏 ----

    def test_keeps_v191_hotspot_fix(self):
        """padding/margin 三件套 + ::after 热区尺寸不许被顺手改掉。

        裁剪切点=衬垫框（37px），热点纵向 -11px 恰好铺满衬垫框——
        改 padding 会让热点被裁、改 ::after 会让相邻格热区互相覆盖。"""
        src = self._src()
        seg = self._rule(src, ".hcells{display:flex")
        assert "padding:11px 0" in seg, "衬垫高度被改（热点纵向被裁）"
        assert "margin:-9px 0" in seg, "负 margin 回收丢失（行高回涨）"
        assert "pointer-events:none" in seg, \
            "容器事件穿透丢失（衬垫吞点击回归）"
        hot = self._rule(src, ".hc::after{")
        assert "inset:-11px -1px" in hot, \
            "热点 inset 被改（-1px 防串格 / -11px 触控基准纪律）"


# ---- merged from tests/test_v295_health_ui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    import webui
    with io.StringIO(webui_full_src()) as f:
        return f.read()


def test_server_diag_and_selfcheck_present():
    src = _src()
    for s in ('out["diag"] = classify_round', "/api/channel/selfcheck",
              "channel_evidence.jsonl", "_cookie_states",
              "j.diag", "diagSelfcheck"):
        assert s in src, s


def test_render_no_longer_regex_classifies():
    src = _src()
    start = src.index("function renderHealthDiag")
    end = src.index("async function diagSelfcheck")
    body = src[start:end]
    assert "179991|IP|403" not in body
    assert "j.diag" in body
    assert "不猜测" in body
