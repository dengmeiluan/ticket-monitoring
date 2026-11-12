# -*- coding: utf-8 -*-
"""r943：Magisk `resetprop` 引导——让 `ro.nemu` 的清空能扛住重启。

背景（2026-11-04 实测全链路）
----------------------------
1. 携程 App 登录提交验证码 → **`存在风险，限制登录 50003`**；
2. 设备指纹只剩两条暴露面：`ro.nemu=1`、`ro.build.version.nemux=true`
   （`nemud.*` 40 条值已全为空）；
3. `ro.nemu` **硬编码在 `/system/bin/nemuinit`**（5.19MB 二进制），
   不在任何 `.config` 里 → 改配置不可行；
4. MuMu 只给 `adb root`，没有 `resetprop` 命令。但**把 Magisk APK 里的
   `lib/x86_64/libmagisk.so` 提出来改名 `magisk`，它自带 `resetprop`
   子命令** —— 实测能清掉 `ro.nemu`（`1` → 空），系统无副作用；
5. 清掉之后携程登录从「50003 限制登录」变成「请完成拼图验证」。

两个必须分清的事实：

* **二进制部署是持久的** —— `/data/local/tmp/magisk_bin/` 在 /data 分区；
* **props 是内存态** —— 实例重启后 MuMu 的 `nemuinit` 会重新 set 回去。

所以每次启动都要"确认二进制在 + 再清一次"。`scripts/magisk_bootstrap.py`
的 `ensure()` 就是这件事，已接进 `hardening.harden()` 的 **⓪ 步**
（在 ① 身份、③ stealth 之前，因为 stealth 依赖 resetprop）。

实测硬化后：**自检 100 分（剩余：无）**，7 个步骤全 True。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r943_magisk_bootstrap.py -q
"""
import importlib.util
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_BOOT = os.path.join(ROOT, "scripts", "magisk_bootstrap.py")


def _mod():
    spec = importlib.util.spec_from_file_location("_mb_test", _BOOT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class FakeDev:
    """按命令回放：props 字典 + 可选的 magisk 二进制存在性。"""

    def __init__(self, props=None, has_bin=False, push_ok=True):
        self.props = dict(props or {})
        self.has_bin = has_bin
        self.push_ok = push_ok
        self.calls = []
        self.pushed = []

    def _sh(self, *a, timeout=None):
        cmd = " ".join(str(x) for x in a)
        self.calls.append(cmd)
        if cmd.startswith("shell getprop "):
            return self.props.get(cmd.split(" ", 2)[2], "")
        if cmd == "shell getprop":
            return "\n".join("[%s]: [%s]" % (k, v)
                             for k, v in self.props.items())
        if cmd.startswith("shell ls "):
            p = cmd[len("shell ls "):].strip()
            if not self.has_bin:
                return ""
            if p.endswith("/magisk") and "magisk_bin" in p:
                return "/data/local/tmp/magisk_bin/magisk\n"
            if p.endswith("/resetprop"):
                return ""
            return ""
        if "resetprop" in cmd:
            # **模拟真实语义**：`--delete k` 删键、`k v` 设值。
            # `_magisk()` 现在拿 `ro.boot.revision` 做 delete-then-set 探针
            # （只看文件在不在会被"静默失败"骗——实测 `/data/adb/magisk/`
            #  缺配套文件时 md5 相同却改不动 ro.*），假设备必须答得上这个探针。
            parts = cmd.split()
            if "--delete" in parts:
                _i = parts.index("--delete")
                if _i + 1 < len(parts):
                    self.props[parts[_i + 1].strip("'")] = ""
                return ""
            _i = parts.index("resetprop")
            if _i + 2 < len(parts):
                self.props[parts[_i + 1].strip("'")] = parts[_i + 2].strip("'")
            return ""
        return ""

    # push 接口（脚本里优先用它）
    def push(self, local, remote):
        self.pushed.append((local, remote))
        return self.push_ok

    def connect(self):
        return True


# ---------------------------------------------------------------------------
# 1. probe：现状可读
# ---------------------------------------------------------------------------
def test_probe_reports_bin_and_exposure():
    m = _mod()
    d = FakeDev({"ro.nemu": "1", "ro.build.version.nemux": "true"}, has_bin=True)
    st = m.probe(d)
    assert st["bin_ok"] is True
    assert st["resetprop"].endswith("magisk resetprop")
    assert set(st["exposed"]) == {"ro.nemu", "ro.build.version.nemux"}


def test_probe_clean_device_is_ok():
    m = _mod()
    d = FakeDev({"ro.nemu": "", "ro.build.version.nemux": ""}, has_bin=True)
    st = m.probe(d)
    assert st["exposed"] == []
    assert st["bin_ok"] is True


# ---------------------------------------------------------------------------
# 2. clear_props：必须**读回校验**（防"报成功但没变"）
# ---------------------------------------------------------------------------
def test_clear_props_verifies_by_readback():
    m = _mod()
    d = FakeDev({"ro.nemu": "1", "ro.build.version.nemux": "true"}, has_bin=True)
    rep = m.clear_props(d)
    assert rep["ok"] is True
    assert set(rep["cleared"]) == {"ro.nemu", "ro.build.version.nemux"}
    assert rep["still"] == []


def test_clear_props_reports_still_when_ineffective():
    """resetprop 报成功但值没变 → 必须如实报 still（不许假成功）。"""
    m = _mod()
    d = FakeDev({"ro.nemu": "1"}, has_bin=True)

    # 让 resetprop **命令能跑通但值不变**（真实 MuMu 上 setprop 的老毛病）。
    # 探针要放行，否则测到的是"根本没有 resetprop"，不是这条。
    def _sh(*a, timeout=None):
        cmd = " ".join(str(x) for x in a)
        d.calls.append(cmd)
        if cmd.startswith("shell getprop "):
            return d.props.get(cmd.split(" ", 2)[2], "")
        if cmd.startswith("shell ls "):
            return "/data/local/tmp/magisk_bin/magisk\n"
        if "resetprop" in cmd:
            # 只对探针键生效，其余一律 no-op
            parts = cmd.split()
            if "--delete" in parts:
                _i = parts.index("--delete")
                if parts[_i + 1].strip("'") == "ro.boot.revision":
                    d.props["ro.boot.revision"] = ""
            else:
                _i = parts.index("resetprop")
                if parts[_i + 1].strip("'") == "ro.boot.revision":
                    d.props["ro.boot.revision"] = parts[_i + 2].strip("'")
            return ""
        return ""
    d._sh = _sh
    rep = m.clear_props(d)
    assert rep["ok"] is False
    assert "ro.nemu" in rep["still"]


def test_clear_props_without_resetprop_is_honest():
    m = _mod()
    d = FakeDev({"ro.nemu": "1"}, has_bin=False)
    rep = m.clear_props(d)
    assert rep["ok"] is False
    assert "resetprop" in rep["detail"]


# ---------------------------------------------------------------------------
# 3. ensure：二进制不在就部署，然后清
# ---------------------------------------------------------------------------
def test_ensure_clears_when_bin_present():
    m = _mod()
    d = FakeDev({"ro.nemu": "1", "ro.build.version.nemux": "true"}, has_bin=True)
    out = m.ensure(d)
    assert out["clear"] and out["clear"]["ok"] is True
    assert out["deploy"] is None                 # 已在就不重复部署


def test_ensure_never_raises():
    """任何异常都不许把硬化流程带崩。"""
    m = _mod()

    class Bad:
        def __getattr__(self, n):
            def _f(*a, **k):
                raise RuntimeError("device gone")
            return _f
    try:
        out = m.ensure(Bad())
    except Exception as e:                        # noqa: BLE001
        raise AssertionError("ensure 抛了：%s" % e)
    assert isinstance(out, dict)


# ---------------------------------------------------------------------------
# 4. 源码钉：接进 harden，且位置在 stealth 之前
# ---------------------------------------------------------------------------
def test_hardening_calls_magisk_bootstrap():
    src = io.open(os.path.join(ROOT, "core", "android", "hardening.py"),
                  encoding="utf-8").read()
    assert "magisk_bootstrap" in src, "硬化流程没接 Magisk 引导"
    assert "magisk-resetprop" in src, "没有独立的步骤名"
    # 必须在 ③ stealth 之前（stealth 依赖 resetprop 才能清 ro.*）
    i_magisk = src.find("magisk_bootstrap")
    i_stealth = src.find("stealth_mod.prepare")
    if i_stealth < 0:
        i_stealth = src.find('rep["stealth"]')
    assert i_stealth < 0 or i_magisk < i_stealth, \
        "Magisk 引导跑到 stealth 之后了（那 stealth 就没有 resetprop 可用）"


def test_bootstrap_has_restore_path():
    """要能回滚（恢复 ro.nemu=1），便于 A/B 对比与排障。"""
    src = io.open(_BOOT, encoding="utf-8").read()
    assert "def restore(" in src
    assert "ro.nemu" in src and "ro.build.version.nemux" in src
