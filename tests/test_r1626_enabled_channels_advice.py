# -*- coding: utf-8 -*-
"""r1626：不在采集清单里的渠道，advice 必须说「不在清单」而不是「去查进程」。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pacing import advise  # noqa: E402

NOW = time.time()
OLD = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(NOW - 33 * 3600))


def _node():
    return {"last_seen_at": OLD, "paths": {}}


def test_disabled_channel_says_not_in_plan():
    got = advise("qunar", {}, {}, now=NOW, node=_node(),
                 enabled={"fliggy", "ctrip", "tongcheng", "tuniu"})
    assert got["state"] == "disabled", got
    assert got["severity"] == "ok", got
    assert "不在你的采集清单" in got["hint"], got["hint"]
    assert "检查监控进程" not in got["hint"], (
        "不在清单里的渠道仍教人去查进程：%s" % got["hint"])


def test_enabled_but_stale_still_warns_about_process():
    got = advise("qunar", {}, {}, now=NOW, node=_node(),
                 enabled={"qunar", "fliggy"})
    assert got["state"] == "stalled", got
    assert "采集没在跑" in got["hint"], got["hint"]


def test_no_enabled_arg_keeps_old_behaviour():
    got = advise("qunar", {}, {}, now=NOW, node=_node())
    assert got["state"] == "stalled", got


def test_empty_enabled_is_not_treated_as_all_disabled():
    # 调用方读不到清单时传 None（而不是空集）；空集会被当成"全都不在清单"。
    got = advise("qunar", {}, {}, now=NOW, node=_node(), enabled=None)
    assert got["state"] == "stalled", got
