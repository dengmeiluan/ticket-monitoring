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

    def __init__(self, exists=(), props=None, listing=None):
        self.exists = set(exists)
        # 至少要有一个 prop：`detect()` 拿不到任何 props 会提前返回
        # （"device offline"），后面的文件探测根本不会执行。
        self.props = dict(props if props is not None
                          else {"ro.product.model": "SM-A5260"})
        self.listing = listing or "acct\nadb_keys\napex\nbin\ncache\n"
        self.calls = []

    def _sh(self, *a, timeout=None):
        cmd = " ".join(str(x) for x in a)
        self.calls.append(cmd)
        if "test -e" in cmd:
            # 形如: sh -c "test -e '/system/bin/su' && echo TM_YES || echo TM_NO"
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


def test_audit_uses_test_e_not_ls(monkeypatch):
    dev = FakeDev(exists=())
    fp.audit(dev)
    joined = "\n".join(dev.calls)
    assert "test -e" in joined
    # 不该再用 ls 去探那几个路径
    assert "ls /system/bin/su" not in joined


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
