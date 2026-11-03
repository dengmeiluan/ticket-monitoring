# -*- coding: utf-8 -*-
"""设备硬化：ABI 可行性验证 / 分辨率对齐 / 坐标换算 / 编排顺序。

这台模块最容易出的错是"改完没恢复"和"顺序错"，所以钉的是：
  * canary 无论成功/失败/抛异常，**一定**把 props 恢复回去；
  * 判定落盘，且 ``spoof_allowed`` 有 7 天有效期（App 升级会换 so）；
  * ``display.align_identity`` 只改档案、不动设备设置；
  * ``AdbDevice`` 未开启设计坐标系时行为逐字不变，开启后正向/逆向换算自洽；
  * ``hardening.harden`` 的五步顺序固定：身份 → 显示 → 隐藏 → 调优 → ABI。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r915_android_hardening.py -q
"""
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest  # noqa: E402

from core.android import abi_canary, display, fingerprint, hardening  # noqa: E402

_LOG = logging.getLogger("test_r915")

_ABI_PROPS = dict(abi_canary.ABI_X86)


class FakeDev:
    """够用的 adb 替身：props / settings / wm / logcat / am / dump。

    ``apply_noop=True`` 模拟「ro.* 只读、setprop 静默无效」——2026-11-03 在无
    Magisk 的 MuMu 上实测到的真实情况，用来钉住 canary 不许把它判成成功。
    """

    def __init__(self, props=None, logcat="", activity="", xml="<node>" * 8,
                 size="Physical size: 900x1600", density="Physical density: 320",
                 fail_activity=False, apply_noop=False, can_write=True):
        self.props = dict(props if props is not None else _ABI_PROPS)
        self.logcat = logcat
        self.activity = activity
        self.xml = xml
        self.size = size
        self.density = density
        self.fail_activity = fail_activity
        self.apply_noop = apply_noop
        # can_write=True 模拟"有 Magisk/resetprop"的实例；False 模拟实测的
        # 那台 MuMu（三条路全堵）
        self.can_write = can_write
        self.calls = []
        self.mark = ""
        self._su = True

    def _sh(self, *args, timeout=None):
        cmd = " ".join(str(a) for a in args)
        self.calls.append(cmd)
        return self._route(cmd)

    def _route(self, cmd):
        if cmd.startswith("shell getprop "):
            return self.props.get(cmd.split(" ", 2)[2], "")
        if cmd == "shell getprop":
            return "\n".join("[%s]: [%s]" % (k, v) for k, v in self.props.items())
        if "command -v resetprop" in cmd:
            return "/data/adb/magisk/resetprop" if self.can_write else ""
        if "command -v su" in cmd:
            return "/system/bin/su" if self._su else ""
        if "remount,rw" in cmd:
            # 模拟实测：块设备只读 → touch 失败
            return "mount: '/dev/block/sda6' is read-only\nTM_RW_FAIL\n"
        if "boot_id" in cmd:
            return "boot-1"
        if cmd.startswith("shell logcat -c"):
            # 假设备不清日志：这些测试要看的是"启动后出现了什么崩溃行"，
            # 清掉反而测不到（真机上 `logcat -c` 是必要的）。
            return ""
        if cmd.startswith("shell logcat"):
            return self.logcat
        if cmd.startswith("shell am force-stop"):
            return ""
        if cmd.startswith("shell monkey"):
            return "Events injected: 1"
        if cmd.startswith("shell current") or "dumpsys activity" in cmd:
            if self.fail_activity:
                raise RuntimeError("device gone")
            return "topResumedActivity=ActivityRecord{x y %s/Launcher}" % (
                self.activity or "com.example")
        if cmd.startswith("shell dumpsys package"):
            # 与实机一致（2026-11-03 实测 MuMu/Android 15）：目标包都是
            # arm64-v8a 主 ABI。预检据此判 low，canary 才肯动手。
            pkg = cmd.rsplit(" ", 1)[-1]
            return ("Packages:\n  Package [%s]\n    primaryCpuAbi=%s\n"
                    "    secondaryCpuAbi=null\n" % (pkg,
                                                  getattr(self, "primary",
                                                          "arm64-v8a")))
        if cmd.startswith("shell wm size"):
            return self.size
        if cmd.startswith("shell wm density"):
            return self.density
        if "-n " in cmd or "setprop" in cmd:
            # 只解析两种真实形态：`setprop 'KEY' 'VAL'` 与
            # `<path>/resetprop -n 'KEY' 'VAL'`（apply_props 就是把它们拼成
            # 一条 `... && echo OK ... || echo FAIL ...` 的脚本）。
            import re as _re
            out = []
            for m in _re.finditer(r"(?:setprop|-n)\s+'([^']+)'\s+'([^']*)'", cmd):
                key, val = m.group(1), m.group(2)
                if not self.apply_noop:
                    self.props[key] = val
                out.append("OK " + key)
            return "\n".join(out)
        if "cat /data/local/tmp/tm_" in cmd:
            return self.mark
        return ""

    # probe 走 current_activity / dump
    def current_activity(self):
        if self.fail_activity:
            raise RuntimeError("device gone")
        # 真实 AdbDevice 返回 `pkg/Activity`，probe 按 `/` 前段比对包名
        return "%s/.Main" % (self.activity or "com.example")

    def dump(self):
        return self.xml


# ---------------------------------------------------------------------------
# 1. ABI canary
# ---------------------------------------------------------------------------
def test_canary_ok_path_restores_and_persists(tmp_path):
    dev = FakeDev(activity="ctrip.android.view")
    rep = abi_canary.run(dev, "ctrip.android.view", {}, _LOG,
                         user_data_dir=str(tmp_path), restart_wait_s=1)
    assert rep["ok"] is True
    assert rep["restored"] is True
    # 恢复的是原值，不是硬编码
    assert rep["after"].get("ro.product.cpu.abi") == _ABI_PROPS["ro.product.cpu.abi"]
    assert abi_canary.spoof_allowed("ctrip.android.view", str(tmp_path)) is True
    # 落盘可读
    v = abi_canary.verdict(str(tmp_path))
    assert v["ctrip.android.view"]["ok"] is True


def test_canary_failure_still_restores_and_records(tmp_path):
    dev = FakeDev(activity="ctrip.android.view",
                  logcat="E AndroidRuntime: Process: ctrip.android.view, "
                         "java.lang.UnsatisfiedLinkError: libx.so")
    rep = abi_canary.run(dev, "ctrip.android.view", {}, _LOG,
                         user_data_dir=str(tmp_path), restart_wait_s=1)
    assert rep["ok"] is False
    assert rep["restored"] is True
    assert "UnsatisfiedLinkError" in (rep["probe"]["errors"] or [])
    assert abi_canary.spoof_allowed("ctrip.android.view", str(tmp_path)) is False


def test_probe_ignores_foreign_crashes(tmp_path):
    """框架重启时 system_server 的 SIGSEGV 不能算到 App 头上。"""
    dev = FakeDev(activity="ctrip.android.view",
                  logcat="F DEBUG: pid 1234, tid 1234, SIGSEGV\n"
                         "E ActivityManager: ANR in system_server")
    rep = abi_canary.probe(dev, "ctrip.android.view", wait_s=2)
    assert rep["errors"] == []
    assert rep["foreign_crashes"] >= 1


def test_canary_restores_even_when_probe_raises(tmp_path):
    dev = FakeDev(activity="ctrip.android.view", fail_activity=True)
    rep = abi_canary.run(dev, "ctrip.android.view", {}, _LOG,
                         user_data_dir=str(tmp_path), restart_wait_s=1)
    assert rep["ok"] is False
    # 关键：异常路径也必须恢复
    assert rep["restored"] is True
    assert any("wm" in c or "setprop" in c or "-n " in c for c in dev.calls)


def _writes(dev):
    """从调用记录里挑出**真正的写入**（能力探测里的 `command -v resetprop`
    含 `-n `，不是写）。"""
    return [c for c in dev.calls
            if "setprop '" in c or "resetprop -n '" in c]


def test_canary_dry_run_does_not_touch_device(tmp_path):
    dev = FakeDev()
    rep = abi_canary.run(dev, "ctrip.android.view", {}, _LOG,
                         user_data_dir=str(tmp_path), restart_wait_s=1, dry_run=True)
    assert rep["ok"] is True and rep["dry_run"] is True
    assert _writes(dev) == []


def test_spoof_allowed_expires(tmp_path):
    dev = FakeDev(activity="ctrip.android.view")
    abi_canary.run(dev, "ctrip.android.view", {}, _LOG,
                   user_data_dir=str(tmp_path), restart_wait_s=1)
    import time as _t
    assert abi_canary.spoof_allowed("ctrip.android.view", str(tmp_path),
                                    now=_t.time() + 8 * 86400) is False
    assert abi_canary.spoof_allowed("nope.pkg", str(tmp_path)) is False


# ---------------------------------------------------------------------------
# 1b. 只读预检（判定「改了会不会炸」）
# ---------------------------------------------------------------------------
def _abi_dev(abilist="x86_64,arm64-v8a,x86", abilist64="x86_64,arm64-v8a",
             bridge="libnb.so", primary="arm64-v8a", can_write=True):
    """造一台带 dumpsys 输出的设备。"""
    dev = FakeDev(can_write=can_write)
    dev.props.update({"ro.product.cpu.abilist": abilist,
                      "ro.product.cpu.abilist64": abilist64,
                      "ro.dalvik.vm.native.bridge": bridge})
    dev.primary = primary
    orig = dev._route

    def _route(cmd):
        if cmd.startswith("shell dumpsys package"):
            pkg = cmd.rsplit(" ", 1)[-1]
            return ("Packages:\n  Package [%s]\n    primaryCpuAbi=%s\n"
                    "    secondaryCpuAbi=null\n    versionCode=1\n"
                    % (pkg, dev.primary))
        return orig(cmd)
    dev._route = _route
    return dev


def test_preflight_low_when_all_packages_are_arm64():
    dev = _abi_dev(primary="arm64-v8a")
    rep = abi_canary.preflight(dev, ["ctrip.android.view", "com.Qunar"])
    assert rep["ok"] is True and rep["risk"] == "low"
    assert "so 选择已定" in rep["why"]
    assert set(rep["packages"]) == {"ctrip.android.view", "com.Qunar"}


def test_preflight_high_when_packages_still_x86():
    dev = _abi_dev(primary="x86_64")
    rep = abi_canary.preflight(dev, ["ctrip.android.view"])
    assert rep["ok"] is False and rep["risk"] == "high"
    assert "x86_64" in rep["why"]


def test_preflight_medium_when_mixed(tmp_path):
    dev = _abi_dev(primary="arm64-v8a")
    orig = dev._route
    seen = {"n": 0}

    def _route(cmd):
        if cmd.startswith("shell dumpsys package"):
            seen["n"] += 1
            pkg = cmd.rsplit(" ", 1)[-1]
            abi = "arm64-v8a" if "ctrip" in pkg else "x86_64"
            return "primaryCpuAbi=%s\nsecondaryCpuAbi=null\n" % abi
        return orig(cmd)
    dev._route = _route
    rep = abi_canary.preflight(dev, ["ctrip.android.view", "com.Qunar"])
    assert rep["risk"] == "medium" and rep["ok"] is True


def test_preflight_blocked_without_arm_runtime():
    dev = _abi_dev(abilist="x86_64,x86", abilist64="x86_64", bridge="")
    rep = abi_canary.preflight(dev, ["ctrip.android.view"])
    assert rep["ok"] is False and rep["risk"] == "blocked"
    assert "没有 arm64-v8a" in rep["why"]


def test_preflight_no_installed_package():
    dev = _abi_dev()
    orig = dev._route
    dev._route = lambda cmd: ("Unable to find package" if "dumpsys" in cmd
                              else orig(cmd))
    rep = abi_canary.preflight(dev, ["com.nope"])
    assert rep["ok"] is False
    assert "没有已安装" in rep["why"]


def test_preflight_blocked_when_no_write_channel():
    """无 Magisk + 块设备只读 → **全局** ro.* 改不了，必须判 blocked。

    这种情况下即使 app 全是 arm64，也不能让 canary 白跑一次
    「命令报成功、读回没变」的过程。

    但提示必须指向**能走通的那条路**（MuMu 官方 per-app ABI 表）——
    2026-11-03 实测 ABI 伪装已通过 abi-select 表跑通，与全局 ro.* 无关。
    """
    dev = _abi_dev(primary="arm64-v8a", can_write=False)
    rep = abi_canary.preflight(dev, ["ctrip.android.view"])
    assert rep["ok"] is False and rep["risk"] == "blocked"
    assert "ro.*" in rep["why"]
    assert rep["capabilities"]["can_write_ro"] is False
    # 提示里要有「官方 per-app 表」这条真正可走的路，以及 Magisk 作为兜底
    assert "set_app_abi" in rep["why"] or "per-app" in rep["why"], rep["why"]
    assert "Magisk" in rep["why"]


def test_canary_refuses_without_write_channel(tmp_path):
    dev = _abi_dev(primary="arm64-v8a", can_write=False)
    rep = abi_canary.run(dev, "ctrip.android.view", {}, _LOG,
                         user_data_dir=str(tmp_path), restart_wait_s=1)
    assert rep["ok"] is False and "预检未通过" in rep["error"]
    assert _writes(dev) == []
    assert abi_canary.spoof_allowed("ctrip.android.view", str(tmp_path)) is False


def test_canary_refuses_when_preflight_blocks(tmp_path):
    """预检不过时**一个 prop 都不许写**——canary 自己不能把设备改坏。"""
    dev = _abi_dev(abilist="x86_64,x86", abilist64="x86_64", bridge="")
    rep = abi_canary.run(dev, "ctrip.android.view", {}, _LOG,
                         user_data_dir=str(tmp_path), restart_wait_s=1)
    assert rep["ok"] is False
    assert "预检未通过" in rep["error"]
    assert _writes(dev) == []
    # 也不许落 ok 判定
    assert abi_canary.spoof_allowed("ctrip.android.view", str(tmp_path)) is False


def test_canary_refuses_when_props_are_readonly(tmp_path):
    """这台 MuMu 的真实情况：无 Magisk，setprop 对 ro.* 静默无效。

    命令全报 OK、读回一条没变 —— 必须判成「写不进去」并给出原因，
    **不许**把它当成可行、更不许落 ok 判定。
    """
    dev = FakeDev(activity="ctrip.android.view", apply_noop=True)
    rep = abi_canary.run(dev, "ctrip.android.view", {}, _LOG,
                         user_data_dir=str(tmp_path), restart_wait_s=1)
    assert rep["ok"] is False and rep["wrote"] is False
    assert "读回生效" in rep["error"]
    assert not rep["probe"]                      # 没写进去就不该探活
    assert abi_canary.spoof_allowed("ctrip.android.view", str(tmp_path)) is False


# ---------------------------------------------------------------------------
# 2. 显示：解析 / 对齐 / 计划 / 缩放
# ---------------------------------------------------------------------------
def test_display_actual_prefers_override():
    dev = FakeDev(size="Physical size: 720x1280\nOverride size: 1080x2400",
                  density="Physical density: 320\nOverride density: 440")
    got = display.actual(dev)
    assert (got["width"], got["height"]) == (1080, 2400)
    assert got["density"] == 440 and got["override"] is True


def test_align_identity_rewrites_profile_only():
    ident = fingerprint.build(5, vm=0)
    before_display = list(ident.profile.get("display") or [])
    dev = FakeDev(size="Physical size: 900x1600", density="Physical density: 320")
    rep = display.align_identity(ident, dev)
    assert rep["changed"] is True
    assert ident.profile["display"] == [900, 1600]
    assert ident.profile["density"] == 320
    assert before_display != ident.profile["display"]
    # 不动设备设置
    assert not [c for c in dev.calls if c.startswith("shell wm size ") and
                "reset" not in c]


def test_plan_spoof_keeps_dp_size_constant():
    dev = FakeDev(size="Physical size: 900x1600", density="Physical density: 320")
    p = display.plan_spoof(dev, width=1080, height=1920)
    # 1920/1600 = 1.2 → density 320*1.2 = 384
    assert (p["width"], p["height"]) == (1080, 1920)
    assert p["density"] == 384


def test_scale_for_and_audit():
    assert display.scale_for((900, 1600), (1080, 1920)) == (1.2, 1.2)
    assert display.scale_for(None, None) == (1.0, 1.0)
    assert display.scale_for((0, 0), (100, 100)) == (1.0, 1.0)
    ident = fingerprint.build(1, vm=0)
    dev = FakeDev(size="Physical size: 900x1600", density="Physical density: 320")
    got = display.audit(dev, ident)
    assert got["ok"] is False and got["issues"]     # 池里机型不会是 900x1600


# ---------------------------------------------------------------------------
# 3. AdbDevice 坐标换算
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
    d = devmod.AdbDevice("adb", "127.0.0.1:16384")
    return d, calls


def test_device_without_design_is_unchanged(monkeypatch):
    d, calls = _device(monkeypatch)
    assert d.tap(100, 200) is True
    assert any(c.endswith("input tap 100 200") for c in calls)


def test_device_scales_when_design_set(monkeypatch):
    d, calls = _device(monkeypatch, size="1080x1920")
    d.set_design(900, 1600)                     # 1.2×
    assert d.to_device(100, 200) == (120, 240)
    assert d.to_design(120, 240) == (100, 200)
    d.tap(100, 200)
    assert any(c.endswith("input tap 120 240") for c in calls), calls
    d.swipe(0, 0, 100, 100, 200)
    assert any(c.endswith("input swipe 0 0 120 120 200") for c in calls), calls


def test_device_set_design_zero_disables(monkeypatch):
    d, _ = _device(monkeypatch)
    d.set_design(900, 1600)
    assert d.set_design(0, 0) is None
    assert d.to_device(10, 10) == (10, 10)


# ---------------------------------------------------------------------------
# 4. 编排顺序与 ABI 闸门
# ---------------------------------------------------------------------------
def test_harden_runs_steps_in_fixed_order(monkeypatch, tmp_path):
    order = []

    def _ident(dev, cfg, log, **kw):
        order.append("identity")
        return {"ok": True}

    def _stealth(dev, cfg, log, **kw):
        order.append("stealth")
        return {"ok": True}

    def _tune(dev, cfg, log, **kw):
        order.append("tuning")
        return {"ok": True}

    monkeypatch.setattr(fingerprint, "ensure", _ident)
    from core.android import stealth as st_mod
    from core.android import emulator_tuning as tune_mod
    monkeypatch.setattr(st_mod, "prepare", _stealth)
    monkeypatch.setattr(tune_mod, "apply", _tune)

    dev = FakeDev()
    rep = hardening.harden(dev, {"android": {}}, _LOG,
                           user_data_dir=str(tmp_path))
    assert order == ["identity", "stealth", "tuning"]
    assert rep["ok"] is True
    # 没有身份文件就不做对齐，但也不报错
    assert [s for s in rep["steps"] if s[0] == "display-align"][0][1] is True


def test_harden_aligns_display_when_identity_exists(monkeypatch, tmp_path):
    store = fingerprint.default_store(str(tmp_path), "device")
    ident = fingerprint.build(9, vm=0)
    store.put(ident)

    monkeypatch.setattr(fingerprint, "ensure",
                        lambda *a, **k: {"ok": True, "skipped": "test"})
    from core.android import stealth as st_mod
    from core.android import emulator_tuning as tune_mod
    monkeypatch.setattr(st_mod, "prepare", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(tune_mod, "apply", lambda *a, **k: {"ok": True})

    dev = FakeDev(size="Physical size: 900x1600", density="Physical density: 320")
    rep = hardening.harden(dev, {"android": {}}, _LOG,
                           user_data_dir=str(tmp_path))
    assert rep["display"]["align"]["changed"] is True
    saved = fingerprint.default_store(str(tmp_path), "device").get(0)
    assert saved.profile["display"] == [900, 1600]


def test_abi_gate_off_by_default(monkeypatch, tmp_path):
    dev = FakeDev()
    rep = hardening._abi_gate(dev, {"android": {}}, _LOG,
                              user_data_dir=str(tmp_path))
    assert rep["ok"] is True and "skipped" in rep
    assert not [c for c in dev.calls if "-n " in c]


def test_abi_gate_auto_requires_canary_verdict(monkeypatch, tmp_path):
    cfg = {"android": {"identity": {"spoof_abi": "auto"}}}
    dev = FakeDev()
    rep = hardening._abi_gate(dev, cfg, _LOG, user_data_dir=str(tmp_path))
    assert rep["ok"] is True and "canary" in rep["skipped"]
    assert not [c for c in dev.calls if "-n " in c]

    # 造一份 ok 判定 → 允许写
    import json
    import time
    path = os.path.join(str(tmp_path), "device", "abi_canary.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pkg = next(iter(__import__("core.android.stealth", fromlist=["x"])
                    .KNOWN_APPS.values()))
    with open(path, "w", encoding="utf-8") as f:
        json.dump({pkg: {"ok": True, "at": time.time()}}, f)
    dev2 = FakeDev()
    rep2 = hardening._abi_gate(dev2, cfg, _LOG, user_data_dir=str(tmp_path))
    assert rep2["ok"] is True and rep2.get("apply", {}).get("applied")
