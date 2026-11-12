# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1026_mirror_meta_wrap.py
- tests/test_r1511_mirror_label.py
- tests/test_r999_mirror_rail_grid.py

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


# ---- merged from tests/test_r1026_mirror_meta_wrap.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_static_mirror_meta_allows_two_lines():
    with io.StringIO(webui_full_src()) as f:
        src = f.read()
    i = src.index("r1026：原页镜像 390 的班次元信息")
    block = src[i:i + 700]
    assert "#searchview .srx-mrow .m span{white-space:normal!important" in block
    assert "word-break:keep-all!important" in block
    assert "overflow-wrap:normal!important" in block
    assert "text-overflow:clip!important" in block


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p




# ---- merged from tests/test_r1511_mirror_label.py ----

pytest.importorskip("playwright", reason="渲染门禁依赖 playwright")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p






PROBE = r"""
() => {
  const b=document.getElementById('srxMirrorFold');
  const h=document.querySelector('.srx-listhead');
  const rb=b.getBoundingClientRect(), rh=h.getBoundingClientRect();
  const title=document.getElementById('srxListTitle');
  return {
    text:b.textContent.trim(), title:b.title, aria:b.getAttribute('aria-expanded'),
    btnW:+rb.width.toFixed(1), btnH:+rb.height.toFixed(1), right:+rb.right.toFixed(1),
    headScroll:h.scrollWidth, headClient:h.clientWidth, headH:+rh.height.toFixed(1),
    listTitleShown:!!title && title.offsetParent!==null,
    folded:document.getElementById('srxMirror').classList.contains('srx-folded'),
    vw:innerWidth, docDx:document.documentElement.scrollWidth-document.documentElement.clientWidth
  };
}
"""




# ---- merged from tests/test_r999_mirror_rail_grid.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_static_mirror_rail_is_one_scrollable_row():
    with io.StringIO(webui_full_src()) as f:
        src = f.read()
    assert "#searchview .srx-mirror .srx-mrail{display:flex!important;flex-wrap:nowrap!important" in src
    assert "#searchview .srx-mrail-tabs{display:flex;align-items:center;gap:4px;min-width:0;" in src
    assert "mask-image:linear-gradient(90deg,#000 calc(100% - 18px),transparent)" in src
    # 只列有数据渠道的过滤不能丢
    assert "chans.filter(c=>cnt[c]>0||c===ch)" in src




