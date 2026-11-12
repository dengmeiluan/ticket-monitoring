# -*- coding: utf-8 -*-
"""r1063 T77：分段计时——把"慢在哪一步"变成账本上的数字。

真机实测（2026-11-08，智行 10.26.2，SHA→PEK）：

| 段 | 样本 | 合计 | 平均 |
|---|---|---|---|
| **日历** | 2 | 31.9s | **15.9s** |
| 前置 | 1 | 8.0s | 8.0s |

单次整轮 45.3s，其中可归因 40s —— **日历是最大头**。
在此之前账本只有查询级三个数（墙钟/工作/空等），只能回答"这一轮多久"，
回答不了"慢在哪一步"，优化全靠猜。

设计要点：
* 计时**只做观测**，任何异常都不许影响采集（计时把采集搞挂比没有计时更糟）；
* 自动打点复用现成路径账：相邻两条账的间隔＝上一步的耗时，渠道零改动；
* 手动 `with self.timed("阶段")` 给"没有路径账的大段"补点。
"""
import io
import os
import time

from core.phase_timer import PhaseTimer
from core.yield_stats import YieldLedger

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_summary_aggregates_same_name():
    t = PhaseTimer()
    t.mark("导航", 10)
    t.mark("日历", 4)
    t.mark("导航", 6)
    rows = t.summary()
    assert rows[0] == {"name": "导航", "s": 16.0, "n": 2}, rows
    assert rows[1]["name"] == "日历"


def test_context_manager_times_and_never_raises():
    t = PhaseTimer()
    with t("等待"):
        time.sleep(0.02)
    assert t.summary()[0]["name"] == "等待"
    assert t.summary()[0]["s"] >= 0

    class Boom:
        pass

    # 未知阶段名 / 没打开就 stop：一律不抛
    assert t.stop("从没开始") == 0.0
    t.mark("坏值", "abc")


def test_text_readout_is_one_line():
    t = PhaseTimer()
    t.mark("日历", 16)
    t.mark("前置", 8)
    txt = t.text()
    assert "日历" in txt and "前置" in txt and "共" in txt


def test_ledger_stores_phase_totals(tmp_path=None):
    import tempfile

    p = os.path.join(tempfile.mkdtemp(), "y.json")
    led = YieldLedger(p)
    led.note_phases("app_zhixing", [{"name": "日历", "s": 12.0, "n": 1},
                                    {"name": "前置", "s": 8.0, "n": 1}])
    led.note_phases("app_zhixing", [{"name": "日历", "s": 4.0, "n": 1}])
    import json
    rec = json.load(open(p, encoding="utf-8"))["app_zhixing"]["phases"]
    assert rec["日历"]["n"] == 2 and rec["日历"]["total_s"] == 16.0, rec
    assert rec["前置"]["total_s"] == 8.0


def test_crawlers_have_timed_and_auto_marks():
    app = io.open(os.path.join(ROOT, "crawlers", "app_base.py"),
                  encoding="utf-8").read()
    brw = io.open(os.path.join(ROOT, "crawlers", "base.py"),
                  encoding="utf-8").read()
    for src in (app, brw):
        assert "def timed(self" in src
        assert "def phases_timer(self" in src
        assert "_phase_prev" in src, "自动打点必须留在 path_note 里"
        assert "note_phases" in src, "收尾必须写账"


def test_zhixing_has_explicit_marks():
    src = io.open(os.path.join(ROOT, "crawlers", "app_zhixing.py"),
                  encoding="utf-8").read()
    # r1063 T78 起手动打点统一带 `耗时·` 前缀（与路径名隔离）
    for name in ("耗时·前置", "耗时·导航", "耗时·日历"):
        assert 'with self.timed("%s")' % name in src, name
