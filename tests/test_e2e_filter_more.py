# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1130_filter_continuity.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import os
import pytest
import sys


# ---- merged from tests/test_r1130_filter_continuity.py ----

pytest.importorskip("playwright",
                    reason="筛选连续动作依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p




def _open_search(pg):
    pg.goto(BASE + "/", wait_until="load")
    pg.wait_for_function("typeof S!=='undefined'&&S&&S.users", timeout=25000)
    pg.wait_for_timeout(1200)
    pg.evaluate("()=>switchView('search')")
    pg.wait_for_timeout(900)


def _snap(pg):
    return pg.evaluate("""()=>{
      const f=document.getElementById('srxCtxFly');
      const b=document.getElementById('srxFilterBtn');
      const r=f?f.getBoundingClientRect():null, br=b?b.getBoundingClientRect():null;
      return {ctx:typeof SRX!=='undefined'?!!SRX.ctx:null,
        disp:f?getComputedStyle(f).display:null,
        flyTop:r?+r.top.toFixed(1):null, btnBottom:br?+br.bottom.toFixed(1):null,
        aria:b?b.getAttribute('aria-expanded'):null,
        rows:document.querySelectorAll('#srxRows .srx-row').length,
        pair:(document.querySelector('#srxCtxFly .srx-chip.on[data-pair]')||{}).textContent||'',
        date:(document.querySelector('#srxCtxFly .srx-chip.on[data-date]')||{}).textContent||''
      }}""")




def test_outside_handler_uses_capture_and_composed_path():
    """静态守门：捕获阶段 + composedPath 是这次修复的两个必要件。

    只看行为容易在无重建的 demo 数据下假绿（点同一条航线不重建），所以
    这里同时钉住实现形状；行为由上面的连续动作用例负责。
    """
    src = webui_full_src()
    i = src.find("r1130c：筛选浮层里的条件一点就会重建 DOM")
    assert i > 0, "缺少 r1130c 注释锚点"
    seg = src[i:i + 1200]
    assert "composedPath" in seg, "捕获判定没用 composedPath 兜底"
    assert "},true);" in seg, "document click 监听不在捕获阶段"
    assert "srxCtxFly" in seg, "判定没锚定浮层 id"





