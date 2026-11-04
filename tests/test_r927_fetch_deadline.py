# -*- coding: utf-8 -*-
"""r927：协作式截止时间——把"挂 900s"压成"到点自己退出并放锁"。

事故（2026-11-04 真实日志）：

    23:30  [app_qunar] 开始抓取
    23:45  [并发] app_qunar 路由级超时(900s)      ← 只是"不再等 future"
    00:00  apscheduler … skipped: maximum running instances (1)
    …      连续 10 小时全部 skipped

为什么路由级超时治不了：`ThreadPoolExecutor` 的 worker **不可取消**，它仍在
跑并继续占着设备锁。于是每轮每个 App 渠道白等 600s 才放弃，单轮耗时远超
30 分钟间隔 → apscheduler 永久积压。

正解是**协作式截止**：拿到锁时给设备一个预算，超时后 worker 在**下一个 adb
调用**处主动放弃（卡死都发生在 adb 上），于是立刻退回、`finally` 释放锁。

预算默认 **540s < 路由级 900s**：必须先让 worker 自己退出，路由那边才不会
因为"等不到人"把整轮拖住。``android.fetch_budget_s: 0`` 可关掉（回到旧行为）。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r927_fetch_deadline.py -q
"""
import logging
import os
import sys
import threading
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.android import runtime as rt  # noqa: E402
from core.android.device import AdbDevice  # noqa: E402

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
