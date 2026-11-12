# -*- coding: utf-8 -*-
"""r1770：点城市位落到火车票页时，必须切回机票 tab 再试一次（不是直接收工）。

07:00 那轮的真实账本：

```
07:00:51 app-city timeout · 点城市位后未打开城市页 · 页面: 火车票
```

进表单时还是机票（入口守卫放行），点城市位那一下落到顶部 tab，页面被切成火车票，
原实现直接记 timeout 收工——白丢一整次尝试。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_tongcheng import AppTongchengCrawler, is_train_page  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIN = os.path.join(ROOT, "tests", "fixtures", "tongcheng_train_page.xml")


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, fmt, *a):
        self.lines.append(fmt % a if a else fmt)

    warning = info


class _Dev:
    """假设备：dump 依次返回给定 XML；tap 记录调用。"""

    def __init__(self, pages):
        self.pages = list(pages)
        self.taps = []

    def dump(self):
        return self.pages[0] if self.pages else ""

    def tap(self, x, y):
        self.taps.append((x, y))
        if len(self.pages) > 1:
            self.pages.pop(0)
        return True

    def keyevent(self, k):
        return True

    def current_activity(self):
        return "com.tongcheng.android/.Main"


def _train():
    return io.open(TRAIN, encoding="utf-8", errors="replace").read()


def test_recover_helper_switches_back_to_flight_tab():
    xml = _train()
    c = AppTongchengCrawler({}, _Log())
    c.paths = []
    c.user_data_root = os.path.join(ROOT, "_scratch", "_u")
    # 第一次 dump 是火车票页，tap 之后模拟「变成机票表单」
    flight = xml.replace("查询火车票", "机票查询")
    dev = _Dev([xml, flight])
    page = c._recover_flight_tab(dev)
    assert page, "没切回机票"
    assert not is_train_page(page), "仍是火车票页"
    assert dev.taps, "没有点机票 tab"


def test_failure_note_distinguishes_train_page():
    src = io.open(os.path.join(ROOT, "crawlers", "app_tongcheng.py"),
                  encoding="utf-8").read()
    assert "_recover_flight_tab" in src, "没有恢复助手"
    assert "点城市位后落到火车票页" in src, "失败时没说清是火车票页"
    assert "切回机票后仍打不开城市页" in src, "恢复失败的记账缺失"
