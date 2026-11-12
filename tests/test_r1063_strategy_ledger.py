# -*- coding: utf-8 -*-
"""r1063 T51：策略成效账本——「这条自动策略到底有没有用」。

`pacing` 的计数是**进程内**的，重启归零。于是用户永远回答不了那个关键问题，
只能凭感觉开或干脆关掉。这轮加一份跨进程的 7 天账本：

    近 7 天：换道 12 次、预置 9 次，救回 37 条 · 会话重建 3 次，其中 2 次下一轮恢复

`recovered` 不是猜的：重建时把渠道挂进 `pending`，**它下一次真的出数**才记一次
恢复——这才叫"有用"的证据。
"""
import io
import json
import os
import tempfile
import time

from core import strategy_ledger as sl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
FO = io.open(os.path.join(ROOT, "core", "failover.py"), encoding="utf-8").read()
SRC = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_record_and_summarise_failover():
    d = tempfile.mkdtemp()
    sl.record_failover(switches=2, rows=7, root=d)
    sl.record_failover(switches=1, rows=3, preloads=4, root=d)
    s = sl.summary(days=7, root=d)
    assert s["failover"] == {"preloads": 4, "switches": 3, "rows": 10}, s
    assert s["reset"] == {"n": 0, "recovered": 0}
    assert s["recovered_ratio"] is None, "没有重建时不该编一个比率"


def test_reset_counts_recovery_only_when_data_returns():
    d = tempfile.mkdtemp()
    sl.record_reset("fliggy", root=d)
    assert sl.summary(root=d)["reset"] == {"n": 1, "recovered": 0}
    # 重建之后该渠道第一次出数 → 记一次恢复
    assert sl.mark_recovered("fliggy", root=d) is True
    assert sl.summary(root=d)["reset"] == {"n": 1, "recovered": 1}
    # 没有 pending 的"恢复"不算数（不认识的恢复不能编）
    assert sl.mark_recovered("fliggy", root=d) is False


def test_clear_pending_avoids_crediting_a_later_success():
    """重建后又失败/没重建：撤掉 pending，别把很久以后的成功算成"重建救回来的"。"""
    d = tempfile.mkdtemp()
    sl.record_reset("ctrip", root=d)
    sl.clear_pending("ctrip", root=d)
    assert sl.mark_recovered("ctrip", root=d) is False


def test_window_only_counts_recent_days():
    d = tempfile.mkdtemp()
    old = time.time() - 30 * 86400
    sl.record_failover(switches=5, root=d, now=old)
    sl.record_failover(switches=1, root=d)
    s = sl.summary(days=7, root=d)
    assert s["failover"]["switches"] == 1, "30 天前的记录不该进 7 天窗口"


def test_ledger_prunes_old_days():
    d = tempfile.mkdtemp()
    for i in range(sl.KEEP_DAYS + 5):
        sl.record_failover(switches=1, root=d,
                           now=time.time() - i * 86400)
    with open(sl.ledger_path(d), encoding="utf-8") as f:
        data = json.load(f)
    assert len(data["days"]) <= sl.KEEP_DAYS, len(data["days"])


def test_broken_ledger_never_raises():
    """账本坏掉不许影响采集（这是采集链上的旁路）。"""
    d = tempfile.mkdtemp()
    p = sl.ledger_path(d)
    os.makedirs(d, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("{ 这不是 json")
    sl.record_failover(switches=1, root=d)          # 不抛
    assert sl.summary(root=d)["failover"]["switches"] >= 1


def test_every_caller_is_wired():
    assert "strategy_ledger" in MAIN, "main 没记换道/重建"
    assert "record_reset(" in MAIN
    assert "record_failover(" in MAIN
    assert "record_failover(preloads=" in FO, "预置发生在 failover 里，要在那里记"


def test_ui_shows_the_seven_day_line():
    seg = SRC[SRC.index("const _foPlatTitle="):][:2600]
    assert "f.history" in seg
    assert "近 " in seg and "救回 " in seg
    assert "下一轮恢复" in seg
