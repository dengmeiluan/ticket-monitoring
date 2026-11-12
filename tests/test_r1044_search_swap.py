# -*- coding: utf-8 -*-
"""r1044：检索探针去掉「出发/到达/日期」标签，改为可点击的换向钮。"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_static_swap_markup_and_handler():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
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
