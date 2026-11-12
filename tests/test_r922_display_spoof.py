# -*- coding: utf-8 -*-
"""r922：分辨率/DPI 伪装 + 坐标换算（设计坐标 → 设备坐标）。

背景：App 渠道的坐标**全部按 900×1600 竖屏写死**。所以「改屏幕」这件事
必须满足：改完立刻开换算，否则点击会按比例偏——仓库里已经吃过一次
（横屏 1600×900 让所有硬编码坐标失效，账本记成「设城市失败」）。

本文件钉住三层：
  1. ``display`` 的解析/计划/执行（含 density 同比缩放，保持 dp 尺寸）；
  2. ``AdbDevice`` 的正向换算（写死常量 → 设备）与逆向换算（bounds → 设计）；
  3. 边界：``design=None`` 时**完全不变**（既有行为逐字保留）。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r922_display_spoof.py -q
"""
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.android import display  # noqa: E402

_LOG = logging.getLogger("test_r922")

DESIGN = (900, 1600)


class _Dev:
    """假设备：``wm size/density`` 可读可写，``input`` 调用被记录。"""

    def __init__(self, size="900x1600", density=240, nodes=8):
        self.w = int(size.split("x")[0])
        self.h = int(size.split("x")[1])
        self.d = int(density)
        self.override = False
        self.nodes = nodes
        self.calls = []

    def _sh(self, *a, timeout=None):
        cmd = " ".join(str(x) for x in a)
        self.calls.append(cmd)
        if cmd == "shell wm size":
            return ("Physical size: 900x1600\nOverride size: %dx%d"
                    % (self.w, self.h)) if self.override else \
                   "Physical size: %dx%d" % (self.w, self.h)
        if cmd == "shell wm density":
            return ("Physical density: 240\nOverride density: %d" % self.d) \
                if self.override else "Physical density: %d" % self.d
        if cmd.startswith("shell wm size reset"):
            self.w, self.h, self.override = 900, 1600, False
            return ""
        if cmd.startswith("shell wm density reset"):
            self.d, self.override = 240, False
            return ""
        if cmd.startswith("shell wm size "):
            wh = cmd.split()[-1]
            self.w, self.h = [int(x) for x in wh.split("x")]
            self.override = True
            return ""
        if cmd.startswith("shell wm density "):
            self.d = int(cmd.split()[-1])
            self.override = True
            return ""
        return ""

    def dump(self):
        return "<node>" * self.nodes


# ---------------------------------------------------------------------------
# 1. display：读 / 计划 / 执行 / 回滚
# ---------------------------------------------------------------------------
def test_actual_reads_physical():
    got = display.actual(_Dev())
    assert (got["width"], got["height"], got["density"]) == (900, 1600, 240)
    assert got["override"] is False


def test_actual_prefers_override():
    d = _Dev()
    display.spoof(d, width=1080, height=1920, density=288)
    got = display.actual(d)
    assert (got["width"], got["height"]) == (1080, 1920)
    assert got["override"] is True


def test_plan_spoof_keeps_dp_constant():
    """density 与 height 同比 → dp 尺寸不变，界面布局不乱。"""
    p = display.plan_spoof(_Dev(), width=1080, height=1920)
    assert p["density"] == int(round(240 * (1920 / 1600.0)))   # 288
    p2 = display.plan_spoof(_Dev(), width=1080, height=1680)
    assert p2["density"] == int(round(240 * (1680 / 1600.0)))  # 252


def test_spoof_then_reset_roundtrip():
    d = _Dev()
    rep = display.spoof(d, width=1080, height=1920, density=288)
    assert rep["ok"] is True
    assert (rep["after"]["width"], rep["after"]["height"]) == (1080, 1920)
    back = display.reset(d)
    assert (back["after"]["width"], back["after"]["height"]) == (900, 1600)
    assert back["after"]["override"] is False


def test_spoof_rejects_empty_target():
    class _NoSize(_Dev):
        def _sh(self, *a, timeout=None):
            cmd = " ".join(str(x) for x in a)
            self.calls.append(cmd)
            return ""            # 读不到 wm size
    rep = display.spoof(_NoSize(), width=0, height=0)
    assert rep["ok"] is False and "目标分辨率" in rep["error"]


def test_scale_for_math():
    assert display.scale_for(DESIGN, (1080, 1920)) == (1.2, 1.2)
    assert display.scale_for(DESIGN, (900, 1600)) == (1.0, 1.0)
    assert display.scale_for(None, (1080, 1920)) == (1.0, 1.0)
    assert display.scale_for(DESIGN, (0, 0)) == (1.0, 1.0)


def test_audit_flags_mismatch():
    from core.android import fingerprint
    ident = fingerprint.build(3, vm=0)
    got = display.audit(_Dev(), ident)
    # 池里的机型不会是 900x1600 → 必然报不一致
    assert got["ok"] is False and got["issues"]


# ---------------------------------------------------------------------------
# 2. AdbDevice 坐标换算
# ---------------------------------------------------------------------------
def _device(monkeypatch, size="900x1600"):
    from core.android import device as devmod
    calls = []

    class _P:
        def __init__(self, out):
            self.stdout = out.encode()
            self.stderr = b""
            self.returncode = 0

    def _run(cmd, timeout, binary=False):
        calls.append(" ".join(cmd))
        if "wm" in cmd and "size" in cmd:
            return _P("Physical size: %s" % size)
        return _P("")
    monkeypatch.setattr(devmod, "_run", _run)
    return devmod.AdbDevice("adb", "s"), calls


def test_design_off_is_byte_identical(monkeypatch):
    d, calls = _device(monkeypatch)
    assert d.design is None
    d.tap(100, 200)
    assert any(c.endswith("input tap 100 200") for c in calls), calls


def test_window_size_prefers_override(monkeypatch):
    """``wm size`` 有两行，必须取 Override —— 否则改屏幕后换算恒为 1.0。

    2026-11-03 实机踩到：屏幕已改成 1080x1920，但 ``window_size`` 正则取到
    第一个匹配（``Physical size: 900x1600``），于是 ``scale`` 恒等、
    写死的坐标全部按原值发出去 → 点击位置全偏，而账本只表现成
    「设城市失败 / 页面认不出」。
    """
    from core.android import device as devmod

    class _P:
        def __init__(self, out):
            self.stdout = out.encode()
            self.stderr = b""
            self.returncode = 0

    def _run(cmd, timeout, binary=False):
        joined = " ".join(cmd)
        if "wm" in joined and "size" in joined:
            return _P("Physical size: 900x1600\nOverride size: 1080x1920")
        return _P("")
    monkeypatch.setattr(devmod, "_run", _run)
    d = devmod.AdbDevice("adb", "s")
    assert d.window_size() == (1080, 1920)      # 不是 (900, 1600)！


def test_window_size_falls_back_to_physical(monkeypatch):
    from core.android import device as devmod

    class _P:
        def __init__(self, out):
            self.stdout = out.encode()
            self.stderr = b""
            self.returncode = 0

    def _run(cmd, timeout, binary=False):
        joined = " ".join(cmd)
        if "wm" in joined and "size" in joined:
            return _P("Physical size: 720x1280")     # 没有 override
        return _P("")
    monkeypatch.setattr(devmod, "_run", _run)
    assert devmod.AdbDevice("adb", "s").window_size() == (720, 1280)


def test_design_on_scales_tap_and_swipe(monkeypatch):
    d, calls = _device(monkeypatch, size="1080x1920")
    d.set_design(*DESIGN)                       # 1.2×
    assert d.to_device(100, 200) == (120, 240)
    assert d.to_design(120, 240) == (100, 200)
    d.tap(100, 200)
    assert any(c.endswith("input tap 120 240") for c in calls), calls
    d.swipe(0, 0, 100, 100, 200)
    assert any(c.endswith("input swipe 0 0 120 120 200") for c in calls), calls


def test_design_roundtrip_is_stable(monkeypatch):
    d, _ = _device(monkeypatch, size="1080x2400")
    d.set_design(*DESIGN)
    for x, y in ((0, 0), (450, 800), (899, 1599)):
        dx, dy = d.to_device(x, y)
        bx, by = d.to_design(dx, dy)
        assert abs(bx - x) <= 1 and abs(by - y) <= 1, (x, y, dx, dy, bx, by)


def test_set_design_zero_disables(monkeypatch):
    d, calls = _device(monkeypatch)
    d.set_design(900, 1600)
    assert d.set_design(0, 0) is None
    d.tap(10, 10)
    assert any(c.endswith("input tap 10 10") for c in calls)


def test_unreadable_size_falls_back_to_identity(monkeypatch):
    d, calls = _device(monkeypatch, size="?")
    d.set_design(*DESIGN)
    assert d._scale() == (1.0, 1.0)             # 读不到就不换算
    d.tap(100, 200)
    assert any(c.endswith("input tap 100 200") for c in calls)


# ---------------------------------------------------------------------------
# 3. CLI 的核心行为（不起真设备：只验"目标计算 + 白屏判据"）
# ---------------------------------------------------------------------------
def test_cli_idle_hint_reads_log(tmp_path):
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import display_spoof as cli
    log = tmp_path / "monitor.log"
    log.write_text("x", encoding="utf-8")
    assert "活动" in cli._idle_hint(str(log))
    old = tmp_path / "old.log"
    old.write_text("x", encoding="utf-8")
    os.utime(old, (0, 0))
    assert "空闲" in cli._idle_hint(str(old))
    assert "读不到" in cli._idle_hint(str(tmp_path / "nope.log"))


def test_cli_ui_alive_detects_blank():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import display_spoof as cli
    ok, why = cli._ui_alive(_Dev(nodes=8))
    assert ok is True and "8" in why
    ok2, why2 = cli._ui_alive(_Dev(nodes=2))
    assert ok2 is False and "白屏" in why2
