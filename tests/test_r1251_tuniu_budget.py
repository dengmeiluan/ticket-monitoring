# -*- coding: utf-8 -*-
"""r1251：tuniu 单查询要有**墙钟预算**（不让"圈重试"磨掉整轮）。

实测（2026-11-10）：`tuniu·H5/API` 14 条样本里有一条 **433 秒**，其余 23–31s。
那是 `_hoop()` 的"圈重试"一路磨到底——不改圈数、不改间隔，只是给单查询加一个
总耗时上限，超了按失败面落账退出（v2.1 §5.6「失败快速分类止损」允许项）。

契约：
1. 超预算必须**立刻返回 None**（不许再磨下一圈）；
2. 退出要留 warning，并计入 `_fail_streak`（失败面可见）；
3. 预算内正常拿到结果时行为**完全不变**（负控：不许把正常查询掐断）。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import crawlers.tuniu as T  # noqa: E402


class FakeClock:
    """可控时钟：每次 sleep 就前进固定秒数。"""

    def __init__(self, step=60.0):
        self.now = 1000.0
        self.step = step

    def time(self):
        return self.now

    def sleep(self, s):
        self.now += max(float(s or 0), self.step)


def _crawler(clock, attempts=5, budget=180.0):
    c = object.__new__(T.TuniuCrawler)
    c._fail_streak = 0
    c.max_attempts = attempts
    c.max_poll = 3
    c.rate_limit = False
    c.backoff_s = 1
    c._login_wall = False
    c.hoop_budget_s = budget
    c.logger = _Log()
    return c


class _Log:
    def __init__(self):
        self.warns = []

    def warning(self, fmt, *a):
        self.warns.append(fmt % a if a else fmt)

    def info(self, *a, **kw):
        pass


def test_budget_stops_the_grind(monkeypatch):
    clock = FakeClock(step=60.0)
    monkeypatch.setattr(T, "time", clock)
    c = _crawler(clock, attempts=10, budget=180.0)
    monkeypatch.setattr(c, "_one_attempt",
                        lambda *a, **kw: (False, None, False), raising=False)
    out = c._hoop("SHA", "NRT", "2026-11-20")
    assert out is None
    # 预算 180s、每圈推进 ≥60s → 最多 4 圈就该收手
    assert c._fail_streak == 1, c._fail_streak
    assert any("超过预算" in w for w in c.logger.warns), c.logger.warns


def test_success_within_budget_unchanged(monkeypatch):
    """负控：预算内成功时行为不变（照常返回结果、不记失败）。"""
    clock = FakeClock(step=10.0)
    monkeypatch.setattr(T, "time", clock)
    c = _crawler(clock, attempts=5, budget=180.0)
    monkeypatch.setattr(c, "_one_attempt",
                        lambda *a, **kw: (True, {"ok": 1}, False), raising=False)
    assert c._hoop("SHA", "NRT", "2026-11-20") == {"ok": 1}
    assert c._fail_streak == 0
    assert not c.logger.warns


def test_zero_budget_disables_the_cap(monkeypatch):
    """预算置 0 = 关闭（老行为），便于现场对比与回滚。"""
    clock = FakeClock(step=60.0)
    monkeypatch.setattr(T, "time", clock)
    c = _crawler(clock, attempts=2, budget=0)
    monkeypatch.setattr(c, "_one_attempt",
                        lambda *a, **kw: (False, None, False), raising=False)
    assert c._hoop("SHA", "NRT", "2026-11-20") is None
    # 关掉预算时应走到圈数上限（attempts=2）
    assert any("最大重试圈数" in w for w in c.logger.warns), c.logger.warns
