# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1046_app_date_horizon.py
- tests/test_r938_date_retry_reopen.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import datetime as dt
import io
import logging
import os
import sys

from crawlers import app_zhixing_nav as nav
from crawlers.app_fliggy import AppFliggyCrawler


# ---- merged from tests/test_r1046_app_date_horizon.py ----

class _Dev:
    def current_activity(self):
        return ""


def _crawler():
    return AppFliggyCrawler({"user_data_dir": "user_data", "android": {}},
                            logging.getLogger("test"))


def _days_ahead(n):
    return (dt.date.today() + dt.timedelta(days=n)).isoformat()


def test_far_date_is_rejected():
    c = _crawler()
    assert c.reject_far_dates([_days_ahead(400)]) is True
    note = c.paths[-1]
    assert note["status"] == "unsupported"
    assert "视野" in note["detail"]


def test_near_date_passes():
    c = _crawler()
    assert c.reject_far_dates([_days_ahead(3)]) is False
    assert not c.paths


def test_horizon_boundary_is_inclusive():
    c = _crawler()
    horizon = c.date_horizon_days
    assert c.reject_far_dates([_days_ahead(horizon)]) is False
    assert c.reject_far_dates([_days_ahead(horizon + 1)]) is True


def test_mixed_dates_reject_whole_batch():
    """一批里有一条超视野，就整批交浏览器（App 侧无法只取其中一条）。"""
    c = _crawler()
    assert c.reject_far_dates([_days_ahead(2), _days_ahead(400)]) is True


def test_bad_date_string_is_ignored_not_crashing():
    c = _crawler()
    assert c.reject_far_dates(["not-a-date"]) is False


def test_empty_dates_not_rejected():
    c = _crawler()
    assert c.reject_far_dates([]) is False


# ---- merged from tests/test_r938_date_retry_reopen.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_DLG = "Search_Calendar_Dialog"
_CELL = ('<node resource-id="flight_calendar_date_cell-2026-11-16" '
         'bounds="[40,300][120,360]" />')


# ---------------------------------------------------------------------------
# 1. 源码钉：重试必须**重新打开弹层**（这是本轮修的核心）
# ---------------------------------------------------------------------------
def test_retry_reopens_dialog():
    """整个 `_tap_calendar_cell` 函数体内必须有「重开弹层」这一步。"""
    src = io.open(os.path.join(ROOT, "crawlers", "app_zhixing_nav.py"),
                  encoding="utf-8").read()
    i = src.find("def _tap_calendar_cell")
    assert i > 0
    j = src.find("\ndef ", i + 10)
    body = src[i:j if j > i else len(src)]
    assert "open_date_dialog(dev)" in body, "重试没有重新打开弹层"
    assert "重开弹层失败" in body, "重开失败没有独立证据分支"


def test_no_pointless_relookup_in_code_path():
    """不许再出现"BACK 关掉后直接找格子"那种注定失败的返回文案。"""
    src = io.open(os.path.join(ROOT, "crawlers", "app_zhixing_nav.py"),
                  encoding="utf-8").read()
    # 只允许出现在说明性注释里（带「实测报」前缀）
    for ln in src.splitlines():
        if "重试时找不到格子" in ln:
            assert "实测报" in ln, "旧的无意义重试文案还在代码路径里：%s" % ln


# ---------------------------------------------------------------------------
# 2. 行为钉：弹层没关时，重试必须先调 open_date_dialog 再点格子
# ---------------------------------------------------------------------------
class ScriptedDev:
    """按调用次序给帧；tap/keyevent 记录动作，不模拟真实渲染。"""

    def __init__(self, frames):
        self.frames = list(frames)
        self.i = 0
        self.taps = []
        self.backs = 0

    def dump(self):
        f = self.frames[min(self.i, len(self.frames) - 1)]
        self.i += 1
        return f

    def tap(self, x, y):
        self.taps.append((x, y))
        return True

    def keyevent(self, code):
        self.backs += 1
        return True

    def swipe(self, *a, **k):
        return True


def test_retry_calls_open_date_dialog(monkeypatch):
    """核心断言：走重试分支时 `open_date_dialog` 被调用过。

    帧序列要满足真实流程：
      ① 首次 dump：日历里**有**目标格 → 点击
      ② 点击后 dump：**弹层还在** → 进入「弹层没关」分支
      ③ dismiss 第 1 次 dump：弹层还在 → 按 BACK
      ④ dismiss 第 2 次 dump：弹层已关 → gone=True（这才进重试）
      ⑤ 重试：open_date_dialog（桩，返回失败）→ 如实报
    """
    called = {"open": 0}

    def fake_open(dev, log=None):
        called["open"] += 1
        return False, "（测试桩）不真打开"

    monkeypatch.setattr(nav, "open_date_dialog", fake_open)
    frames = [
        _CELL,                                    # ① 有格子
        f'<node text="{_DLG}" />',                # ② 点完弹层还在
        f'<node text="{_DLG}" />',                # ③ dismiss: 还在 → BACK
        '<node text="机票查询" />',                # ④ dismiss: 已关
        '<node text="机票查询" />',                # ⑤ 重开前 dump
    ]
    d = ScriptedDev(frames)
    ok, why = nav._tap_calendar_cell(d, d.dump(), "2026-11-16")
    assert ok is False
    assert called["open"] >= 1, "重试时没有重新打开弹层（就地找格子注定失败）"
    assert "重开弹层失败" in why, why


def test_gives_up_when_dialog_never_closes(monkeypatch):
    """弹层始终关不掉：dismiss 之后仍开着 → 如实报「弹层没关」。"""
    def fake_open(dev, log=None):
        raise AssertionError("既然 dismiss 没关掉，就不该进入重开流程")
    monkeypatch.setattr(nav, "open_date_dialog", fake_open)
    # dismiss_until_gone 会连续看到弹层 → gone=False
    d = ScriptedDev([_CELL] + [f'<node text="{_DLG}" />'] * 12)
    ok, why = nav._tap_calendar_cell(d, d.dump(), "2026-11-16")
    assert ok is False
    assert "弹层没关" in why, why


def test_attempt_cap_prevents_infinite_loop(monkeypatch):
    """重开成功但每次点完弹层都不关：必须停在 attempt 上限，不许无限递归。"""
    opened = {"n": 0}

    def fake_open(dev, log=None):
        opened["n"] += 1
        return True, "已打开"
    monkeypatch.setattr(nav, "open_date_dialog", fake_open)
    # 永远给"有格子 + 点完弹层还在"的帧
    d = ScriptedDev([_CELL] + [f'<node text="{_DLG}" />'] * 200)
    ok, why = nav._tap_calendar_cell(d, d.dump(), "2026-11-16")
    assert ok is False
    assert opened["n"] <= 6, "重开次数没有上限：%d" % opened["n"]
