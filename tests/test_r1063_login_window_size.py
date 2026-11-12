# -*- coding: utf-8 -*-
"""r1063 T140：登录弹窗尺寸可配、按端给默认值（用户诉求："友好人操作登录"）。

原来固定 `--window-size=1180,760`：PC 表格偏小、H5 手机页面挤在大窗左侧。
现在：
* `web.login_window`      → PC 默认 **1280×900**
* `web.login_window_h5`   → H5 默认 **480×880**（手机比例，点得到控件）
* 非法/过小配置自动退回默认（**这里抛异常等于弹不出窗**）

真机验证（`login_window_size()`）：
```
PC 默认 (1280, 900) | H5 默认 (480, 880)
PC 自定义 (1500, 950) | H5 自定义 (420, 900)
非法退回 (1280, 900) | 过小退回 (1280, 900)
```
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.base import BaseCrawler  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _F(BaseCrawler):
    package = "x"

    def __init__(self, cfg, mobile):
        self.config = cfg
        self.use_mobile = mobile

    def login_url(self):
        return "https://x/"


def test_pc_default():
    assert _F({}, False).login_window_size() == (1280, 900)


def test_h5_default_is_phone_shaped():
    w, h = _F({}, True).login_window_size()
    assert w < h, "H5 窗口要给手机比例，否则控件点不准"
    assert (w, h) == (480, 880)


def test_config_override_both_surfaces():
    assert _F({"web": {"login_window": {"w": 1500, "h": 950}}},
              False).login_window_size() == (1500, 950)
    assert _F({"web": {"login_window_h5": {"w": 420, "h": 900}}},
              True).login_window_size() == (420, 900)


def test_bad_or_tiny_config_falls_back():
    assert _F({"web": {"login_window": {"w": "abc"}}},
              False).login_window_size() == (1280, 900)
    assert _F({"web": {"login_window": {"w": 200, "h": 300}}},
              False).login_window_size() == (1280, 900)


def test_launch_args_use_the_method():
    src = io.open(os.path.join(ROOT, "crawlers", "base.py"),
                  encoding="utf-8").read()
    i = src.index("--window-size")
    assert "login_window_size()" in src[max(0, i - 400):i], \
        "launch_args 必须用 login_window_size()，别再写死尺寸"

class _S(BaseCrawler):
    package = "x"
    use_mobile = True          # 采集走 m 站（ctrip/tuniu 就是这种）

    def __init__(self, surface=None, cfg=None):
        self.config = cfg or {}
        if surface is not None:
            self.login_surface = surface

    def login_url(self):
        return "https://x/"


def test_surface_wins_over_use_mobile():
    """`use_mobile=True` 是**采集**口径；PC 槽位仍要桌面尺寸。

    现场（用户截图）：携程 PC 登录窗是 480×880，passport 桌面页被裁 →
    "排版有问题"。根因就是拿 use_mobile 判端。
    """
    assert _S("pc").login_window_size() == (1280, 900)
    assert _S("h5").login_window_size() == (480, 880)


def test_falls_back_to_use_mobile_without_surface():
    assert _S(None).login_window_size() == (480, 880)   # use_mobile=True
    f = _S(None)
    f.use_mobile = False
    assert f.login_window_size() == (1280, 900)


def test_slot_crawler_stamps_surface():
    """`slot_crawler()` 必须把槽位的端写进 crawler.login_surface。"""
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "core", "login_slots.py"),
        encoding="utf-8").read()
    assert "crawler.login_surface" in src
