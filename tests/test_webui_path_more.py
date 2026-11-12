# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_path_elapsed.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import io
import os
import sys


# ---- merged from tests/test_r1063_path_elapsed.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(p):
    return io.open(os.path.join(ROOT, p), encoding="utf-8").read()


def test_column_and_insert():
    s = _src("core/storage.py")
    assert "elapsed_ms INTEGER NOT NULL DEFAULT 0" in s, "缺列定义"
    assert '"http_status,rows,note,evidence_level,attempt_id,elapsed_ms)' in s, \
        "INSERT 必须带 elapsed_ms"
    assert "int(ms or 0)))" in s, "参数要写入"


def test_callers_pass_ms():
    m = _src("main.py")
    assert m.count('ms=int(rec.get("ms") or 0)') >= 1
    assert m.count('ms=int(_rec.get("ms") or 0)') >= 1


def test_path_note_fallback_and_start_marker():
    b = _src("crawlers/base.py")
    assert "_ms_fallback" in b or "耗时兜底" in b, "缺兜底逻辑"
    i = b.index("def path_reset")
    assert "_ms_prev" in b[i:i + 600], "path_reset 必须打起点，否则首条记账为 0"


def test_docstring_separates_from_cross_channel_trap():
    """注释里必须写清：同实例内部的间隔 **不等于** 今天踩过的"跨渠道时间差"。"""
    b = _src("crawlers/base.py")
    i = b.index("def path_note")          # 锚在 path_note 里，别命中 path_reset 的注释
    seg = b[i:i + 2600]
    assert "耗时兜底" in seg, "path_note 里应有耗时兜底"
    assert "跨渠道" in seg or "别的通路" in seg, "要把陷阱写清楚，避免后人重犯"
