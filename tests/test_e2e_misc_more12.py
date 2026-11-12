# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r796_scroll_to_bottom_loads_all.py
- tests/test_r832_trigger_not_flanked.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import json
import os
import pytest
import socket
import subprocess
import sys
import time
import urllib.request


# ---- merged from tests/test_r796_scroll_to_bottom_loads_all.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p




def _open_details(pg, base):
    pg.goto(base + "/")
    pg.wait_for_function("typeof S!=='undefined' && S && S.users", timeout=25000)
    pg.wait_for_timeout(700)
    pg.evaluate("switchView('mon')")
    pg.wait_for_timeout(900)
    pg.evaluate("showMonTab('details')")
    pg.wait_for_timeout(900)






# ---- merged from tests/test_r832_trigger_not_flanked.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = _free_port()
BASE = "http://127.0.0.1:%d" % PORT

JS = r"""() => {
  const vis = e => { const s=getComputedStyle(e); const r=e.getBoundingClientRect();
    return r.width>1 && r.height>1 && s.display!=='none' && s.visibility!=='hidden'; };
  const tag = e => e.tagName.toLowerCase()+(e.id?'#'+e.id:'')+
    ((typeof e.className==='string'&&e.className.trim())?'.'+e.className.trim().split(/\s+/)[0]:'');
  const band=document.getElementById('srxBand');
  const hero=document.getElementById('srxOvHero');
  if(!band||!hero) return {err:'missing'};
  const h=band.querySelector('.srx-band-h');
  const hr=hero.getBoundingClientRect();
  const kids=[...h.children].filter(vis);
  const leftSameRow = kids.filter(e=>{
    if(e===hero) return false;
    const r=e.getBoundingClientRect();
    const sameRow=Math.abs((r.top+r.height/2)-(hr.top+hr.height/2)) < hr.height*0.6;
    const hasText=(e.textContent||'').trim().length>0;
    return sameRow && r.right <= hr.left+1 && (hasText || r.width>4);
  }).map(tag);
  return {hero:[+hr.left.toFixed(1),+hr.top.toFixed(1)], leftSameRow:leftSameRow,
    collapsed:document.getElementById('searchview').classList.contains('srx-ov-collapsed')};
}"""








def test_band_header_is_grid():
    src = webui_full_src()
    assert "#searchview #srxBand .srx-band-h{\n display:grid;" in src or \
           "#searchview #srxBand .srx-band-h{display:grid;grid-template-columns:auto 1fr auto" in src, (
        "标题行不是 grid 两行布局——flex 下无法保证「标题+触发器」独占第一行")
    assert "grid-area:1/3/2/4" in src, "触发器没有被显式放到第 1 行第 3 列"
