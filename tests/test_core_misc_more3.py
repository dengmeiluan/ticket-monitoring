# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1070_startup_hardening_hint.py
- tests/test_r1186_dual_modal.py
- tests/test_r1210_backup_retention.py
- tests/test_r1656_failure_kinds_cover_statuses.py
- tests/test_r1744_spin_advice.py
- tests/test_r1761_quiet_wake_pushes_next.py
- tests/test_r1799_dur_cn_backend.py
- tests/test_r501_auto_trip_behavioural.py
- tests/test_r625_breaker_off_is_honest.py
- tests/test_r652_frozen_paths.py
- tests/test_r900_low_fare_single_truth.py
- tests/test_r927_fetch_deadline.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import core.scheduler as sch
import importlib
import io
import logging
import os
import pytest
import re
import sys
import tempfile
import threading
import time
import zipfile

from core import paths, update
from core.android import bootstrap as bs, runtime as rt
from core.android.device import AdbDevice
from core.channels import CHANNEL_DIMENSIONS
from core.pacing import FAILURE_KINDS, Pacing, advise, failure_kind
from core.policy import _dur_cn
from core.specials import SPECIAL_CAPABILITY


# ---- merged from tests/test_r1070_startup_hardening_hint.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

class _Mgr:
    adb_path = "adb"

    def __init__(self, *a, **k):
        pass

    def adb_serial(self):
        # 真实 MuMuManager 里这是**方法**，写成属性会让 AdbDevice 构造抛
        # TypeError 并被吞成"设备句柄不可用"（假绿/假红的典型来源）。
        return "127.0.0.1:16384"

    def available(self):
        return True

    def info(self):
        return {"is_android_started": True, "adb_port": 16384,
                "adb_host_ip": "127.0.0.1"}


class _Dev:
    """假设备：App 都没装（让 status 走到"就绪但缺 App"分支）。"""

    def __init__(self, *a, **k):
        pass

    def app_installed(self, pkg):
        return False


def _patch(monkeypatch, hardening):
    monkeypatch.setattr(bs, "resolve_install_dir", lambda c: r"D:\x")
    monkeypatch.setattr(bs, "MuMuManager", _Mgr)
    from core.android import device as _dev_mod
    monkeypatch.setattr(_dev_mod, "AdbDevice", _Dev)
    monkeypatch.setattr(bs, "probe_hardening", lambda dev: hardening)


def test_ready_with_missing_hardening_says_what_to_run(monkeypatch):
    _patch(monkeypatch, {"ok": False, "checks": [],
                         "missing": ["SELinux 视图=Permissive"],
                         "next": "设备伪装未就位：SELinux 视图=Permissive；"
                                 "执行 python scripts/setup_device.py --apply --reboot"})
    msg = bs.ensure_android_runtime(["app_zhixing"],
                                    {"android": {"enabled": True}})
    assert "setup_device.py" in msg and "--apply" in msg, msg


def test_ready_with_good_hardening_stays_concise(monkeypatch):
    _patch(monkeypatch, {"ok": True, "checks": [("x", True, "y")],
                         "missing": [], "next": ""})
    msg = bs.ensure_android_runtime(["app_zhixing"],
                                    {"android": {"enabled": True}})
    assert "就绪" in msg
    assert "setup_device.py" not in msg


def test_ready_with_unknown_hardening_does_not_cry_wolf(monkeypatch):
    """读不到伪装时不能吓人（ok=None 不算失败）。"""
    _patch(monkeypatch, {"ok": None, "checks": [], "missing": [],
                         "next": "读不到设备状态"})
    msg = bs.ensure_android_runtime(["app_zhixing"],
                                    {"android": {"enabled": True}})
    assert "setup_device.py" not in msg, msg


def test_no_app_channel_returns_empty(monkeypatch):
    _patch(monkeypatch, {"ok": False, "checks": [], "missing": [],
                         "next": "x"})
    assert bs.ensure_android_runtime(["qunar"], {"android": {"enabled": True}}) == ""


# ---- merged from tests/test_r1186_dual_modal.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

WEBUI = webui_full_src()


def test_no_fallback_to_another_vendor():
    """负控：**代码里**不许再出现"回落到飞猪"（注释里说明历史病根是允许的）。"""
    import re

    code = re.sub(r"/\*.*?\*/", "", WEBUI, flags=re.S)
    assert "LG_DUAL[plat]||LG_DUAL.fliggy" not in code, (
        "弹窗仍在回落到飞猪：未登记渠道会弹错别人的窗口")
    assert "||LG_DUAL.fliggy" not in code


def test_fallback_derives_from_backend_slots():
    assert "function _lgDualFallback(" in WEBUI
    i = WEBUI.find("function _lgDualFallback(")
    seg = WEBUI[i:i + 900]
    assert "p+'_h5'" in seg, "兜底没有按 plat+_h5 推 H5 lane"
    assert "CHANNEL_STATE" in seg, "兜底没有读后端 slots（会退回写死）"


def test_modal_uses_fallback():
    i = WEBUI.find("function lgDualModalHTML(")
    seg = WEBUI[i:i + 200]
    assert "_lgDualFallback(plat)" in seg, "弹窗构造没有走兜底"


def test_five_vendors_will_all_get_a_modal():
    """5 家浏览器渠道都必须能开出自己的弹窗（其中 qunar 走兜底）。"""
    from core.channels import BROWSER_CHANNELS
    for plat in BROWSER_CHANNELS:
        assert plat in WEBUI, plat
    assert "qunar" in WEBUI


# ---- merged from tests/test_r1210_backup_retention.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _proj(tmp_path):
    root = tmp_path / "proj"
    (root / "user_data" / "update").mkdir(parents=True)
    (root / "main.py").write_text("V0", encoding="utf-8")
    (root / "data").mkdir()
    (root / "data" / "prices.db").write_text("DB", encoding="utf-8")
    return root


def _bak(root, name, at):
    d = root / "user_data" / "update" / name
    d.mkdir(parents=True)
    (d / "main.py").write_text("OLD", encoding="utf-8")
    os.utime(d, (at, at))
    return d


def test_prune_keeps_newest(tmp_path, monkeypatch):
    root = _proj(tmp_path)
    now = time.time()
    _bak(root, "backup_a", now - 300)
    _bak(root, "backup_b", now - 200)
    _bak(root, "backup_c", now - 100)
    _bak(root, "backup_d", now - 10)
    monkeypatch.setattr(update, "_root", lambda: str(root))
    rep = update.prune_backups(2)
    left = [b["name"] for b in update.list_backups()]
    assert left == ["backup_d", "backup_c"], left
    assert sorted(rep["removed"]) == ["backup_a", "backup_b"], rep
    assert rep["freed_bytes"] > 0


def test_prune_never_touches_user_data(tmp_path, monkeypatch):
    root = _proj(tmp_path)
    now = time.time()
    for i, nm in enumerate(("backup_1", "backup_2", "backup_3")):
        _bak(root, nm, now - 100 + i)
    monkeypatch.setattr(update, "_root", lambda: str(root))
    update.prune_backups(1)
    assert (root / "data" / "prices.db").read_text(encoding="utf-8") == "DB", \
        "清理备份把用户数据删了"
    assert (root / "main.py").is_file()


def test_apply_prunes_automatically(tmp_path, monkeypatch):
    """负控：apply 成功后老备份必须被清（否则又回到只增不减）。"""
    root = _proj(tmp_path)
    now = time.time()
    for i in range(5):
        _bak(root, "backup_old%d" % i, now - 500 + i)
    z = tmp_path / "pkg.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("main.py", "V1")
    monkeypatch.setattr(update, "_root", lambda: str(root))
    rep = update.apply(str(z))
    assert rep["ok"] is True, rep
    assert "pruned" in rep, "apply 没带清理结果"
    left = [b["name"] for b in update.list_backups()]
    assert len(left) <= 3, left


# ---- merged from tests/test_r1656_failure_kinds_cover_statuses.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _statuses(path):
    s = io.open(os.path.join(ROOT, path), encoding="utf-8").read()
    m = re.search(r"PATH_STATUS\s*=\s*\(([^)]*)\)", s, re.S)
    assert m, path
    body = re.sub(r"#[^\n]*", "", m.group(1))
    return [x for x in re.findall(r'"([a-z_]+)"', body)]


def test_every_crawler_status_has_a_label():
    missing = []
    for f in ("crawlers/base.py", "crawlers/app_base.py"):
        for st in _statuses(f):
            if st in ("ok", "calendar"):
                continue      # 这两个是成功态，不进"失败归类"
            if st not in FAILURE_KINDS:
                missing.append("%s:%s" % (f, st))
    assert not missing, "这些状态码在「反复出现」里会写成未分类：%s" % missing


def test_blocked_is_named():
    lbl, act, auto = failure_kind("blocked")
    assert lbl != "未分类", "blocked 仍是未分类"
    assert "拦" in lbl, lbl
    assert act and act != "看日志", act
    assert auto is False


def test_unknown_code_still_honest():
    lbl, act, _ = failure_kind("no-such-code")
    assert lbl == "未分类", "未知码应当如实说未分类（不要编）"


# ---- merged from tests/test_r1744_spin_advice.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

NOW = time.time()
QUIET_OFF = {"active": False}


def _node(att, ok):
    return {"query_attempts": att, "query_ok": ok,
            "last_seen_at": time.strftime("%Y-%m-%d %H:%M:%S",
                                          time.localtime(NOW - 30)),
            "paths": {}}


def test_many_attempts_zero_output_escalates_to_halt():
    got = advise("app_tongcheng", {}, {}, now=NOW, node=_node(25, 0),
                 quiet=QUIET_OFF)
    assert got["action"] == "halt", got
    assert got["severity"] == "act", got
    assert "0 出数" in got["hint"] and "停手" in got["hint"], got["hint"]


def test_few_attempts_still_watch():
    got = advise("x", {}, {}, now=NOW, node=_node(5, 0), quiet=QUIET_OFF)
    assert got["action"] == "watch", got


def test_healthy_attempts_not_escalated():
    got = advise("x", {}, {}, now=NOW, node=_node(25, 10), quiet=QUIET_OFF)
    assert got["action"] != "halt", got


def test_threshold_is_documented():
    import io
    p = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "core", "pacing.py")
    src = io.open(p, encoding="utf-8").read()
    assert ">= 20 and _qok == 0" in src or ">= 20 and _qok == 0" in src.replace(
        " ", " "), "阈值判断不在（20 次尝试 0 出数）"
    assert "空转比失败更贵" in src, "缺理由说明"


# ---- merged from tests/test_r1761_quiet_wake_pushes_next.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class _Job(dict):
    pass


class _Sched:
    """最小假调度器：只记录 modify_job 传入的 next_run_time。"""

    def __init__(self):
        self.timezone = None
        self.next_at = None

    def get_job(self, job_id):
        return object()

    def modify_job(self, job_id, next_run_time=None):
        self.next_at = next_run_time


def _run(state):
    s = _Sched()
    out = sch._schedule_next(s, dict(state))
    return out


def test_quiet_wake_pushes_next_run_past_window_end():
    # 自然间隔 25 分，窗口还剩 75 分 → 应推到 76 分（窗口结束+1）
    out = _run({"interval_minutes": 25, "jitter_minutes": 0,
                "wake_at": 75 * 60})
    assert out is not None
    from datetime import datetime
    delta_min = (out - datetime.now()).total_seconds() / 60.0
    assert 74 <= delta_min <= 76, delta_min
    assert delta_min > 25, "仍然按自然间隔排（会继续在窗内醒）：%.1f" % delta_min


def test_no_wake_keeps_natural_interval():
    out = _run({"interval_minutes": 25, "jitter_minutes": 0})
    assert out is not None


def test_short_remaining_window_wake_wins():
    # 窗口只剩 5 分、自然间隔 30 分 → 按 r391 契约：wake_at 是硬计划，取 5 分。
    out = _run({'interval_minutes': 30, 'jitter_minutes': 0,
                'wake_at': 5 * 60})
    from datetime import datetime
    delta_min = (out - datetime.now()).total_seconds() / 60.0
    assert 4.0 <= delta_min <= 5.5, 'wake_at 没有赢：%.1f' % delta_min


# ---- merged from tests/test_r1799_dur_cn_backend.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_duration_cn_scales():
    assert _dur_cn(30) == "30 秒"
    assert _dur_cn(900) == "15 分钟"
    assert _dur_cn(3600) == "1 小时"
    assert _dur_cn(7200) == "2 小时"
    assert _dur_cn(604700) == "7 天"
    assert _dur_cn(0) == "0 秒"
    assert _dur_cn(None) == "0 秒"


def test_halt_reason_uses_helper():
    s = io.open(os.path.join(ROOT, "core", "policy.py"), encoding="utf-8").read()
    i = s.index("人工停手，剩 ")
    seg = s[i:i + 220]
    assert "_dur_cn(" in seg, "停手理由仍在写分钟"
    assert "%d 分钟" not in seg, "仍有硬编码分钟"


def test_frontend_uses_same_scale():
    w = webui_full_src()
    assert "function durCN(sec)" in w
    assert "' 天'" in w and "' 小时'" in w and "' 分钟'" in w


# ---- merged from tests/test_r501_auto_trip_behavioural.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ps():
    import sys
    sys.path.insert(0, ROOT)
    from core.storage import PriceStorage
    return PriceStorage(os.path.join(tempfile.mkdtemp(), "t.db"))


def test_breaker_actually_fires_and_lands_in_the_ledger():
    import sys
    sys.path.insert(0, ROOT)
    from core.pacing import Pacing

    pac = Pacing({})
    kind, cd = pac.observe("qunar", ["login"], "登录墙", retry_after=0)
    assert kind == "login", "熔断没有真的触发：%r" % (kind,)
    assert cd > 0, "冷却时长非正：%r" % (cd,)

    ps = _ps()
    # 与 main.py 入账块同构
    if kind:
        ps.save_intervention("qunar", "auto_trip", ok=False, scope=kind,
                             note="自动熔断 %s，冷却 %ss" % (kind, int(cd)))

    rows = ps.interventions("qunar", 5)
    assert [r["action"] for r in rows] == ["auto_trip"], \
        "熔断触发后账本里没有 auto_trip：%r" % [
            (r["action"], r["scope"]) for r in rows]
    assert rows[0]["scope"] == "login", "熔断类型未写进 scope"


def test_auto_trip_does_not_steal_the_manual_effect_boundary():
    """自动事件进了账，但「上次干预成效」仍以人工干预为分界。"""
    ps = _ps()
    ps.save_intervention("ctrip", "probe", ok=True, rows=5)
    ps.save_intervention("ctrip", "auto_trip", ok=False, scope="ip",
                         note="自动熔断 ip")
    e = ps.intervention_effect("ctrip", 24)
    assert e.get("action") == "probe", \
        "自动事件抢走了人工干预的分界：%r" % (e,)


def test_auto_trip_is_excluded_from_intervention_success_rate():
    """自动事件不是「人按的钮」，不进干预成功率的分母。"""
    ps = _ps()
    ps.save_intervention("ctrip", "auto_trip", ok=False, scope="ip")
    assert ps.intervention_success_rate() == {}, \
        "自动事件混进了人工干预成功率"


def test_disabled_auto_verify_is_logged_not_silent():
    """「自动开窗已关闭」时必须留痕（可识别）。

    实测：`_auto_verify` 默认 false，命中验证时旧代码 `if _auto and ...`
    直接跳过、**什么都不记**。用户随后看到界面只剩「需验证」，既不知道
    本来可以自动处理，也不知道是自己关掉的。
    """
    import io
    m = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8",
                newline="").read()
    i = m.index('_auto = bool(((rt.get("cfg") or cfg).get("crawler")')
    seg = m[i:i + 1800]
    assert "else:" in seg, "关闭时没有分支处理（静默跳过）"
    j = seg.index("else:")
    tail = seg[j:j + 500]
    assert "已关闭" in tail, "关闭时未说明「已关闭」"
    assert "logger.warning" in tail or "logger.info" in tail, \
        "关闭时未留日志"
    assert "去验证" in tail, "关闭时未告诉用户该做什么"


def test_auto_verify_on_still_opens_the_window():
    """开启时仍要真的开窗（不能为了加日志把功能改坏）。"""
    import io
    m = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8",
                newline="").read()
    i = m.index('_auto = bool(((rt.get("cfg") or cfg).get("crawler")')
    seg = m[i:i + 1800]
    assert "if _auto:" in seg
    assert "verify_channel" in seg and "Thread" in seg, "开启时不再开窗"
    assert "> 600" in seg, "10 分钟内只开一次的防连点丢了"


# ---- merged from tests/test_r625_breaker_off_is_honest.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BLOCKED = ["blocked"]
NOTE = "验证码"


def _p(enabled):
    return Pacing({"crawler": {"breaker": {"enabled": enabled}}})


def test_disabled_breaker_does_not_report_trip():
    pac = _p(False)
    assert pac.cfg["breaker_enabled"] is False
    kind, cd = pac.observe("ctrip", BLOCKED, NOTE)
    assert kind == "", (
        "熔断已关闭，observe 仍返回 %r —— 调用方会写 auto_trip 台账、"
        "打「命中…熔断」告警、自动弹窗" % kind)
    assert cd == 0, "熔断已关闭，不应有冷却时长：%r" % cd
    assert pac._breaker.allow("ctrip") == (True, 0), "关闭后必须放行"
    # 也不该出现在本轮 trips 里（面板「本轮节流」按它算）
    trips = pac.snapshot().get("last_round", {}).get("trips") or []
    assert not [t for t in trips if t.get("plat") == "ctrip"], (
        "关闭后仍记了本轮熔断：%s" % trips)


def test_disabled_breaker_still_keeps_the_cause_visible():
    """开关可以关，事实不能消失：被什么拦的要留在载荷里。"""
    pac = _p(False)
    pac.observe("ctrip", BLOCKED, NOTE)
    ch = (pac.snapshot().get("channels") or {}).get("ctrip") or {}
    assert ch.get("blocked_but_open") == "captcha", (
        "关掉熔断后归因丢了（界面会显示一片正常）：%s" % ch)
    assert ch.get("remain_s") in (0, None), "关闭时不应有冷却：%s" % ch


def test_enabled_breaker_behaviour_is_unchanged():
    """开关开启时行为一字不变（回归护栏）。"""
    pac = _p(True)
    kind, cd = pac.observe("ctrip", BLOCKED, NOTE)
    assert kind == "captcha" and cd > 0, (kind, cd)
    assert pac._breaker.allow("ctrip")[0] is False, "开启时必须熔断"
    ch = (pac.snapshot().get("channels") or {}).get("ctrip") or {}
    assert not ch.get("blocked_but_open"), (
        "开启时不该走 blocked_but_open 分支：%s" % ch)


def test_soft_and_login_still_handled_when_breaker_off():
    """软拒/登录墙不是「熔断」语义——关掉熔断不应连它们一起吞掉。"""
    pac1 = _p(False)
    k1, _ = pac1.observe("qunar", ["soft_reject"], NOTE)
    assert k1 == "soft", (
        "软拒要给「下一轮先预热」的信号，不该因熔断关闭而消失：%r" % k1)
    # 登录墙用独立实例：软拒会在同一渠道留下 needs_warmup，
    # 混在一起测会把「登录」的分支判定搅浑（测试隔离，非产品行为）。
    pac2 = _p(False)
    k2, cd2 = pac2.observe("qunar", ["login"], NOTE)
    assert k2 == "login" and cd2 > 0, (k2, cd2)


def test_string_false_from_yaml_is_respected():
    """手写 yaml 的 'false' 字符串也要真的关掉（同 r519 的教训）。"""
    pac = Pacing({"crawler": {"breaker": {"enabled": "false"}}})
    assert pac.cfg["breaker_enabled"] is False
    kind, _ = pac.observe("ctrip", BLOCKED, NOTE)
    assert kind == "", "'false' 字符串没有被当成关闭：observe=%r" % kind


def test_panel_renders_the_not_tripped_state():
    """界面必须有这一档文案，否则关掉开关后只能看到「正常」。"""
    import io
    w = webui_full_src()
    i = w.index("blocked_but_open")
    seg = w[max(0, i - 400):i + 500]
    assert "被拦 · 未熔断" in seg, "面板没有「被拦 · 未熔断」这一档：%s" % seg[:260]
    assert "熔断已关闭" in seg, "没有说清为什么没熔断：%s" % seg[:260]


# ---- merged from tests/test_r652_frozen_paths.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_source_mode_uses_repo_root(monkeypatch):
    """源码态：根目录 = core/ 的上一级（仓库根）。"""
    monkeypatch.delattr(sys, "frozen", raising=False)
    root = paths.app_root()
    assert os.path.isdir(os.path.join(root, "core")), root
    assert os.path.isdir(os.path.join(root, "crawlers")), root


def test_frozen_mode_uses_exe_dir(monkeypatch, tmp_path):
    """冻结态：根目录 = exe 所在目录，不是 _internal。"""
    exe = tmp_path / "TicketMonitor.exe"
    exe.write_bytes(b"x")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe), raising=False)
    assert paths.app_root() == str(tmp_path)


def test_relative_paths_anchor_to_exe_dir(monkeypatch, tmp_path):
    """`data/prices.db` 这类相对路径要拼到 exe 目录下。"""
    exe = tmp_path / "TicketMonitor.exe"
    exe.write_bytes(b"x")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe), raising=False)
    got = paths.resolve("data/prices.db").replace("\\", "/")
    want = (str(tmp_path) + "/data/prices.db").replace("\\", "/")
    assert got == want, "%s != %s" % (got, want)
    # 绝对路径原样（用平台真实的绝对路径，别写死 Windows 盘符——
    # `D:\...` 在 POSIX 上不是绝对路径，这条断言在 CI 上必红）
    abs_path = os.path.join(os.sep, "other", "a.db")
    assert paths.resolve(abs_path) == abs_path


def test_main_and_crawlers_use_app_root_when_frozen():
    """三处根解析都要接上 core.paths，否则只修一半仍会写错位置。"""
    import io
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel in ("main.py", "crawlers/base.py", "crawlers/app_base.py"):
        src = io.open(os.path.join(root, rel), encoding="utf-8",
                      newline="").read()
        assert "core.paths import app_root" in src, "%s 未接 app_root" % rel
        assert 'getattr(sys, "frozen", False)' in src, "%s 未判冻结态" % rel


# ---- merged from tests/test_r900_low_fare_single_truth.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_low_fare_matrix_matches_radar_sources():
    bad = []
    for plat, row in CHANNEL_DIMENSIONS.items():
        caps = SPECIAL_CAPABILITY.get(plat) or {}
        has_src = bool(caps.get("sources"))
        declared = (row or {}).get("low_fare", "")
        if has_src and declared != "y":
            bad.append((plat, "雷达有源但矩阵=%r" % declared))
        if (not has_src) and declared == "y":
            bad.append((plat, "雷达无源但矩阵=y（谎称可用）"))
    assert not bad, (
        "低价机票在两处给出相反答案（矩阵 vs 特价雷达发现源）：%s" % bad)


def test_every_radar_source_owner_is_a_registered_channel():
    """雷达登记的源所属渠道，必须都在能力矩阵里（否则界面上无落点）。"""
    unknown = sorted(set(SPECIAL_CAPABILITY) - set(CHANNEL_DIMENSIONS))
    assert not unknown, "特价雷达登记了矩阵里不存在的渠道：%s" % unknown


def test_no_channel_silently_claims_low_fare_without_evidence():
    """没源的渠道必须写明原因，不能只留一个空数组。"""
    for plat, caps in SPECIAL_CAPABILITY.items():
        if caps.get("sources"):
            continue
        assert (caps.get("note") or "").strip(), (
            "%s 没有低价源，但 note 为空——用户看不出「为什么没有」" % plat)


# ---- merged from tests/test_r927_fetch_deadline.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_LOG = logging.getLogger("test_r927")


@pytest.fixture(autouse=True)
def _isolated_lock(monkeypatch):
    """把模块级设备锁换成**测试专用**的一把。

    为什么必须隔离：同一测试进程里可能还有采集线程（或前序用例遗留的
    后台线程）持着**同一把**模块级 ``_DEVICE_LOCK``。测试若用真锁去抢，
    默认 ``timeout=600`` 就会真的等 10 分钟——2026-11-04 实测把一批单测
    拖到超时（不是代码坏，是抢真锁）。换掉锁之后各用例互不影响。
    """
    monkeypatch.setattr(rt, "_DEVICE_LOCK", threading.Lock())
    monkeypatch.setattr(rt, "_LOCK_STATE", {"owner": "", "since": 0.0})
    yield


class FakeDev:
    """只有截止相关接口的假设备（真实 AdbDevice 的 adb 调用在单测里跑不起来）。"""

    def __init__(self):
        self._deadline = 0.0
        self.deadline_hits = 0
        self.calls = 0

    def set_deadline(self, budget_s=0, now=None):
        b = float(budget_s or 0)
        self._deadline = (time.time() + b) if b > 0 else 0.0
        return self._deadline

    def deadline_left(self, now=None):
        if not self._deadline:
            return 0.0
        return max(0.0, self._deadline - time.time())

    def expired(self):
        return bool(self._deadline) and self.deadline_left() <= 0

    def crawl_until_blocked(self, max_steps=5000, step_s=0.02):
        """模拟"卡住的采集"：一直调 adb，直到预算耗尽。"""
        n = 0
        while n < max_steps:
            self.calls += 1
            if self.expired():
                self.deadline_hits += 1
                return "aborted"
            time.sleep(step_s)
            n += 1
        return "never-aborted"


# ---------------------------------------------------------------------------
# 1. AdbDevice 本体
# ---------------------------------------------------------------------------
def test_deadline_off_by_default():
    d = AdbDevice("adb", "s")
    assert d.deadline_left() == 0.0
    assert d._expired() is False


def test_set_and_clear_deadline():
    d = AdbDevice("adb", "s")
    d.set_deadline(5)
    assert d.deadline_left() > 4
    d.set_deadline(0)
    assert d.deadline_left() == 0.0


def test_expired_blocks_adb_call():
    """过期后 adb 调用必须**当场返回 None**，不是继续等。"""
    d = AdbDevice("adb", "s")
    d.set_deadline(0.05)
    time.sleep(0.1)
    assert d._sh("shell", "getprop") is None
    assert d.last_error == "deadline exceeded"
    assert d.deadline_hits == 1


def test_deadline_zero_is_treated_as_off():
    d = AdbDevice("adb", "s")
    assert d.set_deadline(0) == 0.0
    assert d.set_deadline(-3) == 0.0
    assert d.set_deadline("bad") == 0.0


# ---------------------------------------------------------------------------
# 2. 锁 → 截止 → 释放（完整链路）
# ---------------------------------------------------------------------------
def _runtime(**cfg):
    base = {"enabled": True}
    base.update(cfg)
    return rt.AndroidRuntime(base, _LOG)


def test_lock_arms_deadline_and_releases_on_budget():
    r = _runtime(fetch_budget_s=0.5)
    dev = FakeDev()
    r._device = dev
    t0 = time.time()
    with r.device_lock(owner="app_qunar"):
        assert dev.deadline_left() > 0            # 拿到锁就有预算
        out = dev.crawl_until_blocked()
    elapsed = time.time() - t0
    assert out == "aborted", out                  # 到点自己退出
    assert elapsed < 3, elapsed                   # 不是挂到天荒地老
    assert r.lock_state()["owner"] == ""          # 锁已释放
    assert dev.deadline_left() == 0.0             # 预算已解除


def test_lock_releases_even_when_worker_raises():
    r = _runtime(fetch_budget_s=5)
    dev = FakeDev()
    r._device = dev
    try:
        with r.device_lock(owner="app_ctrip"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert r.lock_state()["owner"] == ""
    assert dev.deadline_left() == 0.0


def test_budget_zero_disables_feature():
    """``fetch_budget_s: 0`` = 回到旧行为（不限制）。"""
    r = _runtime(fetch_budget_s=0)
    dev = FakeDev()
    r._device = dev
    with r.device_lock(owner="app_fliggy"):
        assert dev.deadline_left() == 0.0
    assert r.lock_state()["owner"] == ""


def test_default_budget_is_below_route_timeout():
    """默认预算必须**小于**路由级超时（900s），否则 worker 还没退、路由先放弃了。"""
    r = _runtime()
    assert 0 < r._fetch_budget_s() < 900, r._fetch_budget_s()


def test_budget_is_clamped():
    assert _runtime(fetch_budget_s=99999)._fetch_budget_s() <= 3600
    assert _runtime(fetch_budget_s="bad")._fetch_budget_s() == 540.0


def test_lock_state_reports_budget():
    r = _runtime(fetch_budget_s=30)
    dev = FakeDev()
    r._device = dev
    with r.device_lock(owner="app_zhixing"):
        st = r.lock_state()
        assert st["owner"] == "app_zhixing"
        assert st["budget_left"] > 0
        assert "deadline_hits" in st


def test_no_device_does_not_break():
    """没有设备对象时（未就绪/关闭）也要能正常进出锁。"""
    r = _runtime(fetch_budget_s=10)
    r._device = None
    with r.device_lock(owner="app_qunar"):
        pass
    assert r.lock_state()["owner"] == ""
