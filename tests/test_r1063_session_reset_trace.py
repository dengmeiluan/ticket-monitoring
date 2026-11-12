# -*- coding: utf-8 -*-
"""r1063 T49：会话重建的**判据链**可视化（为什么判它该重建）。

光有「已重建 2 次」回答不了用户的真实疑问：**凭什么**？决策发生在 main，
但它用的输入（连续被拦几次、什么类型、上次重建多久前、今天第几次）界面看不到。

做法：把输入搬进 `pacing.snapshot()` 的 `channels[plat].sr`，界面原样展示成
悬停提示——**读数与决策同源**，界面不自己算，才不会出现"界面说该重建、
实际没重建"这种最难查的不一致。
"""
import io
import os
import time

from core.pacing import Pacing

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
MAIN = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()


def test_pacing_exposes_the_judgment_chain():
    p = Pacing({"fliggy": {}})
    p.note_reset("fliggy")
    p.note_sr_state("fliggy", fails=3, kind="captcha",
                    last_ts=time.time() - 3600, day=1, why="连续被拦 3 次")
    sr = p.snapshot()["channels"]["fliggy"]["sr"]
    assert sr["fails"] == 3 and sr["kind"] == "captcha"
    assert sr["day"] == 1 and "连续被拦" in sr["why"]


def test_state_merges_partial_updates():
    """只报一项时不许把别的项清空（每轮上报的字段可能不齐）。"""
    p = Pacing({"ctrip": {}})
    p.note_sr_state("ctrip", fails=2, kind="ip")
    p.note_sr_state("ctrip", day=3)
    sr = p.snapshot()["channels"]["ctrip"]["sr"]
    assert sr["fails"] == 2 and sr["kind"] == "ip" and sr["day"] == 3, sr


def test_no_field_when_nothing_happened():
    p = Pacing({"qunar": {}})
    assert "sr" not in (p.snapshot()["channels"]["qunar"] or {})


def test_ui_builds_the_tooltip_from_the_chain():
    seg = SRC[SRC.index("const _srTitle=(()=>{"):][:1400]
    for token in ("sr.why", "sr.fails", "sr.last_ts", "sr.day"):
        assert token in seg, token
    assert "esc(_srTitle)" in SRC, "提示文案没有转义就写进 title"


def test_tooltip_does_not_add_layout():
    """读数与解释都挂在既有 `.e2` / `<i class="e2k">` 上，不新增可见节点。"""
    i = SRC.index("_srTxt?((")
    seg = SRC[i:i + 400]
    assert 'class="e2k"' in seg
    assert "title=" in seg


def test_main_reports_the_chain_every_round():
    assert "note_sr_state(" in MAIN
    i = MAIN.index("note_sr_state(")
    seg = MAIN[i:i + 700]
    for token in ("fails=", "last_ts=", "day=", "why="):
        assert token in seg, token
    # 上报失败不许影响采集
    assert "except Exception" in MAIN[max(0, i - 400):i + 900]
