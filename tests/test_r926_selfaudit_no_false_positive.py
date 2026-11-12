# -*- coding: utf-8 -*-
"""r926：自检**不许误报**——`ls` 把目录内容当成命中，把分数扣到 0。

2026-11-04 实机现象：`[android] root/模拟器隐藏：2 条动作，自检 0 分
（剩余：fs:acct, fs:adb_keys, fs:apex, fs:bin, …）`

`acct` / `bin` / `cache` 这些**是根目录的条目**，不是我们探测的
`/system/bin/su`。根因：`ls /system/bin/su /system/xbin/su /sbin/su` 里
某个参数是**目录或符号链接**时，`ls` 会把它的**内容**列出来。于是：

* ``fingerprint.audit()`` 把 17 条目录展开当成 17 条 root 残留，`-6×17` 扣到 0 分；
* ``stealth.detect()`` 同源 bug（`ls -d /mnt/shared` 展开成根目录），也是 0 分。

后果不是"少报"，而是**谎报**：操作员看到「自检 0 分」以为隐藏失败，
去反复重装 Magisk / 改 props——而实际上早就干净了。

修法：一律 `test -e <path>` 判**路径本身**是否存在，不用 `ls`。

本文件同时钉住"清空厂商 prop 后要算干净"（`nemud.player_engine=MUMU15`
这类才是真暴露面，清空值之后不该继续扣分）。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r926_selfaudit_no_false_positive.py -q
"""
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.android import fingerprint as fp  # noqa: E402
from core.android import stealth as st  # noqa: E402

_LOG = logging.getLogger("test_r926")


class FakeDev:
    """按命令返回：``test -e`` 走 exists 集合，``getprop`` 走 props。"""

    def __init__(self, exists=(), props=None, listing=None,
                 dirs=None, modes=None):
        self.exists = set(exists)
        # 父目录（app_can_see 要查它们的权限位）
        self.dirs = set(dirs or ("/data", "/data/local", "/data/local/tmp",
                                 "/mnt", "/system", "/system/bin",
                                 "/system/xbin", "/sbin"))
        # 默认 others 有 r-x（= App 能 traverse），让旧测试语义不变；
        # 要钉"0700 看不见"就把对应目录传成 drwx------
        self.modes = dict(modes or {})
        # 至少要有一个 prop：`detect()` 拿不到任何 props 会提前返回
        # （"device offline"），后面的文件探测根本不会执行。
        self.props = dict(props if props is not None
                          else {"ro.product.model": "SM-A5260"})
        self.listing = listing or "acct\nadb_keys\napex\nbin\ncache\n"
        self.calls = []

    def _sh(self, *a, timeout=None):
        cmd = " ".join(str(x) for x in a)
        self.calls.append(cmd)
        toks = cmd.split()
        # **新契约**：`ls -d <单条路径>` 判存在、`ls -ld <父链...>` 判权限位。
        # 两者都把路径当**独立 argv**，所以不经过任何 shell 解析。
        if toks[:3] == ["shell", "ls", "-ld"]:
            out = []
            for p in toks[3:]:
                if p in self.exists or p in self.dirs:
                    mode = self.modes.get(p, "drwxr-xr-x")
                    out.append("%s 2 root root 4096 2026-11-04 12:00 %s"
                               % (mode, p))
            return "\n".join(out)
        if toks[:3] == ["shell", "ls", "-d"]:
            p = toks[3] if len(toks) > 3 else ""
            return p if (p in self.exists or p in self.dirs) else ""
        if "test -e" in cmd:
            # 旧契约（保留：钉"不许再用 sh -c 探测"——它会被 adb 拆参数恒假）
            import re as _re
            m = _re.search(r"test -e '([^']+)'", cmd)
            path = m.group(1) if m else ""
            return "TM_YES" if path in self.exists else "TM_NO"
        if cmd.startswith("shell getprop "):
            return self.props.get(cmd.split(" ", 2)[2], "")
        if cmd == "shell getprop":
            return "\n".join("[%s]: [%s]" % (k, v)
                             for k, v in self.props.items())
        if "ls " in cmd:
            return self.listing          # 模拟 ls 展开目录的恶劣行为
        return ""


# ---------------------------------------------------------------------------
# 1. audit：不能把目录内容当残留
# ---------------------------------------------------------------------------
def test_audit_does_not_expand_directories():
    """`ls` 会返回一堆根目录条目，但一条都不该被算成 root 残留。"""
    dev = FakeDev(exists=(), listing="acct\nadb_keys\napex\nbin\ncache\n")
    rep = fp.audit(dev)
    fs_leaks = [x for x in rep["leaks"] if x["key"] == "fs"]
    assert fs_leaks == [], fs_leaks
    assert rep["score"] >= 60, rep["score"]


def test_audit_reports_real_su_only():
    dev = FakeDev(exists={"/system/xbin/su"}, listing="acct\nbin\n")
    rep = fp.audit(dev)
    fs_leaks = [x["value"] for x in rep["leaks"] if x["key"] == "fs"]
    assert fs_leaks == ["/system/xbin/su"], fs_leaks


def test_audit_probe_avoids_shell_metacharacters(monkeypatch):
    """探测必须把路径当**独立 argv**，不许包 `sh -c`。

    这条测试曾经反向钉住了一个错误实现（`sh -c "test -e X && echo A || echo B"`），
    而那个实现是**恒假**的：adb 把命令行按空格拆开送进设备 shell，设备执行的是
    `sh -c test`（内层拿不到参数 → 恒假）+ 外层 `|| echo TM_NO`
    → 任何路径都判"不存在"，`root 痕迹: []` 于是从来没有意义。
    用 `/system/bin/sh`（必然存在）一测就露馅。

    但**原始意图仍然要保住**：不能退回去用不带 `-d` 的 `ls <路径>`，
    那会把目录内容列出来 → 17 条幽灵残留、自检被打到 0 分。
    所以钉的是：用 `ls -d`/`ls -ld`，且不出现 shell 元字符。
    """
    dev = FakeDev(exists={"/system/bin/sh"})
    assert fp._exact_path_exists(dev, "/system/bin/sh") is True, \
        "探针又恒假了：存在的文件判不出存在"
    joined = "\n".join(dev.calls)
    assert "test -e" not in joined, "还在用 sh -c 探测（会被拆参数 → 恒假）"
    assert '"sh", "-c"' not in joined, "探测命令被包进 sh -c"
    # 反幽灵：不许出现"不带 -d/-ld 的 ls <单个路径>"
    assert "ls /system/bin/su" not in joined, "退回了会展开目录的 ls"


# ---------------------------------------------------------------------------
# 2. stealth.detect：同源 bug
# ---------------------------------------------------------------------------
def test_detect_does_not_expand_shared_dir():
    """`/mnt/shared` 常是符号链接；`ls` 会展开成根目录，不能算共享目录命中。"""
    dev = FakeDev(exists=(), listing="acct\nadb_keys\napex\nbin\n")
    rep = st.detect(dev)
    shared = [x for x in rep["emulator"] if x.startswith("shared:")]
    assert shared == [], shared
    assert rep["score"] >= 60, rep["score"]


def test_detect_reports_real_shared_dir():
    dev = FakeDev(exists={"/mnt/shared"}, listing="acct\n")
    rep = st.detect(dev)
    assert any("/mnt/shared" in x for x in rep["emulator"]), rep["emulator"]


# ---------------------------------------------------------------------------
# 3. 厂商 prop：值非空才算暴露面，清空后要算干净
# ---------------------------------------------------------------------------
def test_vendor_prop_with_value_is_leak():
    dev = FakeDev(props={"nemud.player_engine": "MUMU15"})
    rep = st.detect(dev)
    assert any("nemud" in x for x in rep["emulator"]), rep["emulator"]


def test_vendor_prop_cleared_is_not_leak():
    """清空值之后不再自报"我是 MUMU15"，就不该继续扣分。"""
    dev = FakeDev(props={"nemud.player_engine": "",
                         "nemud.player_architecture": ""})
    rep = st.detect(dev)
    assert not any("nemud" in x for x in rep["emulator"]), rep["emulator"]


def test_is_vendor_prop_ignores_system_runtime_keys():
    """`init.svc.*` 是系统运行态：删不掉，也不算厂商残留。"""
    assert st._is_vendor_prop("init.svc.nemud", "running") is False
    assert st._is_vendor_prop("init.svc_debug_pid.nemuinit", "1600") is False
    assert st._is_vendor_prop("nemud.player_engine", "MUMU15") is True
    assert st._is_vendor_prop("nemud.player_engine", "") is False


# ---------------------------------------------------------------------------
# 4. hide：没有 Magisk 也要清（用 setprop 写空）
# ---------------------------------------------------------------------------
def test_hide_clears_vendor_props_without_resetprop(monkeypatch):
    """无 Magisk 时 `resetprop` 不可用，但厂商键不是 ro.*，清空可行。"""
    dev = FakeDev(props={"nemud.player_engine": "MUMU15"})

    monkeypatch.setattr(st, "_root", lambda d: True)
    monkeypatch.setattr(st, "_magisk", lambda d: "")
    monkeypatch.setattr(st, "boot_id", lambda d: "boot-x", raising=False)

    captured = {}

    def _as_root(d, script, timeout=None):
        captured["script"] = script
        return ""
    monkeypatch.setattr(st, "as_root", _as_root)

    st.hide(dev, packages=["ctrip"])
    script = captured.get("script", "")
    assert "setprop" in script
    assert "nemud.player_engine" in script
    # 用清空（''）而不是依赖 resetprop --delete
    assert "'nemud.player_engine' ''" in script or "'' " in script
