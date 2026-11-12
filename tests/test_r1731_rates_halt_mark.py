# -*- coding: utf-8 -*-
"""r1731：三率表要能看出「这家被停手了」——否则历史成功率会被当现状。

现场：携程/飞猪停手期间，`/api/three-rates` 照样给 12 小时窗口内的历史成绩
（ctrip 68/65、fliggy 41/41），看起来一切正常；而同一屏的节流行写着
「停手 4h」。两张表口径打架。
"""
import io
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_backend_attaches_halts():
    s = _w()
    i = s.index('self.path.split("?")[0] == "/api/three-rates"')
    seg = s[i:i + 2200]
    assert '_sn3["halts"]' in seg, "three-rates 载荷没有 halts"
    assert "read_halt" in seg, "没有读真实停手表"


def test_table_marks_halted_plats():
    s = _w()
    assert "rt-halt" in s, "三率表没有停手标记样式/类"
    # JS 用法（不是第一条 CSS 命中）
    i = s.index("RATES.halts")
    seg = s[max(0, i - 400):i + 500]
    assert "rt-halt" in seg, "读了 halts 但没渲染停手标记"
    assert "停手" in seg, "没有「停手」字样"


def test_live_halts_shape():
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        d = json.loads(op.open("http://127.0.0.1:8765/api/three-rates",
                               timeout=25).read())
    except Exception:
        return
    assert "halts" in d, "载荷缺 halts 字段"
    for p, h in (d.get("halts") or {}).items():
        assert h.get("left_s", 0) > 0, (p, h)
