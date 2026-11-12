# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1061_watch_channel_rail.py
- tests/test_r996_watch_row_mobile.py

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


# ---- merged from tests/test_r1061_watch_channel_rail.py ----

pytest.importorskip("playwright", reason="窄档渠道带依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p




SNAP = """(() => {
  const box=document.getElementById('wsChanStrip');
  if(!box) return {exists:false};
  const chips=[...box.querySelectorAll('.ws-ch')];
  const cs=getComputedStyle(box);
  const rr=box.getBoundingClientRect();
  const first=chips[0]?chips[0].getBoundingClientRect():null;
  const before={scrollW:box.scrollWidth,clientW:box.clientWidth,
    rows:new Set(chips.map(c=>Math.round(c.getBoundingClientRect().top))).size,
    h:Math.round(rr.height),wrap:cs.flexWrap,overflowX:cs.overflowX,
    mask:(cs.maskImage||cs.webkitMaskImage||'none')!=='none',
    boxL:Math.round(rr.left),boxR:Math.round(rr.right),
    firstL:first?Math.round(first.left):null,
    clipped:chips.filter(c=>c.scrollWidth>c.clientWidth+1).length,
    labels:chips.map(c=>(c.textContent||'').trim())};
  box.scrollLeft=box.scrollWidth;
  const last=chips.length?chips[chips.length-1].getBoundingClientRect():null;
  const lastVisible=last?(last.right<=Math.round(rr.right)+1&&last.left>=Math.round(rr.left)-1):false;
  box.scrollLeft=0;
  return {exists:true,n:chips.length,before,lastVisible,
    scrollable:before.scrollW>before.clientW+1,
    over:document.documentElement.scrollWidth>innerWidth+1};
})()"""


def _open(pg):
    pg.goto(BASE + "/", wait_until="load")
    pg.wait_for_function("typeof S!=='undefined'&&S&&S.users", timeout=25000)
    pg.wait_for_timeout(1500)
    pg.evaluate("()=>{switchView('mon');showMonTab('watch')}")
    pg.wait_for_timeout(2200)






# ---- merged from tests/test_r996_watch_row_mobile.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_css_keeps_two_row_mobile_contract():
    with io.StringIO(webui_full_src()) as f:
        src = f.read()
    assert 'grid-template-areas:"id id state" "price act act"' in src
    # App 渠道入口跨面统一为两端动作行，不再回落到 4 列矩阵的单格
    assert ".chband-approw{display:flex" in src
    assert "chband-approw" in src




