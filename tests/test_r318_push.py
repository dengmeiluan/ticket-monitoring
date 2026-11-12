# -*- coding: utf-8 -*-
"""r318 推送落地钉（_scratch/worker_r318_push.md 审校消化）：

P3-1 hits tail 链接词「打开{渠道}」→「{渠道}」裸词：剥渠道名保链
接档在 5 位差额形态（线 ≥￥10000）实算 41/40 恰超 1 半角，`_fit_line`
跳档到保名弃链档——跳转动作件在 5 位线达标轮整体缺席。裸词省 4 半角
（41→37）恒落位，钉钉 markdown 链接蓝字可点语义不变。审校报告变异
轮已实证修前行为（RED 等效），本钉锁修后形态：源码钉（裸词在场+
「打开」禁复活）+ 行为复算钉（最坏 5 位差额行串经 _fit_line 链接档
在场）。

P3-2（_ops_fallbacks 5 渠道缺失形态 `(截)` 留痕档 41/40）备案不修：
section 存在 ⇒ 至少 1 渠道有数据行，5 渠道全缺生产不可达（4 缺失
形态 `(截)` 档 39/40 存活已复算）——守卫链下从未渲染的形态不修
（LESSONS 判例：死改动收口=备案等价论证）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r318_push.py -q
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import _disp_dw, _fit_line  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_jump_word_bare_platform_name():
    """源码钉：链接词=渠道名裸词（multi+legacy 两处同批）；「打开」
    前缀形态禁复活。"""
    src = Path(os.path.join(_ROOT, "core", "alerter.py")).read_text(
        encoding="utf-8")
    assert "jump = f\"[{plat_cn}]({_jump_url})\"" in src, "multi 版链接词漂移"
    assert "jump = f\"[{plat_cn}]({_jump})\"" in src, "legacy 版链接词漂移"
    assert "[打开{plat_cn}]" not in src, "「打开」前缀形态回潮"


def test_five_digit_spread_keeps_jump_link():
    """行为复算钉：5 位差额最坏形态（rd 全形+5 位线 low）下，剥名
    保链档必须真实落位（修前 41/40 恰超被跳档、链接缺席）。"""
    rd = "SHA→URC 10/16"
    low = "低￥97889"
    jump = "[去哪儿](https://flight.qunar.com/view/xyz)"
    tail = _fit_line(
        f"> {rd} · 去哪儿 · {low} · {jump}",
        fallbacks=[f"> {rd} · {low} · {jump}",
                   f"> {rd} · 去哪儿 · {low}",
                   f"> {rd} · {low}"])
    assert "](http" in tail, tail   # 链接动作件在场
    assert _disp_dw(tail) <= 40, (tail, _disp_dw(tail))
