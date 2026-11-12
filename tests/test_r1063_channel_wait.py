# -*- coding: utf-8 -*-
"""r1063 T30：渠道「在等」多少秒必须看得见（不只是写日志）。

背景：`data/pulse.json` 里 qunar 单查询 82.8s 是最大头。它内部早就算过等待预算
（`_WAIT_BUDGET`，300s/轮封顶），但那个数**只写日志**——用户只知道"qunar 慢"，
不知道"慢在等我方限速"。抓取慢和等待慢，优化手段完全不同。
"""
import io
import os

from core.pacing import Pacing

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
MAIN = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
BASE = io.open(os.path.join(ROOT, "crawlers", "base.py"),
               encoding="utf-8").read()
QUNAR = io.open(os.path.join(ROOT, "crawlers", "qunar.py"),
                encoding="utf-8").read()


def test_pacing_accumulates_channel_wait():
    p = Pacing({})
    p.note_chan_wait("qunar", 210.5)
    p.note_chan_wait("qunar", 20)
    p.note_chan_wait("", 99)          # 空渠道名：忽略
    p.note_chan_wait("ctrip", 0)      # 零：忽略
    ch = p.snapshot()["channels"]
    assert ch["qunar"]["waited_s"] == 230.5, ch.get("qunar")
    assert "waited_s" not in (ch.get("ctrip") or {})


def test_crawler_has_one_wait_meter():
    """统一抽象：闸门睡眠与渠道内部等待都走同一个记账入口。"""
    assert "def note_wait(self, sec)" in BASE
    assert "self.waited_s: float = 0.0" in BASE
    assert "self.note_wait(_slp)" in BASE, "path_gate 睡眠没记账"
    assert "self.note_wait(wait)" in QUNAR, "qunar 预算累计没同步进等待表"


def test_main_reports_wait_deltas():
    """读**增量**：读绝对值会重复累加（同一个渠道多查询）。"""
    assert "_wait_seen = {}" in MAIN
    assert "pac.note_chan_wait(c.name, _wd)" in MAIN
    assert "_wd = _wf - float(_wait_seen.get(c.name) or 0.0)" in MAIN


def test_health_row_shows_wait_without_changing_geometry():
    """等待读数塞进既有的 `.ev .e2` 那一行——另起一行会破坏行高门禁。"""
    assert "const _waitTxt=(()=>{" in SRC
    seg = SRC[SRC.index("const _waitTxt=(()=>{"):][:400]
    assert "if(!(w>0))return '';" in seg
    assert 'i class="e2k">等待</i>' in SRC
    assert "_pen2||_waitTxt" in SRC, "e2 的显示条件没带上等待"
