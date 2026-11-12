# -*- coding: utf-8 -*-
"""r267 推送落地案（调研 _scratch/r267_push.md P3-1）：

_channel_ops_lines「本轮无数据渠道」降级档引用行前缀未入量纲——
`\\n\\n> ` + _fit_line(names)（默认 limit=40）产出「> 」+40 半角本体
= 42 半角超宽渲染行（守卫族 P2-1/P1-1 同病漏网残留：前缀在守卫点
之外拼上）。修法：消费点总预算扣减（limit=40-_dw("> ")），地板档
随限收紧恒达标（"(截)" 半角括号 _dw 实值 4：16×2+4=36 本体，
+" >"前缀 2=38=limit 恰满）。可达性窄（需自定义平台键且 legacy
digest 路径）故 P3，但守卫链纪律逐档对账不容豁免。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r267_push.py -q
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import _dw, _fit_line  # noqa: E402


def _src():
    return open("core/alerter.py", encoding="utf-8").read()


def test_refline_prefix_in_budget():
    src = _src()
    # 降级档：引用行前缀并入量纲（消费点总预算扣减，LESSONS 十九§2）
    assert re.search(r'_fit_line\(\s*names,\s*limit=40 - _dw\("> "\)', src), \
        "引用行前缀未并入量纲（> +40 半角本体=42 超宽渲染行）"
    # 地板档随限收紧：names[:16]+"(截)"=36 本体，渲染行=2+36=38 恰满
    assert 'fallbacks=[names[:16] + "(截)"]' in src, \
        "地板档未随限收紧（末档超预算=恒达标律破口）"


def test_budget_math():
    # 数学锚：前缀宽 2；收紧后地板档本体 36（"(截)" 半角括号 _dw 实值 4：
    # 16×2+4=36），整行 38=limit 恰满
    assert _dw("> ") == 2
    fb = "去哪儿、携程、飞猪、同程"[:16] + "(截)"
    assert _dw(fb) <= 38, "地板档本体超 38（整行将破 limit）"
    # 守卫行为：40 半角本体在 limit=38 下降级、38 地板达标
    wide = "站" * 20  # 40 半角
    got = _fit_line(wide, limit=38, fallbacks=[fb])
    assert _dw(got) <= 38, got
