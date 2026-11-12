# -*- coding: utf-8 -*-
"""r1761：静默窗跳过轮必须把下一轮**推到窗口结束+1 分钟**（原来用 min 又落回窗里）。

现场：05:45:43 跳过（窗口还剩 75 分钟），紧接着排的下次是 06:13:23
——又落回窗内，于是「窗口结束即补采」最坏要晚一整个间隔。
根因：`delta = min(delta, _wake/60)` 用了 min。
"""
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.scheduler as sch  # noqa: E402


class _Job(dict):
    pass


class _Sched:
    """最小假调度器：只记录 modify_job 传入的 next_run_time。"""

    def __init__(self):
        self.timezone = None
        self.next_at = None

    def get_job(self, job_id):
        return object()

    def modify_job(self, job_id, next_run_time=None):
        self.next_at = next_run_time


def _run(state):
    s = _Sched()
    out = sch._schedule_next(s, dict(state))
    return out


def test_quiet_wake_pushes_next_run_past_window_end():
    # 自然间隔 25 分，窗口还剩 75 分 → 应推到 76 分（窗口结束+1）
    out = _run({"interval_minutes": 25, "jitter_minutes": 0,
                "wake_at": 75 * 60})
    assert out is not None
    from datetime import datetime
    delta_min = (out - datetime.now()).total_seconds() / 60.0
    assert 74 <= delta_min <= 76, delta_min
    assert delta_min > 25, "仍然按自然间隔排（会继续在窗内醒）：%.1f" % delta_min


def test_no_wake_keeps_natural_interval():
    out = _run({"interval_minutes": 25, "jitter_minutes": 0})
    assert out is not None


def test_short_remaining_window_wake_wins():
    # 窗口只剩 5 分、自然间隔 30 分 → 按 r391 契约：wake_at 是硬计划，取 5 分。
    out = _run({'interval_minutes': 30, 'jitter_minutes': 0,
                'wake_at': 5 * 60})
    from datetime import datetime
    delta_min = (out - datetime.now()).total_seconds() / 60.0
    assert 4.0 <= delta_min <= 5.5, 'wake_at 没有赢：%.1f' % delta_min
