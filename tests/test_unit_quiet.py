# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1716_quiet_window_visible.py
- tests/test_r1739_quiet_header.py
- tests/test_r1763_quiet_header_time.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import json
import os
import urllib.request


# ---- merged from tests/test_r1716_quiet_window_visible.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def test_pulse_payload_carries_quiet():
    s = _w()
    i = s.index('self.path == "/api/pulse"')
    seg = s[i:i + 1400]
    assert '"quiet"' in seg, "pulse 载荷没有 quiet 段"
    assert "seconds_until_quiet_end" in seg, "没有给出距恢复时长"


def test_page_renders_quiet_note():
    s = _w()
    assert "quietNote" in s, "页面没有静默提示节点"
    assert "夜间静默中" in s, "没有静默文案"
    assert ".quiet-note" in s, "没有静默提示样式"


def test_live_pulse_quiet_shape():
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        d = json.loads(op.open("http://127.0.0.1:8765/api/pulse",
                               timeout=20).read())
    except Exception:
        return
    q = d.get("quiet")
    assert isinstance(q, dict), "pulse 没有 quiet"
    for k in ("start", "end", "active", "left_s"):
        assert k in q, "quiet 缺字段 %s：%r" % (k, q)
    if q["active"]:
        assert q["start"] and q["end"], "静默中却没有起止时间：%r" % q
        assert q["left_s"] > 0, "静默中却没有剩余时长：%r" % q


# ---- merged from tests/test_r1739_quiet_header.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


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


# ---- merged from tests/test_r1763_quiet_header_time.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def test_header_uses_next_run_time():
    w = _w()
    i = w.index("QUIET.start")   # 页头 chip（脉冲卡那条也含同样文案）
    seg = w[max(0, i - 400):i + 500]
    assert "_nx" in seg, "没有取 next_run 的时刻"
    assert "开跑" in seg, "没有写「HH:MM 开跑」"
    assert "toTimeString" in seg, "没有从 NEXTRUN 取时分"
