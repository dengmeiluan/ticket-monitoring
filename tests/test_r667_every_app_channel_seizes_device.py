# -*- coding: utf-8 -*-
r"""r667：每个 App 渠道都必须持有设备独占锁，否则两台采集会互相打断。

为什么单独一条：`channel_slot(c.name)` 是**按渠道**加锁的，两个 App 渠道
各拿各的锁，互相不阻塞——而它们共用同一台 MuMu 模拟器。真正的互斥在
`core/android/runtime.py` 的模块级 `_DEVICE_LOCK`（`rt.device_lock()`）。

r667 之前只有智行有这条断言（`test_uses_device_lock`）；并行会话接入
去哪儿 App 后，它的 `fetch` 是否也包了 device_lock 没有任何门禁守着——
漏掉就是「两个渠道同时点同一块屏幕」，而这种缺陷在单渠道测试里看不出来。

判据按 `crawlers.REGISTRY` 里的 App 渠道**参数化**，新增渠道自动纳入。
负控：去掉任意一个 crawler 的 `with rt.device_lock():` → 本测试红。
"""
import io
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _app_channels():
    from core.channels import APP_CHANNELS
    return tuple(APP_CHANNELS)


@pytest.mark.parametrize("plat", _app_channels())
def test_every_app_channel_holds_the_device_lock(plat):
    src = io.open(os.path.join(ROOT, "crawlers", plat + ".py"),
                  encoding="utf-8", newline="").read()
    assert "device_lock()" in src, (
        "%s 的采集没有拿设备独占锁：两个 App 渠道共用一台模拟器时会互相"
        "打断（channel_slot 是按渠道分锁的，挡不住）" % plat)
    # 必须真的把取数段包进锁里，而不是拿到锁对象就丢
    assert re.search(r"with\s+rt\.device_lock\(\)\s*:", src), (
        "%s 只是提到了 device_lock，但没有把它当上下文管理器包住采集段"
        % plat)


def test_device_lock_is_module_level_singleton():
    """锁必须是模块级单例：每个 runtime 实例一把锁等于没有锁。"""
    from core.android import runtime as rt_mod
    assert hasattr(rt_mod, "_DEVICE_LOCK")
    import threading
    assert isinstance(rt_mod._DEVICE_LOCK, type(threading.Lock()))
    # 两个 runtime 实例拿到的是同一把
    a = rt_mod.AndroidRuntime.__new__(rt_mod.AndroidRuntime)
    b = rt_mod.AndroidRuntime.__new__(rt_mod.AndroidRuntime)
    seen = []

    def take(inst, tag):
        with inst.device_lock(timeout=1):
            seen.append(tag)

    import threading as _t
    t1 = _t.Thread(target=take, args=(a, "a"))
    t1.start()
    t1.join(2)
    t2 = _t.Thread(target=take, args=(b, "b"))
    t2.start()
    t2.join(2)
    assert seen == ["a", "b"], "两个 runtime 实例没有共用同一把设备锁：%s" % seen
