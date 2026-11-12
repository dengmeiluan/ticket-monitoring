# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1032_health_evidence_label.py
- tests/test_r1142_health_list_drawer.py
- tests/test_r1211_health_console.py

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


# ---- merged from tests/test_r1032_health_evidence_label.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_static_empty_evidence_is_labelled():
    with io.StringIO(webui_full_src()) as f:
        src = f.read()
    assert "'证据：—'" in src, "空证据行又退回裸「—」"
    # 有证据时仍以「证据：」开头，同行同前缀
    assert "('证据：'+he(c.evidence))" in src


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p




# ---- merged from tests/test_r1142_health_list_drawer.py ----

pytest.importorskip("playwright", reason="渲染门禁依赖 playwright")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p








SNAP = """() => {
  const vis=e=>{const r=e.getBoundingClientRect();return r.width>0.5&&r.height>0.5};
  const rows=[...document.querySelectorAll('#hbody .hrow')].filter(vis);
  const info=rows.map(r=>{
    const cs=getComputedStyle(r), cells=r.querySelector('.hcells');
    const act=r.querySelector('.hrowact'), badge=r.querySelector('.hbadge');
    const hs=r.querySelector('.hsum');
    const det=r.nextElementSibling&&r.nextElementSibling.classList.contains('hcdet')
      ? r.nextElementSibling : null;
    return {h:+r.getBoundingClientRect().height.toFixed(1),
      left:+r.getBoundingClientRect().left.toFixed(1),
      right:+r.getBoundingClientRect().right.toFixed(1),
      bottom:+r.getBoundingClientRect().bottom.toFixed(1),
      cols:cs.gridTemplateColumns.trim().split(/\\s+/).length,
      btns:r.querySelectorAll('[data-hcdetail]').length,
      scope:r.querySelectorAll('.hscope,.hpath,.hslots').length,
      hasDet:!!det, detHidden:det?det.hidden:null,
      cellsW:cells?+cells.getBoundingClientRect().width.toFixed(1):0,
      segs:cells?cells.querySelectorAll('.hseg').length:0,
      cells:cells?cells.querySelectorAll('.hc').length:0,
      btnH:act&&act.querySelector('button')?+act.querySelector('button').getBoundingClientRect().height.toFixed(1):0,
      btnAria:act&&act.querySelector('button')?act.querySelector('button').getAttribute('aria-expanded'):null,
      btnTxt:act&&act.querySelector('button')?act.querySelector('button').textContent:'',
      badgeR:badge?+badge.getBoundingClientRect().right.toFixed(1):null,
      actR:act?+act.getBoundingClientRect().right.toFixed(1):null,
      hsum:hs?hs.innerText:''};
  });
  const f=document.getElementById('hpaceFold'), sum=f.querySelector('summary');
  const push=document.getElementById('pushhl');
  return {rows:info, n:info.length,
    fold:{open:f.open,h:+f.getBoundingClientRect().height.toFixed(1),
          sumH:+sum.getBoundingClientRect().height.toFixed(1)},
    pushAfter:!!(f.compareDocumentPosition(push)&Node.DOCUMENT_POSITION_FOLLOWING),
    noscopes:document.getElementById('hbody').classList.contains('noscopes'),
    over:document.documentElement.scrollWidth-document.documentElement.clientWidth,
    hasDrawer:!!document.getElementById('hcDrawer')};
}"""


def snap(page):
    return page.evaluate(SNAP)


def detail(page):
    return page.evaluate(
        """() => {const p=document.querySelector('#hbody .hcdet:not([hidden])');
          if(!p)return {hidden:true,
            focusIsBtn:!!(document.activeElement&&document.activeElement.matches
              &&document.activeElement.matches('#hbody [data-hcdetail]'))};
          const r=p.getBoundingClientRect();
          const b=document.querySelector('#hbody [data-hcdetail][aria-expanded="true"]');
          return {hidden:false,w:+r.width.toFixed(1),h:+r.height.toFixed(1),
            left:+r.left.toFixed(1),top:+r.top.toFixed(1),
            sections:p.querySelectorAll('.hcd-sec').length,
            scope:!!p.querySelector('.hscope'),path:!!p.querySelector('.hpath'),
            slots:!!p.querySelector('.hslots'),
            fallback:/无分域\\/通路样本/.test(p.innerText),
            acts:p.querySelectorAll('.hcd-acts button').length,
            focusInPanel:p.contains(document.activeElement),
            focusIsBtn:!!(b&&document.activeElement===b),
            bodyOverflow:getComputedStyle(document.body).overflow,
            mask:!!document.querySelector('.hcmask')};}"""
    )












# ---- merged from tests/test_r1211_health_console.py ----

pytest.importorskip("playwright", reason="渲染门禁依赖 playwright")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p






def _open_health(pg):
    pg.goto(BASE + "/", wait_until="load")
    pg.wait_for_function("typeof S==='object'&&S&&S.users", timeout=25000)
    pg.wait_for_timeout(700)
    pg.evaluate("()=>{switchView('mon');showMonTab('health')}")
    pg.wait_for_function(
        "()=>document.querySelectorAll('#hbody .hrow').length>=10", timeout=20000)
    pg.wait_for_timeout(500)






