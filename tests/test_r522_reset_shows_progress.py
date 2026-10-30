# -*- coding: utf-8 -*-
"""r522：干预按钮在途时必须换文案，不能只置灰。

节流面板有四个会真打链路的干预入口，耗时都不短：

    warmNow   预热     3–8 秒     ← 已有「预热 XX 中…（约 3–8 秒）」
    probeNow  自检     10–60 秒   ← 已有「正在自检 XX（约 10–60 秒）」
    verifyNow 去验证    开窗        ← 开窗本身即时返回，无需进度文案
    paceReset 解除     10–60 秒   ← **只置灰、文案不变**（本次修复）

解除要塞一个真实查询回来后端才回答「解了到底通没通」。只置灰的话，
读者看不出它在干活，会以为点了没反应，于是再点一次（虽然被
`PACE_BUSY` 挡住，但人还是白等了）。同族的另外两个都写了「XX 中…（约 N 秒）」，
只有这里漏了 —— 这是同族交互不一致，不是风格选择。
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def _fn(src, name):
    i = src.index("async function %s(" % name)
    j = src.index("\n}", i)
    return src[i:j]


def test_reset_shows_progress_text_while_in_flight():
    seg = _fn(_w(), "paceReset")
    assert "解除中…" in seg, "解除没有进行中文案（只置灰看不出在干活）"
    assert "10–60 秒" in seg, "没有给出可等待的时长量级"
    # 必须真的写进按钮
    assert "textContent='解除中…" in seg.replace(" ", ""), \
        "文案没有赋给按钮"


def test_reset_restores_the_original_label():
    seg = _fn(_w(), "paceReset")
    assert "_rTxt" in seg, "没有保存原按钮文案"
    assert "_rb.textContent=_rTxt" in seg, "结束时没有还原按钮文案"


def test_every_slow_intervention_has_visible_progress():
    """四个入口里，凡是会跑长链路的都要有可见进度（verify 开窗即时返回除外）。"""
    src = _w()
    for fn, needle in (("warmNow", "中…"), ("probeNow", "正在自检"),
                       ("paceReset", "解除中…")):
        seg = _fn(src, fn)
        assert needle in seg, "%s 没有「进行中」文案" % fn
        assert "aria-busy" in seg, "%s 没有标记 aria-busy" % fn


def test_progress_text_is_restored_not_left_stuck():
    """在途文案必须能在结束时消失——否则按钮会永久显示「…中」。"""
    src = _w()
    for fn in ("paceReset", "warmNow", "probeNow"):
        seg = _fn(src, fn)
        assert "finally" in seg, "%s 没有 finally 兜底（异常时会卡在…中）" % fn
