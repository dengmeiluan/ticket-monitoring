# -*- coding: utf-8 -*-
"""自适应轮次退避：本轮受阻 → 下一轮推远；全绿 → 立刻回正常节奏。

2026-11-06 背景：`interval_minutes` 是固定节奏（默认 30 分钟），不管上一轮
是被风控拦了 5 家还是全绿，下一轮都照常半小时后再来。环境已经不好时，
这种"照常节奏"正是风险继续累积的来源。
"""
import datetime as dt

import core.scheduler as sched_mod
from core.pacing import round_backoff_minutes as rb


# ---------- 纯函数 ----------

def test_clean_round_has_no_backoff():
    assert rb(30, 0, 0) == 0


def test_one_or_two_trips_back_off_one_interval():
    assert rb(30, 1, 0) == 30
    assert rb(30, 2, 0) == 30
    assert rb(30, 0, 1) == 30          # 冷却中的渠道也算受阻


def test_three_or_more_trips_back_off_two_intervals():
    assert rb(30, 3, 0) == 60
    assert rb(30, 1, 2) == 60          # trips + blocked 合计


def test_capped():
    assert rb(600, 5, 0) == 240        # 默认封顶 240
    assert rb(600, 5, 0, cap_min=60) == 60


def test_bad_input_is_zero():
    assert rb(None, "x", None) == 0
    assert rb(0, 5, 5) == 0


# ---------- 调度器集成 ----------

class _Job:
    pass


class _FakeSched:
    """够 _schedule_next 用的最小替身。"""

    def __init__(self):
        self.timezone = dt.timezone(dt.timedelta(hours=8))
        self.next_run_time = None

    def get_job(self, job_id):
        return _Job()

    def modify_job(self, job_id, next_run_time=None):
        self.next_run_time = next_run_time


def _delta_for(state):
    s = _FakeSched()
    before = dt.datetime.now(s.timezone)
    sched_mod._schedule_next(s, state)
    after = dt.datetime.now(s.timezone)
    # 用中点消掉执行耗时带来的误差
    return (s.next_run_time
            - (before + (after - before) / 2)).total_seconds() / 60.0


def test_scheduler_applies_backoff():
    plain = _delta_for({"interval_minutes": 30, "jitter_minutes": 0})
    backed = _delta_for({"interval_minutes": 30, "jitter_minutes": 0,
                         "backoff_minutes": 30})
    assert abs(plain - 30) < 1.5, plain
    assert abs(backed - 60) < 1.5, backed


def test_scheduler_ignores_garbage_backoff():
    d = _delta_for({"interval_minutes": 30, "jitter_minutes": 0,
                    "backoff_minutes": "oops"})
    assert abs(d - 30) < 1.5, d


def test_wake_at_still_wins():
    """静默窗结束的 wake_at 仍取较短值：退避不能把补采推得更晚。

    `wake_at` 的语义是**剩余秒数**（main.py 里由
    `Pacing.seconds_until_quiet_end()` 写入），不是绝对时间戳——
    传时间戳会得到 `epoch/60` 这个荒谬的"分钟数"。
    """
    state = {"interval_minutes": 30, "jitter_minutes": 0,
             "backoff_minutes": 120, "wake_at": 5 * 60}
    d = _delta_for(state)
    assert d <= 6, d
