"""基于 APScheduler 的定时调度（支持随机扰动间隔）"""
import logging
import random
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger


SCHED = None  # 当前调度器实例（start 前赋值，供热重载 reschedule）


def run_scheduler(job, state: dict, run_on_start: bool = True):
    """
    state = {"interval_minutes": int, "jitter_minutes": int} —— 可变引用，
    wrapped 每次执行实时读取：web 热改周期/扰动后下轮即生效（曾经闭包
    捕获启动值，热改周期后扰动计算仍沿用旧间隔的不一致隐患）。
    """
    sched = BlockingScheduler(timezone="Asia/Shanghai")
    logger = logging.getLogger("ticket-monitor")

    def wrapped():
        try:
            job()
        except Exception as e:
            logger.exception("任务执行失败: %s", e)
        # 下一次运行时间随机扰动
        iv = int(state.get("interval_minutes", 30))
        jm = int(state.get("jitter_minutes", 0))
        if jm > 0:
            try:
                base = sched.get_job("price_monitor")
                if base is not None:
                    from datetime import datetime, timedelta
                    next_delta = iv + random.uniform(-jm, jm)
                    next_delta = max(1, next_delta)  # 至少1分钟
                    next_time = datetime.now(sched.timezone) + timedelta(
                        minutes=next_delta)
                    sched.modify_job("price_monitor", next_run_time=next_time)
                    logger.info("下次抓取计划: %s (间隔 %.1f 分钟)",
                                next_time.strftime("%H:%M:%S"), next_delta)
            except Exception as e:
                logger.warning("调整下次执行时间失败: %s", e)

    sched.add_job(
        wrapped,
        trigger=IntervalTrigger(minutes=int(state.get("interval_minutes", 30))),
        id="price_monitor",
        max_instances=1,
        coalesce=True,
        next_run_time=None,
    )
    if run_on_start:
        wrapped()
    global SCHED
    SCHED = sched
    sched.start()
    return sched
