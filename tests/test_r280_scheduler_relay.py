# -*- coding: utf-8 -*-
"""r280 调度接力死锁复现。

旧实现：job 以 next_run_time=None（paused）创建，「下次触发」全靠
wrapped() 末尾的 modify_job 显式接力，而该接力包在 `if jm > 0:` 里——
jitter=0（用户要求精确 5 分钟一轮的配置形态）时无人排定下次触发，
调度器永久静默（实录：新进程 22:36:55 启动后 22:41:54 网格点零触发）。

修正：接力无条件执行，jm=0 时 uniform(-0,0)=0 退化为精确间隔；
「下次抓取计划」日志随接力恢复（观测轮界锚依赖该行）。
"""
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from core.scheduler import _schedule_next

_TZ = "Asia/Shanghai"


def _mk_sched():
    s = BlockingScheduler(timezone=_TZ)
    s.add_job(lambda: None, trigger=IntervalTrigger(minutes=5),
              id="price_monitor", max_instances=1, coalesce=True,
              next_run_time=None)  # paused——旧形态无人接力即死
    return s


def test_jitter_zero_still_schedules_next():
    """核心复现：jm=0 时也必须排定下次触发（旧实现 job 恒 paused）。"""
    s = _mk_sched()
    nt = _schedule_next(s, {"interval_minutes": 5, "jitter_minutes": 0})
    assert nt is not None, "jm=0 未排定下次触发（死调度）"
    job = s.get_job("price_monitor")
    assert job.next_run_time is not None
    gap = (job.next_run_time - datetime.now(job.next_run_time.tzinfo)
           ).total_seconds()
    assert 240 <= gap <= 301, f"间隔应≈5分钟, 实测 {gap:.0f}s"


def test_jitter_band_honored():
    """jm>0 时接力时刻落在 [iv-jm, iv+jm] 带内。"""
    s = _mk_sched()
    _schedule_next(s, {"interval_minutes": 15, "jitter_minutes": 5})
    job = s.get_job("price_monitor")
    gap = (job.next_run_time - datetime.now(job.next_run_time.tzinfo)
           ).total_seconds()
    assert 595 <= gap <= 1201, f"间隔应∈[10,20]分钟, 实测 {gap:.0f}s"


def test_missing_job_returns_none():
    """job 不存在（未注册）时不抛错、返回 None（防呆与旧 try/except 同义）。"""
    from apscheduler.schedulers.blocking import BlockingScheduler
    s = BlockingScheduler(timezone=_TZ)
    assert _schedule_next(s, {"interval_minutes": 5,
                              "jitter_minutes": 0}) is None


def test_relay_call_is_unconditional():
    """Soldier Minor-1：wrapped 必须无条件接力——调用点改回参数分支
    （if jm>0）则 _schedule_next 单测仍绿而死调度复发，源码钉锁调用点。"""
    src = open("core/scheduler.py", encoding="utf-8").read()
    assert "_schedule_next(sched, state)" in src, "wrapped 未调用接力"
    assert "if jm > 0" not in src, "接力被参数分支包回（死调度形态复活）"
