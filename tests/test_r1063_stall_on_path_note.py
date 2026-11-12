# -*- coding: utf-8 -*-
"""r1063 T160：连续超时熔断必须挂在 **path_note 层**（含 app-date 细段）。

真机取证（2026-11-09）：
```
user_data/app_ctrip/ 下没有 app_stall.json      ← 熔断从未触发
账本 app_ctrip 近 12h：app-date timeout 20 次
    detail = 「点日历后未回到表单/日期未变（目标 2026-11-16）」
```
根因：T148 把计数挂在"结果记账"函数上，而 `app-date` 这个**细段**直接调
`path_note`，绕过了它。改成在 `path_note` 尾巴统一计数后实测：

```
第 1 次后 streak=1 stall_left=0s
第 2 次后 streak=2 stall_left=0s
第 3 次后 streak=3 stall_left=1800s   ← 真写了 app_stall
成功后 streak = 0                      ← 成功即清零
```
"""
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _crawler(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    from crawlers.app_ctrip import AppCtripCrawler
    c = AppCtripCrawler({"crawler": {"user_data_dir": str(tmp_path)}},
                        logging.getLogger("t"))
    monkeypatch.setattr(c, "user_data_root", str(tmp_path), raising=False)
    return c


def test_three_timeouts_trip_the_breaker(tmp_path, monkeypatch):
    from core import service_state as ss
    c = _crawler(tmp_path, monkeypatch)
    for _ in range(c.APP_STALL_STREAK):
        c.path_note("app-date", "timeout",
                    detail="点日历后未回到表单/日期未变")
    left = ss.until(str(tmp_path), c.name, "app_stall") - time.time()
    assert left > 600, "连续超时没有写出熔断（%r）" % left
    assert "连续" in ss.detail(str(tmp_path), c.name, "app_stall")


def test_success_resets_streak(tmp_path, monkeypatch):
    c = _crawler(tmp_path, monkeypatch)
    c.path_note("app-date", "timeout", detail="x")
    c.path_note("app-date", "timeout", detail="x")
    assert getattr(c, "_timeout_streak", 0) == 2
    c.path_note("航班明细", "ok", rows=1)
    assert getattr(c, "_timeout_streak", 0) == 0


def test_below_threshold_does_not_trip(tmp_path, monkeypatch):
    from core import service_state as ss
    c = _crawler(tmp_path, monkeypatch)
    for _ in range(c.APP_STALL_STREAK - 1):
        c.path_note("app-date", "timeout", detail="x")
    assert ss.until(str(tmp_path), c.name, "app_stall") == 0, \
        "没到阈值不该熔断（把偶发当熔断会让渠道白停）"
