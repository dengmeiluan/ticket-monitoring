# -*- coding: utf-8 -*-
"""r925：设备锁持有者观测——卡死 10 小时也查不出是谁，这不行。

2026-11-04 事故复盘（真实日志，就是这么发生的）：

    23:30:16  [app_qunar] 开始抓取 SHA->BKK
    23:45:07  [并发] qunar 路由级超时(900s)，按断供记健康时间线
    23:45:07  [并发] app_qunar 路由级超时(900s)
    00:00:07  apscheduler … skipped: maximum number of running instances (1)
    …        此后每 30 分钟都 skipped，连续 **10 小时**没采到数

机制：路由级超时只是「不再等 future」，**worker 线程仍在跑**并继续占着
`_DEVICE_LOCK`（模块级 `threading.Lock`）。之后每轮每个 App 渠道都要白等
600s 才发现拿不到锁，单轮耗时远超 30 分钟间隔 → apscheduler 永久积压。

而当时的日志里只有「路由级超时」和「skipped」，**看不出是谁占着锁**——
这正是一次卡死查不动的根本原因。

本文件钉住「谁持锁、持了多久、等不到时是谁占着」这三件事。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r925_device_lock_owner.py -q
"""
import logging
import os
import sys
import threading

import pytest
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.android import runtime as rt  # noqa: E402

_LOG = logging.getLogger("test_r925")


@pytest.fixture(autouse=True)
def _isolated_lock(monkeypatch):
    """换成本文件专用锁：同进程若有别的采集线程持着模块锁，默认
    ``timeout=600`` 会把用例真的拖满 10 分钟（不是产品坏，是抢真锁）。"""
    monkeypatch.setattr(rt, "_DEVICE_LOCK", threading.Lock())
    monkeypatch.setattr(rt, "_LOCK_STATE", {"owner": "", "since": 0.0})
    yield


def _runtime():
    return rt.AndroidRuntime({"enabled": True}, _LOG)


# ---------------------------------------------------------------------------
# 1. 持有者记录
# ---------------------------------------------------------------------------
def test_owner_is_recorded_while_held():
    r = _runtime()
    assert r.lock_state()["owner"] == ""
    with r.device_lock(owner="app_qunar"):
        st = r.lock_state()
        assert st["owner"] == "app_qunar"
        assert st["since"] > 0
    assert r.lock_state()["owner"] == ""


def test_owner_cleared_after_release():
    r = _runtime()
    with r.device_lock(owner="app_ctrip"):
        pass
    st = r.lock_state()
    # lock_state 还会带 budget_left/deadline_hits 等观测字段，这里只钉
    # 「持有者与起始时刻已清空」这一条契约，别把附加上下文当成契约本身。
    assert st["owner"] == "" and st["since"] == 0.0, st


def test_owner_cleared_even_on_exception():
    r = _runtime()
    try:
        with r.device_lock(owner="app_fliggy"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert r.lock_state()["owner"] == ""           # 异常也不能留下持有者


# ---------------------------------------------------------------------------
# 2. 等不到锁时，报出**当前持有者**
# ---------------------------------------------------------------------------
def test_timeout_reports_holder(caplog):
    r = _runtime()
    started = threading.Event()
    release = threading.Event()

    def _hold():
        with r.device_lock(owner="app_qunar"):
            started.set()
            release.wait(5)

    th = threading.Thread(target=_hold, daemon=True)
    th.start()
    started.wait(2)
    try:
        with caplog.at_level(logging.WARNING):
            try:
                with r.device_lock(timeout=0.3, owner="app_ctrip"):
                    pass
                raise AssertionError("应当超时")
            except TimeoutError:
                pass
        text = "\n".join(rec.getMessage() for rec in caplog.records)
        assert "app_qunar" in text, text        # 关键：报出是谁占着
        assert "超时" in text
    finally:
        release.set()
        th.join(3)


def test_timeout_still_raises_timeout_error():
    """既有契约不变：拿不到锁抛 TimeoutError（调用方转 busy）。"""
    r = _runtime()
    started = threading.Event()
    release = threading.Event()

    def _hold():
        with r.device_lock(owner="app_tongcheng"):
            started.set()
            release.wait(5)

    th = threading.Thread(target=_hold, daemon=True)
    th.start()
    started.wait(2)
    try:
        try:
            with r.device_lock(timeout=0.2):
                pass
            raise AssertionError("应当抛 TimeoutError")
        except TimeoutError as e:
            assert "busy" in str(e)
    finally:
        release.set()
        th.join(3)


# ---------------------------------------------------------------------------
# 3. 长持有要留痕（正常 App 采集通常 60s 内）
# ---------------------------------------------------------------------------
def test_long_hold_is_logged(caplog, monkeypatch):
    r = _runtime()
    # 把"偏长"阈值降到 0.2s，避免测试真的等 120s
    real = rt.time
    with caplog.at_level(logging.WARNING):
        with r.device_lock(owner="app_zhixing"):
            # 直接把 since 往前拨，模拟"已经持了很久"
            rt._LOCK_STATE["since"] = time.time() - 300
    text = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "app_zhixing" in text and "偏长" in text, text


# ---------------------------------------------------------------------------
# 4. 渠道侧确实传了 owner（源码钉：9 处调用都要带）
# ---------------------------------------------------------------------------
def test_all_channels_pass_owner():
    import glob
    import io
    files = sorted(glob.glob(os.path.join(ROOT, "crawlers", "app_*.py")))
    bad = []
    for f in files:
        src = io.open(f, encoding="utf-8").read()
        if "rt.device_lock(" not in src:
            continue
        if "rt.device_lock()" in src:
            bad.append(os.path.basename(f))
        if "rt.device_lock(owner=self.name)" not in src:
            bad.append(os.path.basename(f) + "(缺 owner)")
    assert not bad, bad
