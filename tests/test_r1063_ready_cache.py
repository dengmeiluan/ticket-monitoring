# -*- coding: utf-8 -*-
"""r1063 T88：`ensure_ready` 成功缓存 + 前置逐步骤打点。

真机（智行，同一进程连跑两次）：

| 轮次 | 整轮 | 运行时 |
|---|---|---|
| 第 1 次（冷） | 34.5s | 2.3s |
| **第 2 次（热）** | **11.9s** | **0.0s** |

`ensure_ready()` 每次都要跑 MuMuManager info + adb 探测 + 硬化自检（约 2–4s），
而同一进程几十秒内这些条件几乎不变——缓存成功结果直接省掉它。

**只缓存成功**：设备真掉了必须能立刻发现，所以失败一律照常重探。
配置键 `android.ready_cache_s`（默认 60，0 = 不缓存）。

顺带说明一个测量陷阱：`前置·登录态` 那 7 秒是"停 App → 重启 → 等首屏"，
**一个进程只做一次**；我早期用"每次新进程跑一条"的方式测，把它算进了单次成本，
于是看到的前置时间偏大。稳态服务里它是一次性的。
"""
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.android.runtime import AndroidRuntime  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.path.join(ROOT, "core", "android", "runtime.py"),
              encoding="utf-8").read()
SRC_AB = io.open(os.path.join(ROOT, "crawlers", "app_base.py"),
                 encoding="utf-8").read()


def test_cache_knob_is_read_from_raw_config():
    """`ready_cache_s` 从原始 android: 段读（不进 AndroidConfig，避免破坏钉住的字段集）。"""
    from core.android.runtime import AndroidRuntime
    rt = AndroidRuntime({"enabled": True, "ready_cache_s": 0})
    rt._ready_ok_at = time.time()
    assert rt.ensure_ready()[1] != "ready-cached", "0 应关闭缓存"
    rt2 = AndroidRuntime({"enabled": True})
    rt2._ready_ok_at = time.time()
    assert rt2.ensure_ready()[1] == "ready-cached", "缺省 60 秒应命中缓存"


def test_success_is_cached():
    rt = AndroidRuntime({"enabled": True, "ready_cache_s": 60})
    rt._ready_ok_at = time.time()
    ok, why = rt.ensure_ready()
    assert ok is True and why == "ready-cached"
    assert rt._state == "ready(cached)"


def test_cache_expires():
    rt = AndroidRuntime({"enabled": True, "ready_cache_s": 60})
    rt._ready_ok_at = time.time() - 61
    ok, why = rt.ensure_ready()
    assert why != "ready-cached", "过期必须重新探测"


def test_zero_ttl_disables_cache():
    rt = AndroidRuntime({"enabled": True, "ready_cache_s": 0})
    rt._ready_ok_at = time.time()
    ok, why = rt.ensure_ready()
    assert why != "ready-cached"


def test_failures_are_never_cached():
    """失败的调用不许写缓存戳——否则设备掉了会被"缓存"掩盖。"""
    rt = AndroidRuntime({"enabled": False, "ready_cache_s": 60})
    ok, _ = rt.ensure_ready()
    assert ok is False
    assert getattr(rt, "_ready_ok_at", 0.0) == 0.0


def test_source_marks_every_prepare_step():
    """前置每一步都要有名字（否则又回到"只有总数"）。"""
    for name in ("前置·竖屏", "前置·登录态", "前置·权限框", "前置·切前台",
                 "前置·ANR", "前置·props", "前置·定位", "前置·cpuinfo"):
        assert 'self.timed("%s")' % name in SRC_AB, name
