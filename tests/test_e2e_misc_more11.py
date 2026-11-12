# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r324_routehead_sync.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import os
import pytest
import sys


# ---- merged from tests/test_r324_routehead_sync.py ----

pytest.importorskip("playwright",
                    reason="行为钉依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = None
BASE = None


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_up(proc):
    import time
    import urllib.request
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(40):
        if proc.poll() is not None:
            return False
        try:
            op.open(BASE + "/api/state", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False






def _to_cfg(page):
    page.goto(BASE + "/")
    page.wait_for_function("typeof S !== 'undefined' && S && S.users")
    page.evaluate("switchView('cfg')")
    page.wait_for_function("typeof CFG !== 'undefined' && CFG && CFG.length")
    page.wait_for_timeout(400)


_ADD = """
(() => {
  addRoute(0);
  return CFG[0].routes.length - 1;   /* 新卡索引 J */
})()
"""

_EDIT = """
((J) => {
  const rl = document.querySelector('.rline[data-rk="0:' + J + '"]');
  const fin = rl.querySelector('input[onchange*="from_name"]');
  const tin = rl.querySelector('input[onchange*="to_name"]');
  fin.value = '北京'; fin.dispatchEvent(new Event('change', {bubbles: true}));
  tin.value = '长沙'; tin.dispatchEvent(new Event('change', {bubbles: true}));
  const head = rl.querySelector('.rhead');
  return {rtcode: head.querySelector('.rtcode').textContent,
          names: head.querySelector('b').textContent,
          modelFrom: CFG[0].routes[J].from,
          modelTo: CFG[0].routes[J].to};
}) """

_THRESH = """
((J) => {
  const rl = document.querySelector('.rline[data-rk="0:' + J + '"]');
  const inp = rl.querySelector('input[onchange*="alert_direct"]');
  inp.value = '1234';
  inp.dispatchEvent(new Event('change', {bubbles: true}));
  return document.querySelector(
    '.rline[data-rk="0:' + J + '"] .rhead .muted').textContent;
}) """

_CLEAN = """
((J) => { CFG[0].routes.splice(J, 1); buildForm(); }) """






def test_source_pins_route_head_sync():
    """源码钉：syncRouteHead 单源 + setRoute 接线 + 摘要单源共用。"""
    src = webui_full_src()
    assert "function syncRouteHead" in src, "头部随行刷新单源应在案"
    assert src.count("syncRouteHead(i,j)") >= 1, "setRoute 应接线"
    assert "_rsum(r)" in src, "头部摘要应走单源（模板与随行同源）"
