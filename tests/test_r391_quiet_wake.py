# -*- coding: utf-8 -*-
"""r391：静默窗结束即补采（避免窗口结束后仍陈旧半小时）。

夜间静默窗内 sweep 直接 return（只有 force 绕过），跳过轮不落轮次标记；
若照常按 24–37 分钟间隔接力，07:00 窗口结束后最坏还要再等半小时才有
第一轮数据（此时数据已陈旧 6 小时）。现在窗口内跳过时把「距窗口结束
秒数」写进 rt["_wake_at"]，调度取 min(常规间隔, 窗口结束+1 分钟)。
"""
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pacing import Pacing  # noqa: E402

_LOG = logging.getLogger("t_r391")


def _at(hhmm):
    return time.mktime(time.strptime("2026-10-27 %s:00" % hhmm,
                                     "%Y-%m-%d %H:%M:%S"))


def _p():
    return Pacing({"schedule": {"scan_quiet_start": "01:00",
                                "scan_quiet_end": "07:00"}})


def test_seconds_until_quiet_end_inside_window():
    p = _p()
    assert p.quiet_now(_at("01:30")) is True
    left = p.seconds_until_quiet_end(_at("01:30"))
    assert left == 5.5 * 3600, left


def test_seconds_until_quiet_end_outside_window():
    p = _p()
    assert p.quiet_now(_at("07:30")) is False
    assert p.seconds_until_quiet_end(_at("07:30")) is None


def test_seconds_until_quiet_end_just_before_end():
    p = _p()
    left = p.seconds_until_quiet_end(_at("06:59"))
    assert left == 60.0, left


def test_seconds_until_quiet_end_cross_midnight():
    p = Pacing({"schedule": {"scan_quiet_start": "23:00",
                             "scan_quiet_end": "07:00"}})
    assert p.quiet_now(_at("02:00")) is True
    assert p.seconds_until_quiet_end(_at("02:00")) == 5 * 3600


def test_seconds_until_quiet_end_disabled_window():
    p = Pacing({})
    assert p.seconds_until_quiet_end(_at("02:00")) is None


def test_scheduler_honours_wake_at(monkeypatch):
    """调度把下一轮提前到窗口结束（比常规 30 分钟间隔短时取短）。"""
    import core.scheduler as sch

    class _Job:
        pass

    class _Sched:
        timezone = None

        def __init__(self):
            self.modified = None

        def get_job(self, _id):
            return _Job()

        def modify_job(self, _id, next_run_time=None):
            self.modified = next_run_time

    from datetime import datetime as _dt
    s = _Sched()
    s.timezone = _dt.now().astimezone().tzinfo
    state = {"interval_minutes": 30, "jitter_minutes": 0, "wake_at": 180}
    before = _dt.now(s.timezone)
    nxt = sch._schedule_next(s, state)
    assert nxt is not None and s.modified is not None
    delta_min = (nxt - before).total_seconds() / 60.0
    assert delta_min <= 3.5, delta_min          # 180s ≈ 3 分钟，不是 30 分钟
    assert "wake_at" not in state, "一次性键必须消费掉"


# ---- r392：原始明细保留期单源（8 天），不再白占 7–14 天的 never-read 数据 ----

def test_raw_retain_days_matches_all_readers():
    """所有读取方都在 168h（7 天）内，保留期不应超过它太多。"""
    import inspect
    import report
    from core import alerter as _al
    from core.storage import PriceStorage
    assert PriceStorage.RAW_RETAIN_DAYS == 8
    # 走势读取窗=168h（调用方传参；_rounds 自身默认 48h）
    assert "hours=168" in inspect.getsource(_al),         "走势读取窗必须是 168h；扩大窗口时须同步 RAW_RETAIN_DAYS"
    assert "hours=168" in inspect.getsource(report)
    assert PriceStorage.RAW_RETAIN_DAYS >= 7,         "保留期必须覆盖 168h 读取窗（含边界余量）"


def test_purge_default_uses_retention_constant(tmp_path):
    import sqlite3
    from datetime import datetime, timedelta
    from core.storage import PriceStorage
    st = PriceStorage(str(tmp_path / "p.db"))
    db = st.db_path

    def ins(days_ago, price=100.0):
        ts = (datetime.now() - timedelta(days=days_ago)
              ).strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(db) as c:
            c.execute("INSERT INTO flight_prices (platform, from_city, "
                      "to_city, depart_date, price, extra, fetched_at) "
                      "VALUES ('qunar','A','B','2026-11-16',?, '', ?)",
                      (price, ts))

    ins(1)                       # 保留
    ins(PriceStorage.RAW_RETAIN_DAYS + 1)   # 该删
    n = st.purge()               # 缺省 = RAW_RETAIN_DAYS
    assert n == 1, n
    with sqlite3.connect(db) as c:
        left = [r[0] for r in c.execute(
            "SELECT price FROM flight_prices")]
    assert left == [100.0]


# ---- r392b：删除不缩文件，需受控 VACUUM ----

def test_maybe_vacuum_skips_small_delete(tmp_path):
    from core.storage import PriceStorage
    st = PriceStorage(str(tmp_path / "p.db"))
    assert st.maybe_vacuum(10) is False, "少量删除不值得重写整库"


def test_maybe_vacuum_respects_interval(tmp_path):
    import os as _os
    from core.storage import PriceStorage
    st = PriceStorage(str(tmp_path / "p.db"))
    stamp = _os.path.join(_os.path.dirname(st.db_path) or ".", ".last_vacuum")
    open(stamp, "w", encoding="utf-8").write("x")
    assert st.maybe_vacuum(5000) is False, "间隔未到不得重复重写"
    _os.remove(stamp)
    assert st.maybe_vacuum(5000) is True, "条件满足时应执行"


def test_vacuum_actually_shrinks_file(tmp_path):
    """端到端：塞大量 extra 后删除再 VACUUM，文件必须变小。"""
    import os as _os
    import sqlite3
    from core.storage import PriceStorage
    st = PriceStorage(str(tmp_path / "p.db"))
    big = "x" * 20000
    with sqlite3.connect(st.db_path) as c:
        for i in range(60):
            c.execute(
                "INSERT INTO flight_prices (platform, from_city, to_city, "
                "depart_date, price, extra, fetched_at) VALUES "
                "('qunar','A','B','2026-11-16',100,?, "
                "datetime('now','localtime','-30 days'))", (big,))
    size0 = _os.path.getsize(st.db_path)
    st.purge()                      # 全删（都超 8 天）
    assert st.maybe_vacuum(60, min_deleted=50) is True
    assert _os.path.getsize(st.db_path) < size0
