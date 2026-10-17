# -*- coding: utf-8 -*-
"""r306 数据层：tuniu 连续全败降载档。

静默空响应形态（无 179991 字面、无 fareList、blocked=False）绕过
风控判据后，5 圈×10 拍阶梯对每个日期空转 ~110s、每轮 ~7.3min（观测
实证：轮距拉长主因）。连续 _LADDER_STRIKE 个查询全败进入降载档
（1 圈×3 拍），任一成功复位全预算——降载档每轮仍探测，恢复零延迟
自愈（优于维护锁存的重启重探），对风控端点更礼貌（LESSONS 一§1：
行为风控停手换路径，重试只会加深）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r306_tuniu_lite.py
"""
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers import tuniu as _t  # noqa: E402
from crawlers.tuniu import TuniuCrawler  # noqa: E402


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

    def fail_probe(fc, tc, date, polls=None):
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
    c._one_attempt = lambda fc, tc, date, polls=None: (
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
    c._one_attempt = lambda fc, tc, date, polls=None: (
        True, {"fareList": [{"a": 1}]}, False)
    assert c._hoop("SHA", "HAK", "2026-10-24") == {"fareList": [{"a": 1}]}
    assert c._fail_streak == 0
