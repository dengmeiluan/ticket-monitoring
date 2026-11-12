# -*- coding: utf-8 -*-
"""/proc/cpuinfo 伪装的前置校验（2026-11-06）。

背景：模拟器的 /proc/cpuinfo 明写 `GenuineIntel / Intel(R) Core(TM) i7-14700`，
真机是 ARM 核 + `Hardware: MT6991`。这个文件全局可读，App 三行代码就能判定。

为什么不在 KSU 的 service.sh 里做：实测 service.sh 的 `mount --bind` 落在
KSU 自己的 mount namespace 里，**传不到全局**（reboot 后仍是 Intel）；
而走 `MuMuManager sh`（全局 ns）手动挂立刻生效。所以放到 App 每次启动前的
统一前置里，用 MuMu root shell 重挂。
"""
import logging

from crawlers.app_base import AppCrawler

FAKE_CPUINFO = AppCrawler.FAKE_CPUINFO


class FakeDev:
    def __init__(self, head_out, mumu=True):
        self.head_out = head_out
        self.mumu = mumu
        self.mumu_cmds = []

    def _sh(self, *args):
        return self.head_out

    def mumu_available(self):
        return self.mumu

    def mumu_sh(self, cmd):
        self.mumu_cmds.append(cmd)
        return "ok"


def _crawler():
    class C(AppCrawler):
        name = "app_test"
        package = "com.test"

        def login_url(self):
            return ""

        def fetch(self, *a, **k):
            return []

    return C({"user_data_dir": "user_data"}, logging.getLogger("t"))


def test_mounts_when_host_cpu_visible():
    d = FakeDev("processor\t: 0\nvendor_id\t: GenuineIntel\n"
                "model name\t: Intel(R) Core(TM) i7-14700\n")
    _crawler().ensure_proc_cpuinfo(d)
    assert d.mumu_cmds, "看到 Intel 却没去重挂"
    assert "mount --bind" in d.mumu_cmds[0]
    assert FAKE_CPUINFO in d.mumu_cmds[0]


def test_noop_when_already_arm():
    d = FakeDev("processor\t: 0\nCPU implementer\t: 0x41\n")
    _crawler().ensure_proc_cpuinfo(d)
    assert d.mumu_cmds == [], "已经是 ARM 视图就不该再挂"


def test_noop_when_unrecognised():
    """读不出特征（比如命令失败、返回空）时不要乱动。"""
    d = FakeDev("")
    _crawler().ensure_proc_cpuinfo(d)
    assert d.mumu_cmds == []


def test_noop_without_mumu_channel():
    d = FakeDev("vendor_id\t: GenuineIntel\n", mumu=False)
    _crawler().ensure_proc_cpuinfo(d)
    assert d.mumu_cmds == []


def test_survives_sh_exception():
    class Boom(FakeDev):
        def _sh(self, *a):
            raise RuntimeError("adb dead")

    _crawler().ensure_proc_cpuinfo(Boom(""))
