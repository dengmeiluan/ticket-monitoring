# -*- coding: utf-8 -*-
"""r288 推送批（_scratch/r288_push_audit.md P3-1 落地）：

- P3-1 告警图挂兜底「各渠道最低」行序非价序：排序键用 platform_mins
  锚池值、展示值用 tops 明细最低（tops 缺席才回落锚池）——两池口径
  不同源时产出「价高者在前」错序（demo 实测携程￥2250 排去哪儿
  ￥2240 前），与总表 PNG/日报兜底的价序不一致。排序键改为「本行
  将展示的值」，行内容零变化只序变。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r288_push.py -q
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import Alerter  # noqa: E402

_LOG = logging.getLogger("r288_push")


def _sec():
    """携程/去哪儿两池口径错位样本：携程锚池价更低（2240<2300）
    但展示明细最低更高（2250>2240）——按锚池排序携程在前=错序。"""
    return [{"date": "2026-10-11",
             "platform_mins": {"ctrip": 2240.0, "qunar": 2300.0},
             "plat_top3": {"ctrip": [
                 {"price": 2250.0, "name": "MU8369",
                  "depTime": "19:55", "arrTime": "01:25"}],
                 "qunar": [
                     {"price": 2240.0, "name": "HO1258",
                      "depTime": "08:30", "arrTime": "13:50"}]}}]


def test_channel_market_sorted_by_display_value():
    """P3-1：行序按展示值（明细最低）升序——¥2240 在 ¥2250 前。"""
    a = Alerter(_LOG, storage=None)
    out = a._channel_market_lines(_sec())
    assert out, out
    assert out.index("￥2240") < out.index("￥2250"), out
