# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1130_wave3_pages_contract.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
import io
from support_webui_src import webui_full_src

import os
import pytest
import sys


# ---- merged from tests/test_r1130_wave3_pages_contract.py ----

pytest.importorskip("playwright",
                    reason="全站页面契约依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None
VIEWS = [
    ("mon", "overview", "概览"), ("mon", "specials", "特价"),
    ("mon", "trend", "走势"), ("mon", "watch", "关注"),
    ("mon", "details", "明细"), ("mon", "health", "健康"),
    ("search", None, "检索"), ("cfg", "login", "登录"),
    ("cfg", "users", "用户"), ("cfg", "globals", "参数"),
]


def test_static_p1_copy_and_scale():
    with io.StringIO(webui_full_src()) as f:
        src = f.read()
    assert "font-size:10.5px" not in src
    assert "font-size:21px" not in src
    assert ">收起</button>" not in src
    assert "部分需重启" in src
    assert "数据库/日志/登录态/内核路径、监听地址、启动即扫需重启" in src


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p




SNAP = r"""() => {
  const vw = innerWidth;
  function vis(e){const c=getComputedStyle(e),r=e.getBoundingClientRect();
    return c.display!=='none'&&c.visibility!=='hidden'&&c.opacity!=='0'&&r.width>2&&r.height>2;}
  const out=[];
  for(const e of document.querySelectorAll('body *')){
    if(!vis(e))continue;const r=e.getBoundingClientRect();
    if(r.right<=vw+2&&r.left>=-2)continue;
    let n=e.parentElement,scroll=false;
    while(n){const nc=getComputedStyle(n);
      if((nc.overflowX==='auto'||nc.overflowX==='scroll')&&n.getBoundingClientRect().width<=vw+2){scroll=true;break}
      n=n.parentElement}
    if(!scroll)out.push({tag:e.tagName,id:e.id,cls:String(e.className).slice(0,30)});
  }
  const cs=[...document.querySelectorAll('button,input,select,a,summary,[role=button]')]
    .filter(e=>{const c=getComputedStyle(e),r=e.getBoundingClientRect();
      return c.display!=='none'&&c.visibility!=='hidden'&&r.width>4&&r.height>4&&r.bottom>0&&r.top<innerHeight});
  const over=[];
  for(let i=0;i<cs.length;i++)for(let j=i+1;j<cs.length;j++){
    const a=cs[i],b=cs[j];if(a.contains(b)||b.contains(a))continue;
    // 镜像轨的折叠钮与胶囊同处 overflow:hidden 的内部横滑轨，胶囊被裁在轨内；
    // rect 相交不代表可见重叠（轨外边界即裁切边界），按真实裁剪排除。
    const ca=String(a.className||''),cb=String(b.className||'');
    // 镜像折叠钮位于内部横滑轨的裁切边界上，rect 相交不代表可见重叠；
    // 其两态同坐标由 r874 专测，这里排除该颗避免重复口径。
    if(ca.includes('srx-foldbtn')||cb.includes('srx-foldbtn'))continue;
    // r1405：≤560 的筛选/矩阵/概览是固定底部动作条，内容从它下面滚过是
    // 移动端常态（#searchview 已留 64px 底衬）；动作条不是浮层，不参与
    // “控件重叠”口径，否则每个滚动位置都会把行与条判成重叠。
    if(a.closest('#srxMobilebar')||b.closest('#srxMobilebar'))continue;
    const ra=a.getBoundingClientRect(),rb=b.getBoundingClientRect();
    const ox=Math.min(ra.right,rb.right)-Math.max(ra.left,rb.left);
    const oy=Math.min(ra.bottom,rb.bottom)-Math.max(ra.top,rb.top);
    if(ox>3&&oy>3)over.push([String(a.className||a.id||a.tagName).slice(0,20),
      String(b.className||b.id||b.tagName).slice(0,20)]);
  }
  const headings=[...document.querySelectorAll('h1,h2,.uhead,.mon-cardhead,.srx-hero,.srx-listhead')].filter(vis).length;
  return {docOver:document.documentElement.scrollWidth-document.documentElement.clientWidth,
    out:out.slice(0,10), over:over.slice(0,10), headings};
}
"""


