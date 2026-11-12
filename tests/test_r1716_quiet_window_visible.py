# -*- coding: utf-8 -*-
"""r1716：夜间静默必须在页面上说出来。

我自己被误导过一次：同程 App 两小时没记录，我当故障排查，其实日志写着
「夜间静默窗 01:00–07:00 内，本轮跳过采集」——而页面上一个字都没有。
"""
import io
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


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
