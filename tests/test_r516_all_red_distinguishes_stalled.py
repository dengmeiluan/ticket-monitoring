# -*- coding: utf-8 -*-
"""r516：用户反馈「登录都配置好了，但渠道全是红的」——要能分清是哪一种红。

真实场景（本机 data/prices.db 实测即如此）：
  `path_stats(24)` 对五个渠道全部返回空窗口 → `advise` 走
  `not attempts and not q_attempts` 分支，统一回「近 24h 无样本：先跑一轮再判断」。
  而实际情况是**采集自 10-28 14:34 起就没再跑过**（fliggy 这一天重登 103 次，
  渠道一直红）。让一个已经等了 25 小时的人「先跑一轮再判断」，等于让他继续等——
  真正要查的是监控进程/调度有没有在跑。

两种「红」必须分开：
  · `unknown`（待首轮）：刚启动的正常过渡，动作=等一轮；
  · `stalled`（采集停了）：故障，动作=查采集进程，**不要重做登录**。
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.pacing import advise  # noqa: E402


def _node(last_at):
    return {"query_attempts": 0, "paths": {}, "last_at": last_at,
            "last_ok_at": last_at, "scopes": {}}


def _ts(hours_ago):
    return time.strftime("%Y-%m-%d %H:%M:%S",
                         time.localtime(time.time() - hours_ago * 3600))


def test_recent_empty_window_is_still_unknown():
    """刚启动 / 刚清库：仍然说「先跑一轮」，不能一上来就报警。"""
    a = advise("ctrip", {}, {}, node=_node(_ts(0.2)))
    assert a["state"] == "unknown", a
    assert a["severity"] == "ok", a


def test_long_silence_is_reported_as_stalled_not_as_first_round():
    a = advise("fliggy", {}, {}, node=_node(_ts(25)))
    assert a["state"] == "stalled", "采集停了 25 小时仍判成「待首轮」：%r" % (a,)
    assert a["severity"] == "act", "停摆被标成无需处理：%r" % (a,)
    assert "采集" in a["hint"], a
    # 关键：必须明确「登录状态本身无需重做」，否则用户会去反复重登
    assert "登录" in a["hint"], \
        "没有告诉用户这跟登录无关（会引发无效重登）：%r" % (a["hint"],)
    assert "25" in a["hint"] or "24" in a["hint"], \
        "没有说明停了多久：%r" % (a["hint"],)


def test_no_sample_ever_is_unknown_not_stalled():
    """从未采集过（没有 last_at）：不能说「停了」，那是新装。"""
    a = advise("tuniu", {}, {}, node=_node(""))
    assert a["state"] == "unknown", a


def test_fresh_samples_but_no_window_is_not_stalled():
    """刚有样本、只是本轮窗口空（例如刚清空统计）：不算停摆。"""
    a = advise("qunar", {}, {}, node=_node(_ts(1)))
    assert a["state"] == "unknown", a


def test_panel_renders_the_stalled_state_distinctly():
    import io
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert "adv.state==='stalled'" in w, "节流行没有专门的「采集停了」分支"
    i = w.index("adv.state==='stalled'")
    seg = w[i:i + 420]
    assert "采集停了" in seg, "标签没有说明是采集停了"
    assert "bad" in seg, "停摆没有用告警色"
    # 与「待首轮」必须仍是两个独立分支（顺序在前，各管各的）
    j = w.index("adv.state==='unknown'")
    assert i < j, "「采集停了」分支必须排在「待首轮」之前"


def test_backend_supplies_cross_window_last_seen(monkeypatch, tmp_path):
    """窗口内一条记录都没有时，仍要能拿到全表最近样本。

    用临时库固定「fliggy 最后一条样本在 26 小时前」的形态：不依赖本机
    生产库当下是否恰好在跑，干净克隆也能复核同一条判据。
    """
    import sqlite3

    import webui

    stale = _ts(26)
    db = str(tmp_path / "prices.db")
    conn = sqlite3.connect(db)
    try:
        conn.execute("CREATE TABLE fetch_paths (platform TEXT, fetched_at TEXT)")
        conn.execute("INSERT INTO fetch_paths VALUES ('fliggy', ?)", (stale,))
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(webui._State, "cfg",
                        {"output": {"db_path": db}}, raising=False)
    ls = webui._last_seen_of("fliggy")
    assert ls == stale, "拿不到不限窗口的最近样本：%r" % (ls,)
    a = advise("fliggy", {}, {}, node={"last_seen_at": ls}, quiet={})
    assert a["state"] == "stalled", \
        "拿到 26 小时前的样本仍判成「待首轮」：%r" % (a,)
    assert "登录" in a["hint"], "没有点明与登录无关"
