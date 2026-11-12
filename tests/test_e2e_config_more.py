# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1068_cfg_globals_fold.py
- tests/test_r999_cfg_login_grid.py
- tests/test_r999_cfg_users_actions.py
- tests/test_r999_cfg_users_toolbar.py

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


# ---- merged from tests/test_r1068_cfg_globals_fold.py ----

pytest.importorskip("playwright",
                    reason="配置分区折叠依赖 playwright（缺库 SKIP 不 ERROR）")

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
  const root = document.getElementById('cfgglobals');
  const panel = document.getElementById('panel-globals');
  if (!root) return {exists: false};
  const secs = [...root.querySelectorAll('.subsec[data-cfgsec]')];
  const rows = secs.map(s => {
    const b = s.querySelector('.secfold');
    const grid = s.nextElementSibling;
    const r = grid ? grid.getBoundingClientRect() : {height: 0};
    return {t: (s.textContent || '').trim().slice(0, 12),
            folded: s.classList.contains('folded'),
            gridH: Math.round(r.height),
            btn: b ? b.textContent.trim() : null,
            btnDisp: b ? getComputedStyle(b).display : null,
            aria: b ? b.getAttribute('aria-expanded') : null};
  });
  return {exists: true, n: secs.length, rows,
          panelH: Math.round(panel.getBoundingClientRect().height),
          pageOver: document.documentElement.scrollWidth - innerWidth};
})()"""


def _open(pg):
    pg.goto(BASE + "/", wait_until="load")
    pg.wait_for_function("typeof S!=='undefined'&&S&&S.users", timeout=25000)
    pg.wait_for_timeout(1400)
    pg.evaluate("()=>{switchView('cfg');showCfgPanel('globals')}")
    pg.wait_for_timeout(1800)








# ---- merged from tests/test_r999_cfg_login_grid.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_css_has_two_column_login_grid():
    with io.StringIO(webui_full_src()) as f:
        src = f.read()
    assert "#loginRows .lggrid{grid-template-columns:repeat(2,minmax(0,1fr))!important" in src






# ---- merged from tests/test_r999_cfg_users_actions.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_static_users_actions_grid_rule():
    with io.StringIO(webui_full_src()) as f:
        src = f.read()
    assert "#cfgview .cfgtoolbar-act{width:100%!important;display:grid!important" in src
    assert "grid-template-columns:repeat(3,minmax(0,1fr))!important" in src[src.index(
        "#cfgview .cfgtoolbar-act{width:100%!important"):][:300]
    assert "#cfgview .cfgtoolbar-act .btn2{width:100%!important" in src






# ---- merged from tests/test_r999_cfg_users_toolbar.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_static_users_toolbar_separator_rule():
    with io.StringIO(webui_full_src()) as f:
        src = f.read()
    assert "#cfgview .cfgtoolbar .cbsp{display:none!important}" in src




