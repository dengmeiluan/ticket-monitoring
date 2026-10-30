# -*- coding: utf-8 -*-
"""r627（行为判据）：无入口渠道即使写进配置，也不能再出现在可用名单里。

（删掉过一条「在测试里自己再算一遍过滤」的假判据——它不检验真实代码。）


前一版守卫只查字符串（`_warmable()` 出现过），把白名单改回写死五家照样全绿
—— 典型的**空转绿灯**。这里改成真判据：从 webui.py 里取出回读表达式，
在 Python 侧按真实 REGISTRY 求值，断言 `ctrip` 被过滤且出现在 ignored 里。

负控：删掉 `if x in _warmable()` 这段过滤 → 本测试红。
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import webui  # noqa: E402


def _readback_block():
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                newline="").read()
    i = w.index('"warmup_platforms": ", ".join(')
    j = w.index('"warmable": list(_warmable()),', i)
    return w[i:j + len('"warmable": list(_warmable()),')]


def test_readback_filters_and_reports_by_real_entries():
    blk = _readback_block()
    # 结构判据：过滤条件必须绑定 _warmable()，而不是写死的五家名单
    assert "if x in _warmable()" in blk, (
        "回读没有按真实入口过滤（写成死名单就会让 ctrip 混进可用列表）：\n%s" % blk)
    assert re.search(r"x not in _warmable\(\)", blk), (
        "ignored 列表没有按真实入口算：\n%s" % blk)


def test_warmable_matches_registry_warmup_url():
    from crawlers import REGISTRY
    real = tuple(sorted(k for k, cls in REGISTRY.items()
                        if str(getattr(cls, "warmup_url", "") or "").strip()))
    assert webui._warmable() == real, (
        "可预热集合与真实入口不一致：%s vs %s"
        % (webui._warmable(), real))
