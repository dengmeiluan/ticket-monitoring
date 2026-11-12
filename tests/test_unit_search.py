# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1044_search_swap.py
- tests/test_r739_search_round_trip_hint.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request


# ---- merged from tests/test_r1044_search_swap.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_static_swap_markup_and_handler():
    with io.StringIO(webui_full_src()) as f:
        src = f.read()
    i = src.index('<div class="srx-qrow">')
    block = src[i:i + 4200]
    assert 'class="srx-swap"' in block
    assert 'onclick="srxSwapEnds(this)"' in block
    assert 'aria-label="交换出发地和目的地"' in block
    assert '<span class="srx-flab">出发</span>' not in block
    assert '<span class="srx-flab">到达</span>' not in block
    assert '<span class="srx-flab">日期</span>' not in block
    j = src.index("function srxSwapEnds(btn)")
    fn = src[j:j + 900]
    assert "put(a,bv,bn,bc);put(b,av,an,ac)" in fn
    assert "el.dataset.code" in fn


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


MEASURE = """()=>{
  const R=e=>{const r=e.getBoundingClientRect();return {l:+r.left.toFixed(1),t:+r.top.toFixed(1),
    r:+r.right.toFixed(1),b:+r.bottom.toFixed(1),w:+r.width.toFixed(1),h:+r.height.toFixed(1)}};
  const a=document.getElementById('srxFrom'),b=document.getElementById('srxTo'),s=document.getElementById('srxSwap');
  return {labels:[...document.querySelectorAll('#searchview .srx-probe .srx-flab')].map(e=>e.textContent.trim()),
    row:R(document.querySelector('#searchview .srx-probe .srx-qrow')),
    from:R(a.closest('.srx-citybox')),swap:R(s),to:R(b.closest('.srx-citybox')),
    date:R(document.getElementById('srxDate')),go:R(document.getElementById('srxGo')),
    pageOF:document.documentElement.scrollWidth-innerWidth};
}"""

SWAP = """()=>{
  const a=document.getElementById('srxFrom'),b=document.getElementById('srxTo');
  a.value='上海';a.dataset.name='上海';a.dataset.code='SHA';
  b.value='曼谷';b.dataset.name='曼谷';b.dataset.code='BKK';
  document.getElementById('srxSwap').click();
  return {values:[a.value,b.value],names:[a.dataset.name,b.dataset.name],
    codes:[a.dataset.code,b.dataset.code],calc:[srxCityCode(a),srxCityCode(b)]};
}"""


# ---- merged from tests/test_r739_search_round_trip_hint.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _src():
    return webui_full_src()


def _fn_body(src, name):
    i = src.index("function %s(" % name)
    # 花括号配平取函数体
    j = src.index("{", i)
    depth, k = 0, j
    while k < len(src):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[i:k + 1]
        k += 1
    return src[i:]


def test_helper_lists_only_channels_without_round_trip():
    src = _src()
    assert "function _rtNoSupportNames(" in src, (
        "没有 _rtNoSupportNames：检索页无法说明哪些渠道没有往返")
    body = _fn_body(src, "_rtNoSupportNames")
    # 必须按 round_trip 单元格过滤，且把 y 排除
    assert "round_trip" in body, body[:400]
    assert "DIMS_DATA" in body, "没有从能力矩阵取值（会写死名单）"


def test_chip_title_uses_the_helper():
    """可点击的「往返票」chip（含 toggleRT 的那个）要带上不支持名单。

    注意别匹配到只读标签 `<span class="rrt" title="往返票：价格=…">`
    ——那是展示用的角标，不承担"哪些渠道没有"的解释职责。
    """
    src = _src()
    hits = [m.group(0) for m in re.finditer(r'title="往返票[^"]*"[^>]*'
                                            r'onclick="toggleRT\(', src)]
    assert hits, "找不到可点击的往返票 chip"
    seg = hits[0]
    assert "_rtNoSupportNames(" in seg, (
        "往返票 chip 的说明没有引用不支持名单：%s" % seg)


def test_helper_is_pure_and_handles_missing_data():
    """矩阵没加载时不能抛错，也不能凭空列出渠道。"""
    src = _src()
    body = _fn_body(src, "_rtNoSupportNames")
    assert "DIMS_DATA" in body
    # 必须有空值保护（返回空串或空数组）
    assert re.search(r"if\s*\(!\s*DIMS_DATA", body) or "||" in body, body


def test_every_channel_name_comes_from_matrix():
    """名字来自 API 的 name 字段（CHANNEL_CN 单源），不写死中文。"""
    body = _fn_body(_src(), "_rtNoSupportNames")
    assert ".name" in body, "渠道名没有取矩阵的 name 字段（会与单源脱节）"
