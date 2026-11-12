# -*- coding: utf-8 -*-
"""r962：清 `service.adb.root` **不会**切断 root 通道 —— 所以这不是取舍。

背景（2026-11-04 第 61/62 轮）：
自检从 84 掉到 76，多出来的是 `prop:service.adb.root=1`。当时我判断这是
一个必须权衡的矛盾：留着 root 才能跑 `resetprop` 清 `ro.nemu`
（实测 Ctrip SDK 读到 `ro.nemu` 就返回 **50003**），而 root 本身又是一条
App 可读的标记。**这个判断是错的**，实测把它推翻了：

    setprop service.adb.root 0
      → getprop 回读 '0'
      → `adb shell id` 仍然 uid=0(root)      ← 通道没断
      → resetprop `--delete`+set 探针仍可用（读回 'tmprobe62'）
      → 自检 76 → 84，root 归空

原因是这个属性只是 init 在 adbd 起来时**记录**的状态，adbd 不监听它。

代码里真正的不变量是另一件事：`_is_vendor_prop` 对它判 False，
所以它必须靠 `_RUNTIME_ROOT_PROPS` **显式加进** `refresh()` 的清理目标 ——
少了这一条，检测就会报一个自己永远不清的洞（分数长期卡住），
而实例每次重启都会把它置回 1。本测试钉的就是这个不变量，
因为「inclusion 列表」很容易被人当成「skip 列表」反向改掉。

跑：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r962_adb_root_marker.py -q
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.android import fingerprint as fp  # noqa: E402
from core.android import stealth as st  # noqa: E402


class _Dev:
    """只回放 getprop / 记录 resetprop 脚本。"""

    def __init__(self, props):
        self.props = dict(props)
        self.calls = []
        self.scripts = []

    def _sh(self, *a, timeout=None):
        cmd = " ".join(str(x) for x in a)
        self.calls.append(cmd)
        if cmd.strip() == "shell getprop":
            return "\n".join("[%s]: [%s]" % (k, v)
                             for k, v in self.props.items())
        if cmd.startswith("shell getprop "):
            return self.props.get(cmd.split(" ", 2)[2], "")
        if cmd.startswith("shell ls -d"):
            p = cmd.split()[-1]
            return p if p in self.exists else ""
        return ""

    exists = ()

    def push(self, local, remote):
        return True


def _capture_resetprop(monkey, calls):
    """把清 props 的实际动作截下来，看看到底清了什么。"""
    monkey.setattr(fp, "_magisk",
                   lambda dev: "/data/adb/magisk/magisk resetprop")

    def fake_as_root(dev, script, timeout=None):
        calls.append(str(script))
        return ""

    monkey.setattr(fp, "as_root", fake_as_root)
    # refresh 内部是 `from .fingerprint import as_root`，函数级 import
    # 每次调用都重新绑定，所以 patch 源模块即可生效。
    return calls


VENDOR_ONLY = {"ro.product.model": "vivo", "ro.nemu": "1"}


def test_runtime_marker_is_included_in_refresh_targets(monkeypatch):
    """`service.adb.root` 必须被清 —— 它是 inclusion，不是 skip。

    `_is_vendor_prop` 对它判 False（不在厂商命名空间），所以没有
    `_RUNTIME_ROOT_PROPS` 它就永远进不了清理目标：
    检测报了个自己不管的洞，实例每次重启都会把它置回 1。
    """
    calls = _capture_resetprop(monkeypatch, [])
    d = _Dev({"ro.debuggable": "0", "service.adb.root": "1"})
    st.refresh(d)
    joined = "\n".join(calls)
    assert "service.adb.root" in joined, \
        "没清 service.adb.root：它被当成 skip 列表了（分数会永久卡住）"


def test_clearing_it_does_not_require_dropping_root(monkeypatch):
    """文档化实测结论：清这条标记和保留 root 通道**不冲突**。

    这条测试不重复做设备实验（CI 上没有设备），它钉的是代码里的
    **表述不许倒退**：一旦有人把它当"取舍"写回去（例如加一句
    "清掉会丢 root 所以别动"），后面的人会因此不敢清、
    把一条本来免费就能消的暴露面长期留着。
    """
    src = io.open(os.path.join(ROOT, "core", "android", "stealth.py"),
                  encoding="utf-8").read()
    i = src.find("_RUNTIME_ROOT_PROPS")
    ctx = src[max(0, i - 1400):i]
    assert "uid=0" in ctx, "注释里必须保留'清它不会掉 root'的实测证据"
    assert "76" in ctx and "84" in ctx, "分数对照是这条结论的来源，不能丢"


def test_vendor_props_still_cleared_together(monkeypatch):
    """同一次重清要一起覆盖厂商键，不能因为特殊列表漏掉常规项。"""
    calls = _capture_resetprop(monkeypatch, [])
    d = _Dev({"ro.nemu": "1", "service.adb.root": "1"})
    st.refresh(d)
    joined = "\n".join(calls)
    assert "ro.nemu" in joined and "service.adb.root" in joined, joined[:400]


def test_no_targets_means_no_magisk_probe(monkeypatch):
    """已干净时不许探 magisk（refresh 每轮都跑，探针一次 4~5 条 adb）。"""
    probed = []
    monkeypatch.setattr(fp, "_magisk",
                        lambda dev: probed.append(1) or "/x/magisk resetprop")
    d = _Dev({"ro.debuggable": "0", "ro.product.model": "vivo"})
    st.refresh(d)
    assert not probed, "没东西要清还去探测 magisk，白烧 adb 往返"


def test_marker_is_counted_by_detect():
    """detect 必须继续把它算作 root 证据（否则清了也没人知道有没有效）。"""

    class _D(_Dev):
        exists = ("/system/bin/sh",)

    a = _D({"ro.product.model": "vivo", "service.adb.root": "1"})
    b = _D({"ro.product.model": "vivo", "service.adb.root": "0"})
    ra, rb = st.detect(a), st.detect(b)
    assert any("service.adb.root" in x for x in ra["root"]), ra["root"]
    assert not any("service.adb.root" in x for x in rb["root"]), rb["root"]
    assert rb["score"] > ra["score"], (ra["score"], rb["score"])
