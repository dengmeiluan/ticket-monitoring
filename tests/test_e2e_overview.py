# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1057_overview_routes_cap.py
- tests/test_r996_overview_route_fit.py
- tests/test_r999_overview_kpi_grid.py

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


# ---- merged from tests/test_r1057_overview_routes_cap.py ----

pytest.importorskip("playwright",
                    reason="概览裁量依赖 playwright（缺库 SKIP 不 ERROR）")

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
  const box=document.getElementById('monRouteList');
  const cards=[...box.querySelectorAll('article.monroute')];
  const btn=document.getElementById('monRouteMore');
  const br=btn?btn.getBoundingClientRect():null;
  return {n:cards.length,
    visible:cards.filter(c=>c.getBoundingClientRect().height>1).length,
    btnDisp:btn?getComputedStyle(btn).display:'none',
    btnHidden:!!(btn&&btn.hidden),
    txt:btn?(btn.textContent||'').trim():'',
    aria:btn?btn.getAttribute('aria-expanded'):null,
    box:br?[Math.round(br.left),Math.round(br.top+window.scrollY),Math.round(br.width)]:null,
    over:document.documentElement.scrollWidth>innerWidth+1};
})()"""


def _open(pg, w):
    pg.goto(BASE + "/", wait_until="load")
    pg.wait_for_function("typeof S!=='undefined'&&S&&S.users", timeout=25000)
    pg.wait_for_timeout(1600)
    pg.evaluate("()=>switchView('mon')")
    pg.wait_for_timeout(1200)






# ---- merged from tests/test_r996_overview_route_fit.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_css_uses_two_row_mobile_header():
    with io.StringIO(webui_full_src()) as f:
        src = f.read()
    assert 'grid-template-areas:"name acts" "routes routes"' in src
    assert "#montab-overview .uhead>.uroutes" in src






# ---- merged from tests/test_r999_overview_kpi_grid.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_css_scopes_overview_kpi_grid():
    """概览每组 KPI 仍是「两列网格、减少右半空白」，但实现已从
    `grid-template-areas` 换成**显式行列定位 + subgrid**（r1400 前后重构）。

    断言的本意是「桌面上 KPI 用两列排布，数值/说明在右列」，不是某个具体写法，
    所以这里钉列定义与四块的显式列位，别钉死 areas 字符串。
    """
    with io.StringIO(webui_full_src()) as f:
        src = f.read()
    assert "#montab-overview .dgroup .kpi{display:grid;" in src
    i = src.index("#montab-overview .dgroup .kpi{display:grid;")
    rule = src[i:i + 460]
    assert "grid-template-columns:minmax(150px,230px) minmax(0,1fr)" in rule, rule
    # 四块各就各位：标签整行、数值与说明分左右列
    assert ".kpi .lab{grid-column:1/-1" in src
    assert ".kpi .num{grid-column:1;grid-row:2}" in src
    assert ".kpi .muted:not(.fb){grid-column:2;grid-row:2" in src




