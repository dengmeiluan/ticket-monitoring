# -*- coding: utf-8 -*-
"""r1744：空转（多次尝试 0 出数）时，建议升级为「先停手排查」。

现场：同程 App 12 小时 122 次尝试 / 0 出数（App 单次 100–200 秒 = 白烧几个小时），
而 advice 只说「近 24h 成功率 0%，观察一轮；连续两轮再干预」。
**空转比失败更贵**——失败至少还带信息，空转什么都不带。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pacing import advise  # noqa: E402

NOW = time.time()
QUIET_OFF = {"active": False}


def _node(att, ok):
    return {"query_attempts": att, "query_ok": ok,
            "last_seen_at": time.strftime("%Y-%m-%d %H:%M:%S",
                                          time.localtime(NOW - 30)),
            "paths": {}}


def test_many_attempts_zero_output_escalates_to_halt():
    got = advise("app_tongcheng", {}, {}, now=NOW, node=_node(25, 0),
                 quiet=QUIET_OFF)
    assert got["action"] == "halt", got
    assert got["severity"] == "act", got
    assert "0 出数" in got["hint"] and "停手" in got["hint"], got["hint"]


def test_few_attempts_still_watch():
    got = advise("x", {}, {}, now=NOW, node=_node(5, 0), quiet=QUIET_OFF)
    assert got["action"] == "watch", got


def test_healthy_attempts_not_escalated():
    got = advise("x", {}, {}, now=NOW, node=_node(25, 10), quiet=QUIET_OFF)
    assert got["action"] != "halt", got


def test_threshold_is_documented():
    import io
    p = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "core", "pacing.py")
    src = io.open(p, encoding="utf-8").read()
    assert ">= 20 and _qok == 0" in src or ">= 20 and _qok == 0" in src.replace(
        " ", " "), "阈值判断不在（20 次尝试 0 出数）"
    assert "空转比失败更贵" in src, "缺理由说明"
