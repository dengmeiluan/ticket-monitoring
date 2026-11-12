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
    # 自适应退避（2026-11-06）：上一轮受阻越多，这一轮推得越远。
    # 由轮末按 `pacing.round_backoff_minutes()` 写入；全绿时会被清回 0，
    # 所以恢复正常后立刻回到正常节奏，不会一路慢下去。
    try:
        _bo = int(state.get("backoff_minutes", 0) or 0)
    except (TypeError, ValueError):
        _bo = 0
    _bo = max(0, _bo)
    try:
        from datetime import datetime, timedelta
        if sched.get_job(job_id) is None:
            return None
        delta = max(1, iv + _bo + random.uniform(-jm, jm))
        # r391 / r1761 / r1767：静默窗跳过轮把「距窗口结束的秒数」写进
        # state["wake_at"]，它是**硬计划**——下一轮就排在窗口结束那一刻。
        # 旧实现 `min(delta, _wake/60)` 让它被自然间隔盖住：25 分间隔 +
        # 75 分剩余 → 又排回窗里（05:45→06:13→…），「窗口结束即补采」
        # 最坏要晚一整个间隔。
        _wake = state.pop("wake_at", None)
        if isinstance(_wake, (int, float)) and _wake > 0:
            # wake_at 是**硬计划**：窗口结束就能采（右开窗，07:00 整已不在
            # 窗内），所以它直接当 delta——既不被自然间隔盖住（旧 min 的
            # bug：25 分间隔 + 75 分剩余 → 又排回窗里），也不额外加余量
            # （r391：interval 30 + wake 180s 必须 ≤3.5 分钟）。
            delta = max(1.0, _wake / 60.0)
        next_time = datetime.now(sched.timezone) + timedelta(minutes=delta)
        sched.modify_job(job_id, next_run_time=next_time)
        if _bo:
            logger.info("下次抓取计划: %s (间隔 %.1f 分钟，含受阻退避 %d 分钟)",
                        next_time.strftime("%H:%M:%S"), delta, _bo)
        else:
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
        # misfire 宽限窗：接力链的唯一驱动是 wrapped 末尾的显式排定，
        # due 轮若因外邻满载（同机打包/构建）错过默认 1s 宽限被丢弃，
        # 无人再排下次=调度链静默死亡（进程活、端口听、零扫描）。
        # 宽限窗 ≥ 最小扫描间隔，让迟到轮照跑、链自愈
        misfire_grace_time=300,
        next_run_time=None,
    )
    if run_on_start:
        wrapped()
    else:
        _schedule_next(sched, state)
    global SCHED
    SCHED = sched
    sched.start()
    return sched
