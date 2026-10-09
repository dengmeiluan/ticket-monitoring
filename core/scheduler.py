"""基于 APScheduler 的定时调度（支持随机扰动间隔）"""
import logging
import random
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger


SCHED = None  # 当前调度器实例（start 前赋值，供热重载 reschedule）


def _schedule_next(sched, state, job_id="price_monitor"):
    """按当前间隔(+随机扰动)显式排定 job 的下次触发，返回排定时刻或 None。

    job 以 paused（next_run_time=None）创建，本函数是唯一驱动源、每轮
    接力调用——jm=0 时 uniform(-0,0)=0 退化为精确间隔；漏调即死调度
    （jm=0 档无人排下次、网格点零触发实录）。「下次抓取计划」日志行
    是观测轮界锚（对齐一个已完成轮的依据），随接力恒在。"""
    logger = logging.getLogger("ticket-monitor")
    iv = int(state.get("interval_minutes", 30))
    jm = int(state.get("jitter_minutes", 0))
    try:
        from datetime import datetime, timedelta
        if sched.get_job(job_id) is None:
            return None
        delta = max(1, iv + random.uniform(-jm, jm))
        next_time = datetime.now(sched.timezone) + timedelta(minutes=delta)
        sched.modify_job(job_id, next_run_time=next_time)
        logger.info("下次抓取计划: %s (间隔 %.1f 分钟)",
                    next_time.strftime("%H:%M:%S"), delta)
        return next_time
    except Exception as e:
        logger.warning("调整下次执行时间失败: %s", e)
        return None


def run_scheduler(job, state: dict, run_on_start: bool = True):
    """
    state = {"interval_minutes": int, "jitter_minutes": int} —— 可变引用，
    wrapped 每次执行实时读取：web 热改周期/扰动后下轮即生效（禁闭包
    捕获启动值——热改周期后扰动计算仍沿用旧间隔的不一致隐患）。
    """
    sched = BlockingScheduler(timezone="Asia/Shanghai")
    logger = logging.getLogger("ticket-monitor")

    def wrapped():
        try:
            job()
        except Exception as e:
            logger.exception("任务执行失败: %s", e)
        # 下次触发无条件接力（含 jm=0，见 _schedule_next）
        _schedule_next(sched, state)

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
