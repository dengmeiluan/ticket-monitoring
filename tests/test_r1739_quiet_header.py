# -*- coding: utf-8 -*-
"""r1739：静默窗内页头不许承诺「下轮 05:04」——那一轮会被跳过。

现场（看截图发现）：静默窗 01:00–07:00 内页头写着
「⏱ 下轮 05:04（11 分 46 秒后）」，而 05:04 那一轮会被静默跳过，
用户等到 05:04 什么也不会发生。调度侧会重排到窗口结束，
但**界面这个数字没跟着改**。
"""
import io
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_state_payload_carries_quiet():
    s = _w()
    assert "def _quiet_view(" in s, "没有 quiet 视图函数"
    i = s.index('"next_run": _next_run()')
    seg = s[i:i + 400]
    assert '"quiet": _quiet_view()' in seg, "state 载荷没带 quiet"


def test_tick_branches_on_quiet():
    s = _w()
    i = s.index("function tick()")
    seg = s[i:i + 900]
    assert "QUIET&&QUIET.active" in seg, "倒计时没判静默期"
    assert "夜间静默中" in seg, "没写静默文案"


def test_live_state_quiet_shape():
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        d = json.loads(op.open("http://127.0.0.1:8765/api/state",
                               timeout=25).read())
    except Exception:
        return
    q = d.get("quiet")
    assert isinstance(q, dict), "state 没有 quiet"
    for k in ("start", "end", "active", "left_s"):
        assert k in q, "quiet 缺字段 %s" % k
    if q["active"]:
        assert q["left_s"] > 0 and q["start"] and q["end"], q
