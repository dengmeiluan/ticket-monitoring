# -*- coding: utf-8 -*-
"""r938：重试时弹层已被 BACK 关掉，就地找格子当然找不到。

真实日志（2026-11-04 11:53，r934 的重试上线后第一次跑）：

    [app_zhixing] 明细前置选日期失败：点了日期但弹层没关（重试时找不到格子）

`r934` 加的重试逻辑是：

```python
gone, _ = dismiss_until_gone(dev, "Search_Calendar_Dialog", tries=1)
if attempt < 4:
    cell2 = _calendar_cell(dev.dump() or "", ymd)      # ← 这里错了
    ...
    else:
        return False, "点了日期但弹层没关（重试时找不到格子）"
```

`dismiss_until_gone()` 的职责就是**把弹层关掉**；关掉之后
`_calendar_cell()` 当然找不到格子——这一步注定失败，
「重试」等于白做，只是把文案从"弹层没关"换成"重试时找不到格子"。

正确顺序是**重新打开弹层 → 再走一遍滚动查找 → 点击**。
次数由 `attempt` 上限（5 次）兜住，不会无限递归。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r938_date_retry_reopen.py -q
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers import app_zhixing_nav as nav  # noqa: E402

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
