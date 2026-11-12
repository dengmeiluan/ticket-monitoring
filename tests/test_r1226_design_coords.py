# -*- coding: utf-8 -*-
"""r1226：App 渠道 18 处写死坐标必须走"设计基准 → 设备像素"换算。

现场：模拟器实际 **1260×2800**，而常量按 **900×1600** 写（x≤800 / y≤1400）。
`dev.tap/swipe` 只在 `self.design` 被设置时才换算，而 `runtime` 在没显式配置
`android.display.design` 时会把换算关掉（UI 树坐标不能乘）——于是这些常量
直接打到错误像素上。修法：这些调用点改用 `tap_design/swipe_design`（永远按
当前真实分辨率换算），UI 树路径一行不动。

本文件守：换算正确、基准分辨率下等价、以及"不许再出现裸坐标"。
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.android.device import AdbDevice  # noqa: E402

APP_FILES = ["crawlers/app_qunar.py", "crawlers/app_tongcheng.py",
             "crawlers/app_ctrip.py", "crawlers/app_zhixing_nav.py"]


class FakeDev(AdbDevice):
    """只记录 input 命令，不碰真设备。"""

    def __init__(self, size):
        self._size = size
        self.calls = []
        self.design = None
        self._size_cache = None

    def window_size(self):
        return self._size

    def _sh(self, *args):
        self.calls.append(args)
        return "ok"


def test_tap_design_scales_from_basis():
    d = FakeDev((1260, 2800))
    assert d.tap_design(450, 420) is True
    assert d.calls[-1] == ("shell", "input", "tap", "630", "735"), d.calls[-1]


def test_swipe_design_scales_both_points_and_keeps_duration():
    d = FakeDev((1260, 2800))
    assert d.swipe_design(800, 700, 800, 300, 400) is True
    assert d.calls[-1] == ("shell", "input", "swipe", "1120", "1225",
                           "1120", "525", "400"), d.calls[-1]


def test_same_scale_when_device_matches_basis():
    """基准分辨率下必须逐位相等——否则老设备上的行为会被改坏。"""
    d = FakeDev((900, 1600))
    d.tap_design(450, 420)
    assert d.calls[-1] == ("shell", "input", "tap", "450", "420"), d.calls[-1]


def test_unknown_size_is_safe():
    d = FakeDev((0, 0))
    d.tap_design(450, 420)
    assert d.calls[-1] == ("shell", "input", "tap", "450", "420"), "读不到尺寸时应原样下发"


def test_plain_tap_still_unscaled_when_design_off():
    """负控：普通 `tap()`（设备坐标，UI 树路径）不许被换算。"""
    d = FakeDev((1260, 2800))
    d.tap(450, 420)
    assert d.calls[-1] == ("shell", "input", "tap", "450", "420"), d.calls[-1]


def test_no_bare_hardcoded_coordinates_left():
    """门禁：这 4 个文件里不许再有 `dev.tap(<int>,<int>)` / `dev.swipe(<int>,…)`。"""
    pat_tap = re.compile(r"\.tap\(\s*\d+\s*,\s*\d+\s*\)")
    pat_swipe = re.compile(r"\.swipe\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*\d+")
    bad = []
    for f in APP_FILES:
        s = io.open(os.path.join(ROOT, f), encoding="utf-8").read()
        for m in pat_tap.finditer(s):
            bad.append((f, m.group(0)))
        for m in pat_swipe.finditer(s):
            bad.append((f, m.group(0)))
    assert not bad, "还有写死坐标没换算：%s" % bad[:5]
