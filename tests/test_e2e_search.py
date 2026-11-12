# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1060_search_routes_rail.py
- tests/test_r661_search_side_names.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import os
import pytest
import sys


# ---- merged from tests/test_r1060_search_routes_rail.py ----

pytest.importorskip("playwright",
                    reason="窄档航线轨依赖 playwright（缺库 SKIP 不 ERROR）")

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
  const box=document.getElementById('srxPairs');
  if(!box) return {exists:false};
  const chips=[...box.querySelectorAll('.srx-chip')];
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
    pg.evaluate("()=>switchView('search')")
    pg.wait_for_timeout(2400)






# ---- merged from tests/test_r661_search_side_names.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LATIN = ("app_zhixing", "app-list", "snap-restore", "android-runtime",
         "app-dump", "app-blocker", "app-route", "app-error",
         "android-device")


def _src():
    return webui_full_src()


def test_no_second_channel_name_lookup():
    src = _src()
    assert "(SRX_PLATS[p]||[p])[0]" not in src, (
        "仍有地方用 SRX_PLATS 取渠道名——App 渠道不在那张表里，"
        "会直接打出 app_zhixing；应统一走 platCN(p)")


def test_task_paths_derive_channels_from_data():
    src = _src()
    i = src.index("function srxTaskPaths(lg){")
    seg = src[i:i + 1200]
    assert "SRX_PLAT_ORDER.forEach(p=>{" not in seg, (
        "溯源通路仍按写死的 5 家浏览器渠道遍历，App 渠道的证据永不出现")
    assert "Object.keys((lg&&lg.channels)||{})" in seg, (
        "渠道清单没有按本轮真实数据派生")
    assert "pathCN(x.path" in seg, "溯源通路名没走 pathCN"




