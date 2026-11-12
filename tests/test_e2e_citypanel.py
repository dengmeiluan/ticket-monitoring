# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1047_citypanel_frozen.py

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


# ---- merged from tests/test_r1047_citypanel_frozen.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_static_abc_outside_scroll_body():
    with io.StringIO(webui_full_src()) as f:
        src = f.read()
    assert '<div id="cpabc" class="cp-abc" aria-label="字母导航"></div>' in src
    i = src.index(".cp-abc{")
    block = src[i:i + 220]
    assert "position:sticky" not in block, block
    assert "flex:0 0 auto" in block, block
    j = src.index("r1047：字母导航从滚动容器里搬出来")
    build = src[j:j + 500]
    assert "abcEl.innerHTML=Ls.map" in build
    assert "h2+='<div class=\"cp-abc\"" not in src


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


