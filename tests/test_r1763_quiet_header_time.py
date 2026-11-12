# -*- coding: utf-8 -*-
"""r1763：静默页头要写**真实开跑时刻**（窗口结束+1 分钟），不是笼统「07:00 后恢复」。"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_header_uses_next_run_time():
    w = _w()
    i = w.index("QUIET.start")   # 页头 chip（脉冲卡那条也含同样文案）
    seg = w[max(0, i - 400):i + 500]
    assert "_nx" in seg, "没有取 next_run 的时刻"
    assert "开跑" in seg, "没有写「HH:MM 开跑」"
    assert "toTimeString" in seg, "没有从 NEXTRUN 取时分"
