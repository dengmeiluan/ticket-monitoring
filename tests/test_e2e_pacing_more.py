# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1510_pacing_loading.py
- tests/test_r1513_pace_list_grammar.py
- tests/test_r659_pacing_row_path_names.py
- tests/test_r809_pace_name_not_covering_status.py
- tests/test_r993_pace_tools_flat.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import json
import os
import pytest
import socket
import subprocess
import sys
import time
import urllib.request


# ---- merged from tests/test_r1510_pacing_loading.py ----

pytest.importorskip("playwright", reason="渲染门禁依赖 playwright")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p








LOADING_PROBE = r"""
() => {
  const b=document.getElementById('cfgpacingRows');
  const card=b.querySelector('.sload');
  const r=card?card.getBoundingClientRect():null;
  const br=b.getBoundingClientRect();
  return {
    loading:b.dataset.loading||'', busy:b.getAttribute('aria-busy')||'',
    hasCard:!!card, text:card?card.innerText.replace(/\s+/g,' '):'',
    elapsed:(b.querySelector('.selapsed')||{}).textContent||'',
    skel:b.querySelectorAll('.slskel i').length,
    cardW:r?+r.width.toFixed(1):0, boxW:+br.width.toFixed(1),
    rows:b.querySelectorAll('.srow').length,
    docDx:document.documentElement.scrollWidth-document.documentElement.clientWidth
  };
}
"""

ERROR_PROBE = r"""
() => {
  const b=document.getElementById('cfgpacingRows');
  const e=b.querySelector('.slerr');
  return {hasErr:!!e, text:e?e.innerText.replace(/\s+/g,' '):'',
          retry:e?e.querySelector('button').textContent.trim():'',
          rows:b.querySelectorAll('.srow').length,
          docDx:document.documentElement.scrollWidth-document.documentElement.clientWidth};
}
"""


def _install_fetch(page, mode):
    """把 /api/strategy 的 fetch 换成可控桩；返回恢复脚本。"""
    page.evaluate(
        """(mode)=>{
          if(!window.__ofetch)window.__ofetch=window.fetch;
          window.__stratMode=mode;
          window.fetch=function(u,o){
            if(String(u).indexOf('/api/strategy')>=0){
              if(window.__stratMode==='stall')return new Promise(function(){});
              if(window.__stratMode==='fail')return Promise.resolve({ok:true,json:function(){
                return Promise.resolve({ok:false,err:'矩阵计算超时'});}});
            }
            return window.__ofetch.apply(window,arguments);
          };
          const b=document.getElementById('cfgpacingRows');
          b.dataset.painted='0';STRATPAY=null;loadStrategyPanel(true);
        }""", mode)


def _restore_fetch(page):
    page.evaluate("()=>{if(window.__ofetch)window.fetch=window.__ofetch;}")






# ---- merged from tests/test_r1513_pace_list_grammar.py ----

pytest.importorskip("playwright", reason="渲染门禁依赖 playwright")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p








PROBE = r"""
() => {
  const rows=[...document.querySelectorAll('#paceBox .pace-row')];
  const box=e=>{if(!e)return null;const b=e.getBoundingClientRect();
    return {x:+b.x.toFixed(1),y:+b.y.toFixed(1),w:+b.width.toFixed(1),h:+b.height.toFixed(1),
            right:+b.right.toFixed(1)}};
  const first=rows[0];
  const ev=first?first.querySelector('.ev'):null;
  const e1=ev?ev.querySelector('.e1'):null;
  const e2=ev?ev.querySelector('.e2'):null;
  return {
    n:rows.length,
    heads:document.querySelectorAll('#paceBox .pace-head').length,
    hs:rows.map(r=>+r.getBoundingClientRect().height.toFixed(1)),
    row:box(first), ev:box(ev), e1:box(e1), e2:box(e2),
    ac:box(first?first.querySelector('.ac'):null),
    docDx:document.documentElement.scrollWidth-document.documentElement.clientWidth
  };
}
"""


def _cols(page):
    return page.evaluate(PROBE)










# ---- merged from tests/test_r659_pacing_row_path_names.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LATIN_IDS = ("app-list", "app-route", "app-blocker", "app-dump",
             "app-error", "android-runtime", "android-device",
             "snap-restore")


def _src():
    import io
    return webui_full_src()


def test_pacing_row_renders_use_path_cn():
    src = _src()
    assert "pws.push(pathCN(pp)+' '" in src, (
        "节流行右半的通路名没走 pathCN，会打出 app-list 这类英文 id")
    assert "'最差通路 '+_worst[0]" in src and \
        "pathCN(pp)" in src.split("const _worst=[]")[1][:2000], (
        "结论行的「最差通路」仍在拼原始键名")
    assert "dead.forEach(pp=>pws.push(pathCN(pp)+' 退役'))" in src
    # 同一段写两遍会让退役通路在行里出现两次（r659 顺手清掉）
    assert src.count("pws.push(pathCN(pp)+' 退役')") == 1, (
        "退役标签又重复渲染了")




def _bare(text):
    import re
    return sorted({p for p in LATIN_IDS
                   if re.search(r"(?<![A-Za-z_-])" + re.escape(p)
                                + r"(?![A-Za-z_-])", text)})






# ---- merged from tests/test_r809_pace_name_not_covering_status.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

M = r"""() => {
  // elementFromPoint 对视口外的点返回 null——先滚到节流表，否则负控永远探不到。
  const pace = document.querySelector('.pace');
  if (pace) pace.scrollIntoView({block: 'center'});
  const rows = [...document.querySelectorAll('.pace-row')];
  const out = [];
  let cols = null;
  for (const r of rows) {
    const nm = r.querySelector('.nm'), st = r.querySelector('.st');
    if (!nm || !st || nm.getBoundingClientRect().width < 1) continue;
    if (cols === null) cols = getComputedStyle(r).gridTemplateColumns;
    const nt = nm.querySelector('.nm-t');
    const ncs = nt ? getComputedStyle(nt) : null;
    const nr = nm.getBoundingClientRect();
    const sr = st.getBoundingClientRect();
    // **不能**用 Range 量「文字有没有压过去」：Range 返回的是布局矩形，
    // 不受 overflow 裁剪——已实测正控下 Range 右缘仍越过状态列 9.8px。
    // 真正该问的是「盒外的可见像素属于谁」→ elementFromPoint。
    const probeX = Math.min(nr.right + 2, sr.left - 1);
    const probeY = nr.top + nr.height / 2;
    const hitEl = document.elementFromPoint(probeX, probeY);
    const leaked = !!hitEl && (hitEl === nm || nm.contains(hitEl));
    const textRight = nr.right;
    // **矩形相交**才叫"覆盖"：堆叠布局下 nm/st 同列不同行，x 相同但不覆盖。
    const _ox = Math.min(nr.right, sr.right) - Math.max(nr.left, sr.left);
    const _oy = Math.min(nr.bottom, sr.bottom) - Math.max(nr.top, sr.top);
    const covered = _ox > 0.5 && _oy > 0.5;
    out.push({txt: (nm.textContent || '').trim(),
              overlap: +(textRight - sr.left).toFixed(1),
              covered,
              stacked: !(_oy > 0.5),
              leaked,
              hasT: !!nt,
              te: ncs ? ncs.textOverflow : null,
              ovf: ncs ? ncs.overflow : null,
              lost: nt ? nt.scrollWidth - nt.clientWidth : 0,
              title: nm.getAttribute('title') || (nt && nt.getAttribute('title')) || ''});
  }
  // 健康行首列宽（.hrow 的品牌列），用于校验"同一条竖线"
  let healthFirstCol = null;
  const hr = document.querySelector('#healthcard .hrow');
  if (hr) {
    const hcs = getComputedStyle(hr);
    const t = (hcs.gridTemplateColumns || '').split(' ');
    if (t.length) healthFirstCol = t[0];
  }
  return {cols: cols, n: out.length, rows: out,
          healthFirstCol: healthFirstCol};
}"""

# 负控不能用 CSS 构造：修复前是**裸文本节点**（匿名 flex item，不可收缩），
# 加 .nm-t 之后就一定有可收缩层了。要精确复现旧形态，只能在 DOM 里把
# 包层拆掉、把文字退回成裸节点。
# 负控：**强行让名字溢出**（而不是拆 .nm-t）。
#
# 老写法是"把 .nm-t 拆掉让文字退回裸节点，压列应复现"。2026-11-06 实测
# 该前提已不成立：品牌列实际 104px，拆了也不压列 → 负控恒失败。
# 负控要证明的是**检测器有效**，所以直接注入一条把名字撑到 600px 的样式，
# 几何判定必须报 covered，否则说明 `covered` 这条判据是死的。
UNWRAP = r"""() => {
  const rows = [...document.querySelectorAll('.pace-row')];
  let n = 0;
  for (const r of rows) {
    const nm = r.querySelector('.nm');
    if (!nm) continue;
    nm.style.minWidth = '600px';
    nm.style.overflow = 'visible';
    const t = nm.querySelector('.nm-t');
    if (t) { t.style.minWidth = '600px'; t.style.overflow = 'visible'; }
    n++;
  }
  return n;
}"""


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p








# 只测单行布局（>760px）。窄屏 `@media(max-width:760px)` 会切成
# 纵向堆叠（`minmax(0,1fr) auto`），**本来就没有品牌列**，这条约束
# 在那里不成立（2026-11-06 实测 grid-template-columns=413px 81px）。


# 负控只在**单行布局**下做：窄屏（≤760px）是纵向堆叠，名字与状态本就在
# 不同行，横向撑宽也不会相交——在那里做负控没有意义（2026-11-06 实测）。


# ---- merged from tests/test_r993_pace_tools_flat.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p












