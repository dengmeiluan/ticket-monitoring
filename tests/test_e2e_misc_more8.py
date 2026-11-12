# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r324_airline_chips.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import os
import pytest
import sys


# ---- merged from tests/test_r324_airline_chips.py ----

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






_SYNTH = """
(() => {
  const u = S.users[U];
  const bak = u.flights;
  const proto = JSON.parse(JSON.stringify(bak[0]));
  const mk = (ov) => Object.assign(JSON.parse(JSON.stringify(proto)), ov);
  u.flights = [
    mk({name: '吉祥HO100', code: 'HO100', price: 900,
        airlineCode: 'HO'}),
    mk({name: '吉祥HO101', code: 'HO101', price: 910,
        airlineCode: 'HO'}),
    mk({name: '吉祥HO102', code: 'HO102', price: 920,
        airlineCode: 'HO'}),
    mk({name: '吉祥航HO200', code: 'HO200', price: 930,
        airlineCode: 'HO'}),
    mk({name: '东方航空MU111', code: 'MU111', price: 940,
        airlineCode: 'MU/8L'}),
    mk({name: '东方航空MU222', code: 'MU222', price: 950,
        airlineCode: 'MU'}),
    mk({name: '春秋航空9C888', code: '9C888', price: 960,
        airlineCode: ''}),
  ];
  FLT.airlines.clear();
  resetFlt();
  buildAttrChips();
  table();
  return {n: u.flights.length};
})()
"""

_RESTORE = """
(() => {
  const u = S.users[U];
  u.flights = %BAK%;
  FLT.airlines.clear();
  resetFlt();
  buildAttrChips();
  table();
})()
"""


def _to_details(page):
    page.goto(BASE + "/")
    page.wait_for_function("typeof S !== 'undefined' && S && S.users")
    page.evaluate("showMonTab('details');table();"
                  "const fb=document.querySelector('.fbar');"
                  "if(fb&&getComputedStyle(fb).display==='none')togFlt();")
    page.wait_for_timeout(600)


def _with_synth(page, todo):
    """快照还原三件套：换装合成行 → 执行断言 → 无条件还原。"""
    page.evaluate("window.__r324bak = S.users[U].flights")
    page.evaluate(_SYNTH)
    try:
        return page.evaluate(todo)
    finally:
        page.evaluate(
            _RESTORE.replace("%BAK%", "window.__r324bak"))
        page.evaluate("delete window.__r324bak")












def test_source_pins_carrier_code_aggregation():
    """源码钉：码键单源 + 谓词消费 + 旧词面键聚合退役。"""
    src = webui_full_src()
    assert "function carrierKeyOf" in src, "码键单源函数应在案"
    assert "FLT.airlines.has(carrierKeyOf(f))" in src, "谓词应消费码键"
    assert "new Set(u.flights.map(carrierOf))" not in src, (
        "旧词面键聚合应退役")
    assert "function carrierOf(" not in src, "旧词面派生单源应退役"
    assert 'class="frow attrgrid"' in src and \
        src.count('id="attrchips"') == 1, "r343 属性筛选横滚分组应在案"
    assert ".attrgrid .agrp .chips-wrap{" in src, \
        "单行横滚容器样式应在案"
