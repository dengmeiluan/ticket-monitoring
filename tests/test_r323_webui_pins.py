# -*- coding: utf-8 -*-
"""r323 半年走势呈现面源码钉（P2-3/P3-1 词面档位）。

- 长窗空态文案随档位（TREND_LAB 单源）——「近 48h」硬编码词禁复活
  （180d 档空态曾宣「近 48h」=档位失实）；
- K线图注在长窗档宣「日K」词（桶长未成词=图例与桶语义脱节）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r323_webui_pins.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui  # noqa: E402


def test_long_window_empty_copy_is_range_aware():
    src = webui.PAGE
    assert ("TREND_LAB[CR.range]||(CR.range==='7d'?'7 天':'48h')") in src
    assert "这里会出现近 48h 的最低价曲线" not in src


def test_dayk_ring_note_word():
    assert "日K=真实航班当日最低价（不含日历价" in webui.PAGE
    assert "日K=行情池当日最低价（含日历价" in webui.PAGE
