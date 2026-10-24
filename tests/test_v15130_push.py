# -*- coding: utf-8 -*-
"""推送词面单源收口（r230 WE Minor-2）：_near_txt「擦边」前缀字面量
挂 TIER_FULL["near"] 投影。

背景（_scratch/r230_we_push.md）：档位词四方同语言已全挂 _TIER_TABLE
四投影，唯 _near_txt 前缀仍是字面量——档位词改版日该前缀会漂离图例
（LESSONS 十六§3 词面单源律）。行为不变（TIER_FULL["near"]=="擦边"
本态），输出形态钉 test_v15110_push 维持不动。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15130_push.py -q
"""
import inspect

from core import alerter
from core.alerter import TIER_FULL, _near_txt


def test_near_txt_prefix_on_tier_projection():
    body = inspect.getsource(_near_txt)
    assert 'TIER_FULL["near"]' in body, \
        "_near_txt 擦边前缀未挂 TIER_FULL 投影（档位词改版日漂离图例）"


def test_near_txt_output_shape_unchanged():
    """投影重构不动输出：边界契约（≤0.5 显式含界）与普通档词面维持。"""
    assert _near_txt(0.0021) == TIER_FULL["near"] + "不足1%"
    assert _near_txt(0.005) == TIER_FULL["near"] + "不足1%"
    assert _near_txt(0.006) == TIER_FULL["near"] + "1%"
    assert _near_txt(0.09) == TIER_FULL["near"] + "9%"
