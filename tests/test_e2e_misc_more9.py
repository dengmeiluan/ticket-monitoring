# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r324_cfghead_sync.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import os
import pytest
import sys


# ---- merged from tests/test_r324_cfghead_sync.py ----

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


def _restore(page, snapshot):
    """模型快照还原 + buildForm 全量重建（测试收尾态复位）。"""
    page.evaluate("""((snap) => {
      CFG.length = 0;
      for (const u of snap.users) CFG.push(JSON.parse(JSON.stringify(u)));
      GLB = JSON.parse(JSON.stringify(snap.glb));
      buildForm();
    })""", snapshot)


_SNAP = """
(() => ({glb: JSON.parse(JSON.stringify(GLB)),
        users: JSON.parse(JSON.stringify(CFG))}))()
"""


def _pill(head, idx):
    return f"""(() => {{
      const p = document.querySelectorAll(
        '#cfgform .ucard')[0].querySelectorAll('.uhead2 .upill')[{idx}];
      return {{t: p.textContent.trim(), ok: p.classList.contains('ok')}};
    }})()"""




















def test_source_pins_userhead_sync():
    src = webui_full_src()
    assert "function syncUserHead" in src, "卡头刷新单源应在案"
    assert src.count("syncUserHead(i)") >= 9, (
        "九写点（W1-W3/W4-W7/W11/W15）应接线")
    assert "syncRouteHead(i,j)" in src, "航线头单源应在案"
    qi = src.find("function quickDep")
    assert qi >= 0 and "syncRouteHead(i,j)" in src[qi:qi + 400], (
        "quickDep 应接航线头随行")
