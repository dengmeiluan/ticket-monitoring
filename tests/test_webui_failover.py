# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_blockers_visible.py
- tests/test_r1063_degraded_batch2.py
- tests/test_r1063_degraded_ledger.py
- tests/test_r1063_failover_ready.py
- tests/test_r1063_failover_state.py
- tests/test_r1063_failover_surface.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import os
import pytest
import sys
import tempfile
import time

from core import degraded as dg, failover as fo, strategy_params as sp
from core.pacing import Pacing


# ---- merged from tests/test_r1063_blockers_visible.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fresh_degraded(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    from core import degraded as dg
    with dg._LOCK:
        dg._STATE.clear()
    return dg


def test_degraded_persists_across_processes(tmp_path, monkeypatch):
    dg = _fresh_degraded(tmp_path, monkeypatch)
    dg.note("device_env", "", "1 处矛盾", now=time.time())
    # 模拟"另一个进程"：清空内存后再读
    with dg._LOCK:
        dg._STATE.clear()
    snap = dg.snapshot()
    assert "device_env" in snap, snap
    assert "1 处矛盾" in snap["device_env"]["last"]


def test_degraded_ttl_drops_old(tmp_path, monkeypatch):
    dg = _fresh_degraded(tmp_path, monkeypatch)
    dg.note("app_captcha", "app_fliggy", "滑块未过",
            now=time.time() - dg._TTL_S - 60)
    with dg._LOCK:
        dg._STATE.clear()
    assert "app_captcha" not in dg.snapshot(), "超过 TTL 的旧账应丢弃"


def test_degraded_counts_accumulate_on_disk(tmp_path, monkeypatch):
    dg = _fresh_degraded(tmp_path, monkeypatch)
    _t = time.time()          # 必须用当前时间附近：TTL 24h 会丢掉旧账
    dg.note("app_captcha", "p", "第一次", now=_t)
    dg.note("app_captcha", "p", "第二次", now=_t + 1)
    with dg._LOCK:
        dg._STATE.clear()
    snap = dg.snapshot()
    assert snap["app_captcha"]["n"] == 2
    assert snap["app_captcha"]["last"] == "第二次"


def test_cpuinfo_hardware_parsed_as_whole_line():
    """`Qualcomm Technologies, Inc SM8650` 不能用第一个词当型号。"""
    from core.android import consistency as C
    assert "整行" in io.open(os.path.join(
        ROOT, "core", "android", "consistency.py"), encoding="utf-8").read()
    # 判据：包含即一致
    facts = {"soc_model": "SM8650",
             "cpuinfo_hardware": "Qualcomm Technologies, Inc SM8650",
             "board": "pineapple", "hardware": "qcom",
             "abilist": "arm64-v8a,armeabi-v7a,armeabi"}
    keys = {i["key"] for i in C.audit(facts)["items"]}
    assert "ro.soc.model vs cpuinfo" not in keys, keys


def test_multiword_vs_single_token_both_accepted():
    from core.android import consistency as C
    for hw in ("SM8650", "Qualcomm Technologies, Inc SM8650"):
        facts = {"soc_model": "SM8650", "cpuinfo_hardware": hw}
        assert not C.audit(facts)["items"]


def test_panel_has_labels_and_next_steps():
    src = webui_full_src()
    assert "device_env:'设备环境'" in src
    assert "app_captcha:'人机验证'" in src
    assert "core.android.consistency" in src and "identity_boot_module" in src
    assert "reset-app" in src


def test_setup_check_has_device_env_row():
    from core import setup_check as sc
    assert callable(getattr(sc, "check_device_env", None))
    src = io.open(os.path.join(ROOT, "core", "setup_check.py"),
                  encoding="utf-8").read()
    i = src.index("def run_checks")
    assert "check_device_env()" in src[i:i + 400]


# ---- merged from tests/test_r1063_degraded_batch2.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = io.open(os.path.join(ROOT, "crawlers", "base.py"),
               encoding="utf-8").read()
CAPTCHA = io.open(os.path.join(ROOT, "crawlers", "captcha.py"),
                  encoding="utf-8").read()
SRC = webui_full_src()


def test_stealth_injection_failure_is_recorded():
    assert 'note("stealth_init"' in BASE
    i = BASE.index('note("stealth_init"')
    seg = BASE[max(0, i - 600):i + 300]
    assert "add_init_script" in seg, "记账点不在注入失败的分支里"


def test_captcha_screenshot_failure_is_recorded():
    assert 'note("captcha_shot"' in CAPTCHA
    i = CAPTCHA.index('note("captcha_shot"')
    seg = CAPTCHA[max(0, i - 500):i + 400]
    assert "screenshot" in seg, "记账点不在截图失败的分支里"
    # 必须与「检测不到目标」分开：后者不是降级
    assert "检测不到可点目标" in seg or "detect_targets" in seg


def test_degraded_caps_have_chinese_labels():
    seg = SRC[SRC.index("const CN={app_geo"):][:600]
    for cap in ("app_geo", "captcha_det", "ua_kernel", "stealth_init",
                "captcha_shot"):
        assert cap in seg, cap
    # 中文名不许出现空串/英文原文当标签
    assert "伪装注入" in seg and "识别截图" in seg


def test_notes_are_capability_level_not_network_noise():
    """降级账本只收能力级：这三个 key 都不带渠道/时间细节，是"能力名"。"""
    for cap in ("stealth_init", "captcha_shot", "captcha_det", "app_geo",
                "ua_kernel"):
        assert cap.islower() and "/" not in cap and " " not in cap, cap


def test_ledger_records_with_channel():
    dg.reset()
    dg.note("stealth_init", "qunar", "注入失败")
    snap = dg.snapshot()
    assert snap["stealth_init"]["plats"].get("qunar") == 1, snap
    dg.reset()

def test_degraded_line_says_what_to_do_next():
    """只报次数等于让人自己猜：每类降级都要给出**下一步**。"""
    seg = SRC[SRC.index("const _DGFIX="):][:900]
    for cap in ("app_geo", "captcha_det", "ua_kernel", "stealth_init",
                "captcha_shot"):
        assert cap + ":" in seg, cap
    assert "setup_check" in seg and "ddddocr" in seg
    assert "tips.push('→ '" in SRC, "提示里没带下一步"


# ---- merged from tests/test_r1063_degraded_ledger.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEO = io.open(os.path.join(ROOT, "core", "android", "geo.py"),
              encoding="utf-8").read()
CAPTCHA = io.open(os.path.join(ROOT, "crawlers", "captcha.py"),
                  encoding="utf-8").read()
BASE = io.open(os.path.join(ROOT, "crawlers", "base.py"),
               encoding="utf-8").read()
SRC = webui_full_src()


@pytest.fixture(autouse=True)
def _clean():
    dg.reset()
    yield
    dg.reset()


def test_counts_aggregate_per_capability():
    dg.note("app_geo", "", "emu geo fix 失败")
    dg.note("app_geo", "fliggy")
    dg.note("captcha_det", "", "缺后端")
    snap = dg.snapshot()
    assert snap["app_geo"]["n"] == 2, snap
    assert snap["app_geo"]["plats"].get("fliggy") == 1, snap
    assert "缺后端" in snap["captcha_det"]["last"]
    assert dg.total() == 3


def test_empty_capability_is_ignored():
    dg.note("", "", "没名字的不记")
    assert dg.snapshot() == {}


def test_ledger_never_raises_on_bad_input():
    dg.note("x", "", "", n="abc")      # 不抛
    assert dg.snapshot()["x"]["n"] == 1


def test_pacing_snapshot_carries_it():
    dg.note("app_geo", "", "失败")
    got = Pacing({"fliggy": {}}).snapshot()
    assert "degraded" in got and got["degraded"]["app_geo"]["n"] == 1, got


def test_geo_failure_is_recorded():
    assert 'dg.note("app_geo"' in GEO or "_dg.note(\"app_geo\"" in GEO


def test_missing_detector_is_recorded():
    assert 'note("captcha_det"' in CAPTCHA


def test_ua_kernel_mismatch_is_recorded():
    assert 'note("ua_kernel"' in BASE


def test_panel_shows_the_degraded_line_only_when_needed():
    # 窗口放宽：T61 又往 tips 里加了「下一步」（_DGFIX），1400 字不够
    seg = SRC[SRC.index("const _degradeLine="):][:2200]
    assert "j.degraded" in seg
    assert "if(!keys.length)return '';" in seg, "没有降级时不该占位"
    # 中文能力名与原因都要有
    assert "识别后端" in seg and "定位" in seg
    assert "esc(tips.join" in seg, "提示文案要转义"
    # r1392：右栏重构后降级行与建议/弱通路成组渲染，读数折叠进 pace-fold；
    # 断言保留原意——降级行必须挂在右栏（pace-side）且与建议同组。
    assert "+_degradeLine+_adviceLine+_pathLine" in SRC, "没挂到右栏"
    assert "+_stats+_rail+_kv+_fostats" in SRC, "读数未折进 pace-fold"


# ---- merged from tests/test_r1063_failover_ready.py ----

MAIN = io.open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "main.py"), encoding="utf-8").read()


def test_ready_gate_blocks_when_not_ready():
    d = tempfile.mkdtemp()
    app, why = fo.plan_switch(
        "ctrip", "captcha", {}, user_data_dir=d,
        ready=lambda _a: (False, "安卓链路未启用"))
    assert app == "" and "未就绪" in why, why


def test_ready_gate_passes_when_ready():
    d = tempfile.mkdtemp()
    app, _why = fo.plan_switch("ctrip", "captcha", {}, user_data_dir=d,
                              ready=lambda _a: (True, ""))
    assert app == "app_ctrip"


def test_ready_gate_is_fail_open_on_errors():
    """就绪检查自己炸了不许挡住换道（否则一个 bug 会让整条兜底失效）。"""
    d = tempfile.mkdtemp()

    def _boom(_a):
        raise RuntimeError("readiness 出问题")

    app, _why = fo.plan_switch("ctrip", "captcha", {}, user_data_dir=d,
                              ready=_boom)
    assert app == "app_ctrip"


def test_no_ready_callback_keeps_old_behaviour():
    d = tempfile.mkdtemp()
    assert fo.plan_switch("ctrip", "captcha", {}, user_data_dir=d)[0] == "app_ctrip"


def test_main_wires_the_readiness_checker():
    assert "def _app_ready(" in MAIN
    assert "ready=_app_ready" in MAIN
    # 只判能离线判定的两件事：安卓总开关、App 渠道是否注册
    assert "android.enabled=false" in MAIN
    assert "未注册" in MAIN
    # 被挡住要有归因（否则用户不知道为什么没换）
    assert "换道被挡" in MAIN


# ---- merged from tests/test_r1063_failover_state.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = webui_full_src()


def test_state_reports_budget_and_cooldown():
    d = tempfile.mkdtemp()
    st = fo.state("fliggy", {}, user_data_dir=d)
    assert st["app"] == "app_fliggy" and st["enabled"] is True
    assert st["cap"] > 0 and st["used"] == 0 and st["left"] == st["cap"]
    assert st["cooldown_left_s"] == 0


def test_state_follows_the_ledger():
    d = tempfile.mkdtemp()
    fo.note_switch("fliggy", "app_fliggy", ok=True, user_data_dir=d)
    st = fo.state("fliggy", {}, user_data_dir=d)
    assert st["used"] == 1 and st["left"] == st["cap"] - 1, st
    assert st["last_app"] == "app_fliggy" and st["last_ok"] is True
    # 冷却从上次换道算起
    assert st["cooldown_left_s"] > 0


def test_state_reflects_the_switch():
    """开关关了要能看出来（否则用户不知道为什么一直没换）。"""
    from core import strategy_params as sp
    sp.invalidate()
    try:
        sp.set_config({"crawler": {"strategy_enabled": {
            "app_fallback": False}}})
        assert fo.state("fliggy", {})["enabled"] is False
    finally:
        sp.invalidate()


def test_states_only_lists_channels_with_an_app_twin():
    d = tempfile.mkdtemp()
    got = fo.states(["fliggy", "ctrip", "app_fliggy", "tuniu"], {},
                    user_data_dir=d)
    assert "app_fliggy" not in got, "App 渠道本身不参与换道"
    # tuniu 没有 App 孪生（app_counterpart("tuniu") == ""）→ 不该出现
    assert set(got) == {"fliggy", "ctrip"}, got


def test_snapshot_carries_the_inputs():
    p = Pacing({"fliggy": {}, "ctrip": {}})
    fo_snap = p.snapshot()["failover"]
    assert "plats" in fo_snap and "fliggy" in fo_snap["plats"]
    row = fo_snap["plats"]["fliggy"]
    for k in ("cap", "used", "left", "cooldown_left_s", "enabled", "app"):
        assert k in row, (k, row)


def test_ui_tooltip_uses_the_inputs_without_new_nodes():
    seg = SRC[SRC.index("const _foPlatTitle="):][:1200]
    for token in ("v.cap", "v.used", "cooldown_left_s", "last_app", "last_ok"):
        assert token in seg, token
    # 只挂在既有 title 上：没有新增可见元素
    i = SRC.index("const _foPlatTitle=")
    after = SRC[i:i + 2000]
    assert "_foPlatTitle?(" in after or "esc(_foPlatTitle" in after
    assert "<div class=\"snote\"" in after or "class=\"snote\"" in after


# ---- merged from tests/test_r1063_failover_surface.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = webui_full_src()


def test_health_panel_renders_failover_stats():
    assert "const _fostats=(()=>{" in SRC
    assert "+_stats+_rail+_kv+_fostats" in SRC, "换道成效没进右栏"


def test_failover_line_is_empty_when_nothing_happened():
    """没有换道就返回空串——不占位，几何零变化。"""
    seg = SRC[SRC.index("const _fostats=(()=>{"):][:900]
    assert "if(!pre&&!sw&&!rows)return '';" in seg


def test_failover_line_names_zero_recovery():
    """回采 0 条要说明白（App 通路可能也被拦），不能只显示「换道 1 次」。"""
    # 窗口放宽：T50 起这段里还塞了每家渠道的判据输入（只挂在 title 上，
    # 可见文案不变）
    seg = SRC[SRC.index("const _fostats=(()=>{"):][:3200]
    assert "回采 0 条" in seg


def test_snapshot_exposes_failover_counters():
    from core.pacing import Pacing

    p = Pacing({})
    p.note_failover(preload=2, note="x")
    p.note_failover(switched=1, rows=7)
    f = p.snapshot()["failover"]
    assert f["preloads"] == 2 and f["switches"] == 1 and f["rows"] == 7, f
