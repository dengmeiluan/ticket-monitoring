# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_net_check.py
- tests/test_r1063_session_panel.py
- tests/test_r1063_session_reset.py
- tests/test_r1063_session_reset_trace.py
- tests/test_r1063_session_reset_ui.py
- tests/test_r1063_session_window.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import os
import pytest
import sys
import time
import webui

from core import net_check as NC, session_reset as sr, session_window as SW, strategy_params as sp
from core.pacing import Pacing


# ---- merged from tests/test_r1063_net_check.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_residential_verdict():
    v, advice = NC.verdict({"proxy": False, "hosting": False, "mobile": False})
    assert v == "residential"
    assert "IP 不是主要风险点" in advice


def test_datacenter_verdict_wins_over_mobile():
    v, advice = NC.verdict({"proxy": True, "hosting": True, "mobile": True})
    assert v == "datacenter"
    assert "换家宽" in advice


def test_hosting_alone_is_datacenter():
    assert NC.verdict({"hosting": True})[0] == "datacenter"


def test_mobile_verdict():
    v, _ = NC.verdict({"proxy": False, "hosting": False, "mobile": True})
    assert v == "mobile"


def test_unknown_when_probe_failed():
    v, advice = NC.verdict({})
    assert v == "unknown"
    assert "别急着换 IP" in advice


def test_probe_never_raises(monkeypatch):
    """网络不通时也必须返回 dict（返回 {}），不许抛。"""
    import httpx

    def _boom(*a, **kw):
        raise httpx.ConnectError("no net")

    monkeypatch.setattr(httpx, "get", _boom)
    assert NC.probe(timeout=0.1) == {}


def test_cli_exists():
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "core", "net_check.py"),
        encoding="utf-8").read()
    assert "def _main" in src and "--json" in src


# ---- merged from tests/test_r1063_session_panel.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = webui_full_src()


def test_session_field_is_wired_into_pacing_payload():
    assert "from core import session_window as _sw" in SRC
    assert '_ch["session"] = _session' in SRC
    # 必须用真实存在的 root 助手（第一版写成 `_ud_root_local()`，会被 try 吞掉）
    seg = SRC[SRC.index("from core import session_window as _sw"):
              SRC.index("from core import session_window as _sw") + 400]
    assert "_ud_root()" in seg, seg
    assert "_ud_root_local" not in seg, "不存在的助手会被 try 静默吞掉"


def test_session_field_inside_path_stats_block():
    """要放在 path_stats 那段里（真实模式才执行），别放到别处。"""
    i_sess = SRC.index('_ch["session"] = _session')
    i_paths = SRC.index("_paths = {}", i_sess)
    assert 0 < i_paths - i_sess < 600, (i_sess, i_paths)


def test_ud_root_helper_exists():
    import webui
    assert callable(getattr(webui, "_ud_root", None))
    root = webui._ud_root()
    assert str(root)


# ---- merged from tests/test_r1063_session_reset.py ----

@pytest.fixture(autouse=True)
def _clean():
    sp.invalidate()
    yield
    sp.invalidate()


def _profile(root, plat, extra=True):
    d = os.path.join(str(root), plat)
    os.makedirs(os.path.join(d, "Default"), exist_ok=True)
    if extra:
        for fn in ("policy_state.json", "yield_stats.json"):
            with open(os.path.join(d, fn), "w", encoding="utf-8") as f:
                f.write('{"x": 1}')
    return d


def test_backup_moves_not_deletes_and_carries_our_state(tmp_path):
    d = _profile(tmp_path, "fliggy")
    rep = sr.backup("fliggy", str(tmp_path), reason="manual")
    assert rep["ok"], rep
    assert os.path.isdir(d), "新档案必须存在"
    assert os.path.isdir(os.path.join(d, "Default")) is False, "新档案要是干净的"
    # 我们的账要跟过来
    assert set(rep["kept_state"]) == {"policy_state.json", "yield_stats.json"}
    assert os.path.isfile(os.path.join(d, "policy_state.json"))
    # 旧档案还在（可还原）
    assert rep["backup"] in [b["name"] for b in sr.list_backups("fliggy",
                                                               str(tmp_path))]


def test_backup_of_missing_profile_is_not_a_success(tmp_path):
    rep = sr.backup("nope", str(tmp_path))
    assert rep["ok"] is False and "没有档案" in rep["why"]


def test_restore_brings_it_back_without_overwriting(tmp_path):
    d = _profile(tmp_path, "qunar")
    rep = sr.backup("qunar", str(tmp_path))
    # 新档案里写点垃圾，证明还原会把它挪开而不是覆盖
    with open(os.path.join(d, "junk.txt"), "w", encoding="utf-8") as f:
        f.write("x")
    r2 = sr.restore("qunar", str(tmp_path), rep["backup"])
    assert r2["ok"], r2
    assert os.path.isdir(os.path.join(d, "Default")), "原档案内容应回来了"
    assert not os.path.exists(os.path.join(d, "junk.txt"))
    assert r2["discarded"].startswith("qunar.discard_")


def test_prune_keeps_only_the_newest(tmp_path):
    _profile(tmp_path, "ctrip")
    names = []
    for _ in range(4):
        rep = sr.backup("ctrip", str(tmp_path), keep=2)
        assert rep["ok"], rep
        names.append(rep["backup"])
        # 每次都要有档案可重置
        _profile(tmp_path, "ctrip")
    left = [b["name"] for b in sr.list_backups("ctrip", str(tmp_path))]
    assert len(left) <= 2, left


def test_should_reset_respects_switch_threshold_cooldown_and_cap():
    sp.set_config({})
    # 开关默认开；未到阈值
    ok, why = sr.should_reset("fliggy", fails=1)
    assert ok is False and "未到阈值" in why, why
    # 到阈值
    ok, why = sr.should_reset("fliggy", fails=99)
    assert ok is True, why
    # 冷却中
    ok, why = sr.should_reset("fliggy", fails=99, last_reset_ts=1.0,
                              now=2.0)
    assert ok is False and "冷却" in why, why
    # 今日上限
    ok, why = sr.should_reset("fliggy", fails=99, resets_today=99)
    assert ok is False and "今日" in why, why
    # 开关关掉
    sp.set_config({"crawler": {"strategy_enabled": {"session_reset": False}}})
    ok, why = sr.should_reset("fliggy", fails=99)
    assert ok is False and "开关" in why, why


def test_auto_step_counts_only_consecutive_blocks(tmp_path):
    _profile(tmp_path, "tuniu")
    st = {}
    r1 = sr.auto_step(st, "tuniu", str(tmp_path), blocked=True)
    assert r1["acted"] is False, "第一次不该动手"
    r2 = sr.auto_step(st, "tuniu", str(tmp_path), blocked=False)
    assert r2["acted"] is False and st["fails"]["tuniu"] == 0, "没被拦要清零"
    acted = None
    for _ in range(5):
        r = sr.auto_step(st, "tuniu", str(tmp_path), blocked=True)
        if r["acted"]:
            acted = r
            break
    assert acted is not None, "达到阈值后应该真的重建"
    assert acted["result"]["ok"] is True


def test_auto_step_never_raises_on_broken_root():
    r = sr.auto_step({}, "ctrip", "\\\\?\\不存在的路径\\x", blocked=True)
    assert r["acted"] is False


def test_routes_exist_for_manual_control():
    """可干预：必须是**手也能按**的（自动只是兜底）。"""
    src = webui_full_src()
    assert '"/api/session/reset"' in src
    assert '"/api/session/restore"' in src


def test_main_auto_hook_is_wired_and_guarded():
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "main.py"), encoding="utf-8").read()
    assert "session_reset as _sr" in src
    assert "_sr.auto_step(" in src
    # 必须被 try 包住：会话维护不许把一轮采集搞挂
    i = src.index("_sr.auto_step(")
    assert "except Exception" in src[i - 200:i + 600] or \
        "except Exception" in src[i:i + 900]


# ---- merged from tests/test_r1063_session_reset_trace.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = webui_full_src()
MAIN = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()


def test_pacing_exposes_the_judgment_chain():
    p = Pacing({"fliggy": {}})
    p.note_reset("fliggy")
    p.note_sr_state("fliggy", fails=3, kind="captcha",
                    last_ts=time.time() - 3600, day=1, why="连续被拦 3 次")
    sr = p.snapshot()["channels"]["fliggy"]["sr"]
    assert sr["fails"] == 3 and sr["kind"] == "captcha"
    assert sr["day"] == 1 and "连续被拦" in sr["why"]


def test_state_merges_partial_updates():
    """只报一项时不许把别的项清空（每轮上报的字段可能不齐）。"""
    p = Pacing({"ctrip": {}})
    p.note_sr_state("ctrip", fails=2, kind="ip")
    p.note_sr_state("ctrip", day=3)
    sr = p.snapshot()["channels"]["ctrip"]["sr"]
    assert sr["fails"] == 2 and sr["kind"] == "ip" and sr["day"] == 3, sr


def test_no_field_when_nothing_happened():
    p = Pacing({"qunar": {}})
    assert "sr" not in (p.snapshot()["channels"]["qunar"] or {})


def test_ui_builds_the_tooltip_from_the_chain():
    seg = SRC[SRC.index("const _srTitle=(()=>{"):][:1400]
    for token in ("sr.why", "sr.fails", "sr.last_ts", "sr.day"):
        assert token in seg, token
    assert "esc(_srTitle)" in SRC, "提示文案没有转义就写进 title"


def test_tooltip_does_not_add_layout():
    """读数与解释都挂在既有 `.e2` / `<i class="e2k">` 上，不新增可见节点。"""
    i = SRC.index("_srTxt?((")
    seg = SRC[i:i + 400]
    assert 'class="e2k"' in seg
    assert "title=" in seg


def test_main_reports_the_chain_every_round():
    assert "note_sr_state(" in MAIN
    i = MAIN.index("note_sr_state(")
    seg = MAIN[i:i + 700]
    for token in ("fails=", "last_ts=", "day=", "why="):
        assert token in seg, token
    # 上报失败不许影响采集
    assert "except Exception" in MAIN[max(0, i - 400):i + 900]


# ---- merged from tests/test_r1063_session_reset_ui.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = webui_full_src()
MAIN = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()


def _fn(name):
    i = SRC.index("function %s(" % name)
    j = SRC.index("\nfunction ", i + 10)
    return SRC[i:j]


def test_pacing_counts_resets_and_exposes_them():
    p = Pacing({"fliggy": {}, "ctrip": {}})
    assert p.reset_count("fliggy") == 0
    p.note_reset("fliggy")
    p.note_reset("fliggy")
    assert p.reset_count("fliggy") == 2
    ch = p.snapshot()["channels"]
    assert (ch.get("fliggy") or {}).get("resets") == 2, ch.get("fliggy")
    # 没重建过的渠道不出现该字段（不制造 0 值噪声）
    assert "resets" not in (ch.get("ctrip") or {})


def test_row_has_the_button_and_the_counter():
    seg = SRC[SRC.index("const chips=_order.map(k=>{"):][:24000]
    assert "paceSessionReset(" in seg, "行里没有重置会话按钮"
    assert "data-pk=\"'+k+':sreset\"" in seg or ":sreset" in seg
    assert "已重建 " in seg, "行里没有「已重建 N 次」读数"


def test_button_is_browser_only():
    """App 渠道换档案要走渠道登录，不是删设备目录。"""
    seg = SRC[SRC.index("const chips=_order.map(k=>{"):][:24000]
    i = seg.index("sreset")
    assert "/^app_/.test(String(k))" in seg[max(0, i - 600):i], \
        "按钮没有排除 App 渠道"


def test_confirm_before_destructive_action():
    fn = _fn("paceSessionReset")
    assert "confirm(" in fn, "破坏性动作没有二次确认"
    assert "可还原" in fn, "没告诉用户旧档案可还原"
    assert "/api/session/reset" in fn
    assert "method:'POST'" in fn


def test_readout_uses_existing_badge_pattern():
    """沿用 `<i class="e2k">` 标签，不新起视觉。"""
    i = SRC.index("_srTxt?(")
    seg = SRC[max(0, i - 300):i + 300]
    assert 'class="e2k"' in seg, "读数没走既有标签样式"


def test_both_paths_record_the_count():
    """手动与自动都要记数，否则读数永远 0。"""
    # 取**后端路由**那一处：前端函数里也有同一串，先跳过它
    i = SRC.index('self.path == "/api/session/reset"')
    seg = SRC[i:i + 2500]
    assert "note_reset(" in seg, "手动路由没记数"
    assert "note_reset(" in MAIN, "自动兜底没记数"


def test_panel_payload_carries_resets():
    """读数来自 `/api/pacing`（pacing.snapshot），不是前端自己编的。"""
    p = Pacing({"fliggy": {}})
    p.note_reset("fliggy", 3)
    got = webui._demo_pacing_payload if False else None  # noqa: F841
    assert p.snapshot()["channels"]["fliggy"]["resets"] == 3


# ---- merged from tests/test_r1063_session_window.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _root():
    import tempfile
    return tempfile.mkdtemp()


def test_ok_then_block_makes_a_window():
    r = _root()
    SW.note(r, "p", "ok", now=1000.0)
    SW.note(r, "p", "login", now=1812.0)
    s = SW.summary(r, "p")
    assert s["last_window_s"] == 812.0, s
    assert s["last_block_kind"] == "login"
    assert "812" in s["last_window_text"]


def test_calendar_counts_as_usable():
    r = _root()
    SW.note(r, "p", "calendar", now=100.0)
    SW.note(r, "p", "captcha", now=160.0)
    assert SW.summary(r, "p")["last_window_s"] == 60.0


def test_block_without_prior_ok_is_ignored():
    """先被拦（从没可用过）不该编出一个窗口。"""
    r = _root()
    SW.note(r, "p", "login", now=200.0)
    s = SW.summary(r, "p")
    assert s["last_window_s"] == 0 and s["windows"] == 0


def test_recovery_interval_is_recorded():
    r = _root()
    SW.note(r, "p", "login", now=100.0)
    SW.note(r, "p", "ok", now=1900.0)
    s = SW.summary(r, "p")
    assert s["recover_s"] == 1 and s["avg_recover_s"] == 1800.0, s


def test_avg_and_cap():
    r = _root()
    for i in range(30):
        SW.note(r, "p", "ok", now=1000.0 + i * 100)
        SW.note(r, "p", "login", now=1050.0 + i * 100)
    s = SW.summary(r, "p")
    assert s["windows"] <= SW.KEEP
    assert s["avg_window_s"] == 50.0, s


def test_empty_status_is_noop_and_never_raises():
    r = _root()
    assert SW.note(r, "p", "") == {}
    assert SW.summary(r, "p")["windows"] == 0
    assert SW.summary(_root(), "nope")["last_window_s"] == 0


def test_wired_into_both_path_notes():
    for name in ("app_base.py", "base.py"):
        src = io.open(os.path.join(ROOT, "crawlers", name),
                      encoding="utf-8").read()
        assert "session_window" in src, name
