# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_path_select_catalog.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import os
import re
import sys


# ---- merged from tests/test_r1063_path_select_catalog.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return webui_full_src()


def _scope_fill_body() -> str:
    s = _src()
    i = s.index("function stratScopeFill(")
    j = s.find("\nfunction ", i + 10)
    return s[i:j if j > 0 else i + 2000]


def test_path_select_merges_catalog():
    body = _scope_fill_body()
    assert "H.paths" in body, "跑过的通路仍要在列表里（顺序更靠前）"
    assert "STRATPAY.paths" in body, "必须并上全量目录，否则新通路永远选不到"
    assert "_seen" in body, "必须去重，否则同一通路出现两次"
    assert "r1063 T158" in body, "留注释说明为什么这么做"


def test_catalog_field_comes_from_single_source():
    s = _src()
    i = s.index('out["paths"] = [{"id": _k, "cn": _v}')
    seg = s[max(0, i - 400):i + 200]
    assert "from core.channels import PATH_CN" in seg


def test_new_paths_present_in_catalog():
    from core.channels import PATH_CN
    for pid in ("PC·国际", "PC·周历"):
        assert pid in PATH_CN
        assert re.search(r"[\u4e00-\u9fff]", PATH_CN[pid]), \
            "%s 的中文名不能是空的（下拉里直接显示它）" % pid
