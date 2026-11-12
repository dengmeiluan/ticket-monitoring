# -*- coding: utf-8 -*-
"""r1783：两个 App 渠道按用户决定搁置——界面必须说清"为什么不动"。

用户 2026-11-12：「携程 App / 飞猪 App 登录风控无法登录，暂时放弃」。

这条测试守三件事：
1. 决策有落档（`docs/CHANNEL_PARKED.md`），含原因与恢复方式；
2. 停手建议里**带得出理由**（不能只剩「剩 N 分钟」）；
3. 时长可读（7 天不该写成 10079 分钟）。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _doc():
    return io.open(os.path.join(ROOT, "docs", "CHANNEL_PARKED.md"),
                   encoding="utf-8").read()


def test_decision_is_documented():
    d = _doc()
    for k in ("app_ctrip", "app_fliggy", "登录风控", "暂时放弃",
              "恢复", "浏览器通路"):
        assert k in d, "落档缺 " + k


def test_halt_hint_carries_note_and_readable_duration():
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert "人工停手中：%s · 剩 %s" in w, "停手建议没把理由拼进去"
    assert '_hrow3.get("note")' in w, "没读停手的 note"
    assert "_mins >= 48 * 60" in w, "没有「天」这一档时长"
    assert "_mins >= 120" in w, "没有「小时」这一档时长"


def test_browser_lanes_untouched():
    """App 停手不该牵连浏览器通路（两条独立 platform 键）。"""
    d = _doc()
    assert "ctrip" in d and "fliggy" in d
    assert "正常出数" in d or "不受影响" in d
