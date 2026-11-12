# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1051_matrix_sticky.py
- tests/test_r999_matrix_label_fit.py
- tests/test_r999_matrix_no_loadmore.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
import io
from support_webui_src import webui_full_src

import os
import socket
import subprocess
import sys
import time
import urllib.request


# ---- merged from tests/test_r1051_matrix_sticky.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_static_matrix_scroll_and_sticky_header():
    with io.StringIO(webui_full_src()) as f:
        src = f.read()
    assert "#cfgDimMatrix .dimwrap{max-height:min(50vh,520px);overflow:auto!important" in src
    assert "#cfgDimMatrix .dimtbl thead th{position:sticky;top:0;z-index:3;" in src
    assert "background:var(--card)!important" in src






# ---- merged from tests/test_r999_matrix_label_fit.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_static_matrix_label_rule():
    with io.StringIO(webui_full_src()) as f:
        src = f.read()
    assert "#searchview .srx-mxcard .pn img.bic{display:none!important}" in src
    assert "「去哪儿 App」" in src






# ---- merged from tests/test_r999_matrix_no_loadmore.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_css_has_matrix_more_guard():
    with io.StringIO(webui_full_src()) as f:
        src = f.read()
    assert "const n=SRX.view==='matrix'?0:Math.max(0,rows.length-srxShownRows(rows).length)" in src




