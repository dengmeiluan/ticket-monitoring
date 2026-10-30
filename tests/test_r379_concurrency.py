# -*- coding: utf-8 -*-
"""r379 并发契约：渠道闸门不死锁、不超全局配额；Pacing 状态读写不炸。

这些不是性能测试，是"竞态不劣化"的最小证据：
  - 同渠道等待者不能占满全局浏览器配额（头阻塞回归）；
  - 全局最多 2 个渠道浏览器（BoundedSemaphore 不被绕过）；
  - Pacing 的 plan/observe/reset/note_fetch/snapshot 可被多线程并发调用。
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pacing import Pacing  # noqa: E402
from crawlers.base import channel_slot  # noqa: E402


def test_channel_slot_caps_global_browsers():
    cur = [0]
    peak = [0]
    lock = threading.Lock()
    plats = ["ctrip", "qunar", "fliggy", "tongcheng", "tuniu"] * 2

    def worker(p):
        with channel_slot(p):
            with lock:
                cur[0] += 1
                peak[0] = max(peak[0], cur[0])
            time.sleep(0.03)
            with lock:
                cur[0] -= 1

    ts = [threading.Thread(target=worker, args=(p,)) for p in plats]
    for t in ts:
        t.start()
    for t in ts:
        t.join(5)
    assert not any(t.is_alive() for t in ts), "channel_slot 不得死锁"
    assert peak[0] <= 2, "全局浏览器配额被突破: %d" % peak[0]
    assert peak[0] >= 2, "并发被过度串行化（配额未用满）"


def test_same_channel_waiters_do_not_block_other_channels():
    hold = threading.Event()
    other_done = threading.Event()

    def same():
        with channel_slot("qunar"):
            hold.wait(3)

    def other():
        with channel_slot("ctrip"):
            other_done.set()

    same_ts = [threading.Thread(target=same, daemon=True) for _ in range(2)]
    for t in same_ts:
        t.start()
    time.sleep(0.1)
    ot = threading.Thread(target=other, daemon=True)
    ot.start()
    assert other_done.wait(1.5), "同渠道等待者堵住了其他渠道"
    hold.set()
    for t in same_ts:
        t.join(2)
    ot.join(2)


def test_pacing_state_is_thread_safe_under_mixed_ops():
    p = Pacing({"schedule": {"fast_ttl_min": 15, "slow_ttl_min": 120,
                             "scan_quiet_start": "", "scan_quiet_end": ""}})
    errors = []
    stop = time.time() + 1.0

    def worker(i):
        try:
            while time.time() < stop:
                key = ("SHA", "PEK", "2027-06-%02d" % (i % 28 + 1))
                tier, _why = p.plan_query("qunar", key, 900)
                p.note_plan("qunar", key, tier, "concurrent")
                p.note_fetch("qunar", key, 800 + i, True)
                p.observe("qunar", ["ok"], "")
                p.observe("qunar", ["blocked"], "")
                p.reset("qunar")
                p.set_health("qunar", 0.5, 20)
                p.seed_fetch("qunar", key, 700 + i, time.time())
                snap = p.snapshot()
                assert "channels" in snap and "last_round" in snap
        except Exception as e:      # noqa: BLE001 - 记录线程内任何异常
            errors.append(repr(e))

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(5)
    assert not any(t.is_alive() for t in ts), "Pacing 并发调用卡死"
    assert not errors, errors[:3]
