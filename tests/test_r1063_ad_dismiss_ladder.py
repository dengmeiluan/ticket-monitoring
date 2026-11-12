# -*- coding: utf-8 -*-
"""r1063 T65：广告层「关不掉就整轮停手」→ 降级关闭阶梯。

**生产证据**（`data/prices.db`，2026-11-08 07:02–07:04，智行）：
```
app-blocker | ad | 0 | 营销弹层（未找到关闭按钮）   ×3
```
根因：`_clear_blockers()` 在 `block.close_xy is None` 时**直接 return**，
一次尝试都不做。而广告层至少有四种关法。

真机端到端（同一台升级到 10.26.2 的智行，2026-11-08 09:06）：
`fetch("SHA","PEK",["2026-11-16"])` → **100.3 秒返回 1 条**（KN5956 ¥337），
`last_path=航班明细`、`login_suspect=False` —— 升级后链路仍然可用。
"""
import io
import logging
import os

import pytest

from crawlers.app_base import AppCrawler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = io.open(os.path.join(ROOT, "crawlers", "app_base.py"),
               encoding="utf-8").read()

# `_texts()` 需要 `bounds`，`has_payload()` 靠航班号/价格判"有没有数据"
AD_XML = ('<hierarchy>'
          '<node text="新人专享 限时秒杀" bounds="[100,300][900,360]"/>'
          '<node text="立即领取" bounds="[300,900][900,980]"/>'
          '<node text="活动规则" bounds="[100,1000][600,1060]"/>'
          '</hierarchy>')
CLEAN_XML = ('<hierarchy>'
             '<node text="航班列表" bounds="[100,300][900,360]"/>'
             '<node text="KN5956" bounds="[100,500][400,560]"/>'
             '<node text="¥337" bounds="[700,500][900,560]"/>'
             '</hierarchy>')


class _Dev:
    """假设备：记录 tap/keyevent；BACK 之后页面就"干净"了。"""

    def __init__(self, close_on="BACK"):
        self.close_on = close_on
        self.taps = []
        self.keys = []
        self._clean = False

    def dump(self):
        return CLEAN_XML if self._clean else AD_XML

    def tap(self, x, y):
        self.taps.append((x, y))
        if self.close_on == "tap":
            self._clean = True
        return True

    def keyevent(self, key):
        self.keys.append(key)
        if self.close_on == "BACK":
            self._clean = True
        return True

    def window_size(self):
        return (1260, 2800)


def _crawler():
    return AppCrawler({"android": {}}, logging.getLogger("t65"))


def test_ad_without_close_button_uses_back_and_records_how():
    """7:02 那三次失败，就是因为"找不到关闭钮"直接放弃。"""
    c = _crawler()
    notes = []
    c.path_note = lambda *a, **kw: notes.append((a, kw))
    dev = _Dev(close_on="BACK")
    xml, block = c._clear_blockers(dev, AD_XML)
    assert block.kind != "ad", "BACK 之后不该还是广告态"
    assert "BACK" in dev.keys
    assert any("app-ad" in str(n[0]) for n in notes), notes


def test_ad_that_only_closes_on_corner_tap():
    """有的层不认 BACK，只认右上角热区。"""
    c = _crawler()
    c.path_note = lambda *a, **kw: None
    dev = _Dev(close_on="tap")
    xml, block = c._clear_blockers(dev, AD_XML)
    assert dev.taps, "应当尝试点了右上角/遮罩"
    assert block.kind != "ad" or not xml


def test_no_screen_size_does_not_crash_the_ladder():
    """读不到屏幕尺寸时不许抛（也不许因此整轮失败）。"""
    c = _crawler()
    c.path_note = lambda *a, **kw: None
    dev = _Dev(close_on="BACK")
    dev.window_size = lambda: (0, 0)
    xml, block = c._clear_blockers(dev, AD_XML)
    assert block.kind != "ad"


def test_screen_wh_prefers_window_size_and_returns_none_honestly():
    assert AppCrawler._screen_wh(_Dev()) == (1260, 2800)

    class NoSize:
        pass

    assert AppCrawler._screen_wh(NoSize()) is None


def test_ladder_is_wired_into_the_source():
    assert "_screen_wh" in BASE
    assert "BACK" in BASE
    assert "_note_ad_closed" in BASE
    # 不许再出现"没有关闭钮就直接 return"的老写法
    assert "if block.kind != \"ad\" or not block.close_xy:" not in BASE
