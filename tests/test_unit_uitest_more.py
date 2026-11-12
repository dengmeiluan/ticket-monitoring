# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_v15127_uitest_abort.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import os
import sys


# ---- merged from tests/test_v15127_uitest_abort.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return open(os.path.join(_ROOT, "tools", "uitest.py"),
                encoding="utf-8").read()


def test_abort_flag_set_in_except():
    src = _src()
    assert "_aborted = False" in src, "中断标志未初始化"
    # except 分支必须置位（缩进锚定：8 空格体=main 内 except）
    assert "        _aborted = True" in src, "except 未置中断标志"


def test_abort_participates_in_exit_code():
    src = _src()
    assert "1 if (_aborted or bad or errors) else 0" in src, \
        "中断标志不参与退出码=中断假绿"
