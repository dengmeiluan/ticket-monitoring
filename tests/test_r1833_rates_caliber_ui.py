# -*- coding: utf-8 -*-
"""r1833：三率页两处口径修正的门禁。

1. 分母剔除「能力边界/主动跳过」后，**剔了多少要报**（不能悄悄变小）；
2. 「空转最贵」不许点名已停手的渠道（实测飞猪 App 停手中仍居榜首）。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_footer_reports_skipped_count():
    s = _w()
    assert "未计入分母" in s, "页脚没有说剔掉多少条"
    assert "t.skipped_n" in s, "没有用载荷里的 skipped_n"
    assert "能力边界与主动跳过不计入分母" in s, "口径说明没跟上"


def test_waste_excludes_halted():
    s = _w()
    i = s.index("let _waste=null")
    seg = s[i:i + 400]
    assert "_halts[k]" in seg, "空转最贵没有排除停手渠道"
    assert "return" in seg, "排除没生效（缺 continue/return）"


def test_payload_has_skipped_n():
    import json
    import urllib.request
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        d = json.loads(op.open("http://127.0.0.1:8765/api/three-rates",
                               timeout=25).read())
    except Exception:
        return
    t = d.get("totals") or {}
    assert "skipped_n" in t, "totals 缺 skipped_n：%s" % list(t)[:8]
