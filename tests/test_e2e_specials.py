# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1053_specials_sources_compact.py
- tests/test_r999_specials_meta_wrap.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
import io
from support_webui_src import webui_full_src

import os
import pytest
import socket
import subprocess
import sys
import time
import urllib.request


# ---- merged from tests/test_r1053_specials_sources_compact.py ----

pytest.importorskip("playwright",
                    reason="窄档/宽档几何依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p










# ---- merged from tests/test_r999_specials_meta_wrap.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_static_specials_meta_rules():
    with io.StringIO(webui_full_src()) as f:
        src = f.read()
    assert "#spMonSum .sep:nth-last-child(2){display:none!important}" in src
    assert "#spMonSum>span:last-child{flex:1 1 100%!important}" in src




