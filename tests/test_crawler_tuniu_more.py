# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r306_tuniu_lite.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import logging
import os
import pytest
import sys

from crawlers import tuniu as _t
from crawlers.tuniu import TuniuCrawler


# ---- merged from tests/test_r306_tuniu_lite.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _crawler():
    return TuniuCrawler(
        {"rate_limit": False, "backoff_seconds": 0}, logging.getLogger("t"))


def test_ladder_pure_thresholds():
    # 未达连败阈值=全预算；达到即降载（1 圈×3 拍）；病理配置取 min
    # 不放大（配置已收口 1 圈×2 拍时降载档不反超）
    assert _t._ladder(0, 5, 10) == (5, 10)
    assert _t._ladder(_t._LADDER_STRIKE - 1, 5, 10) == (5, 10)
    assert _t._ladder(_t._LADDER_STRIKE, 5, 10) == (1, 3)
    assert _t._ladder(_t._LADDER_STRIKE + 95, 5, 10) == (1, 3)
    assert _t._ladder(99, 1, 2) == (1, 2)


def test_fail_streak_enters_lite_and_success_resets():
    c = _crawler()
    polls_seen = []

    def fail_probe(fc, tc, date, polls=None, back_date=""):
        polls_seen.append(polls)
        return False, None, False

    c._one_attempt = fail_probe
    for _ in range(_t._LADDER_STRIKE):
        assert c._hoop("SHA", "HAK", "2026-10-20") is None
    assert c._fail_streak == _t._LADDER_STRIKE
    # 阈值前全预算：每查询 5 圈 × 每圈 10 拍
    assert polls_seen == [10] * (5 * _t._LADDER_STRIKE)
    # 阈值后降载档：单圈 3 拍（连败续期维持降载）
    n = len(polls_seen)
    assert c._hoop("SHA", "HAK", "2026-10-21") is None
    assert polls_seen[n:] == [3]
    assert c._fail_streak == _t._LADDER_STRIKE + 1
    # 任一成功复位全预算（零延迟自愈）
    c._one_attempt = lambda fc, tc, date, polls=None, back_date="": (
        True, {"fareList": []}, False)
    assert c._hoop("SHA", "HAK", "2026-10-22") is not None
    assert c._fail_streak == 0
    polls_seen.clear()
    c._one_attempt = fail_probe
    c._hoop("SHA", "HAK", "2026-10-23")
    assert polls_seen == [10] * 5


def test_lite_zero_delay_recovery_within_round():
    # 降载档内当圈成功即出真价：不因降载漏掉恢复首响应（每圈 3 拍
    # 仍覆盖恢复轮 fareList 完整形态——健康轮首响即收语义不变）
    c = _crawler()
    c._fail_streak = _t._LADDER_STRIKE
    c._one_attempt = lambda fc, tc, date, polls=None, back_date="": (
        True, {"fareList": [{"a": 1}]}, False)
    assert c._hoop("SHA", "HAK", "2026-10-24") == {"fareList": [{"a": 1}]}
    assert c._fail_streak == 0
