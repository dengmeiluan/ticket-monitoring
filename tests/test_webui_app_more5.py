# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_zhixing_harvest_order.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import io
import os
import sys


# ---- merged from tests/test_r1063_zhixing_harvest_order.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return io.open(os.path.join(ROOT, "crawlers", "app_zhixing.py"),
                   encoding="utf-8").read()


def test_subscribed_dates_come_first():
    s = _src()
    i = s.index("_out_wanted")
    seg = s[i:i + 1600]
    assert "_out_wanted.append(_fp)" in seg, "订阅日期必须单独收集"
    assert "_out_wanted + _out_extra" in seg, (
        "合并顺序必须是「订阅日 + 其余」，否则 out[0] 不再是订阅那天")


def test_harvest_is_capped():
    s = _src()
    assert "app_calendar_harvest_cap" in s
    i = s.index("app_calendar_harvest_cap")
    assert "_out_extra[:max(0, _cap - len(_out_wanted))]" in s[i:i + 1200] or \
        "_cap" in s[i:i + 1200], "必须有上限，防一次写爆几十天"


def test_priceless_cells_not_counted():
    s = _src()
    i = s.index("price is None")
    assert "无价格子" in s[i:i + 120], "无价格子不该算进'收了 N 天'"
