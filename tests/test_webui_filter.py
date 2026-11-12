# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r697_filter_cards_same_height.py
- tests/test_r701_filter_chip_renders_icon.py
- tests/test_r836_filter_card_voids.py
- tests/test_r874_filter_edges_and_mirror_void.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import os
import pytest
import re
import socket
import subprocess
import sys
import time
import urllib.request
import webui

from pathlib import Path


# ---- merged from tests/test_r697_filter_cards_same_height.py ----

SRC = webui.PAGE


def test_grid_stretches_same_row_cards():
    m = re.search(r"#searchview \.srf-grid\{[^}]*\}", SRC)
    assert m, "找不到 #searchview .srf-grid 规则"
    assert "align-items:stretch" in m.group(0), (
        "srf-grid 回到 start——同排两张卡会各按内容收缩，底边必然参差：%s"
        % m.group(0)[:120])


def test_time_card_no_longer_pins_to_start():
    found = re.findall(r"\.srf-time\{[^}]*align-self:([a-z]+)[^}]*\}", SRC)
    assert found, "找不到 .srf-time 的 align-self 规则"
    assert all(v == "stretch" for v in found), (
        ".srf-time 仍是 align-self:%s——网格 stretch 会被它自己覆盖掉" % found)


def test_time_card_distributes_its_extra_space():
    """拉高后的余量不能变成卡内孤立空洞（实测 114px 死白）。

    r876：原用 `justify-content:space-between` 把余量摊到每段之间——右侧
    「起降时段」的两组时段因此被推得离标题很远，右栏第 1 行与左栏第 1 行
    差 13.6px（292 vs 278.4），读作「上下不对齐」。
    现改成内容整体贴顶：两栏首行同线，余量落在卡底（与左卡内容贴顶一致）。
    判据由 test_r836_filter_card_voids 实测卡内无 >34px 的孤立空洞来守；
    这里只守「不得回到把余量摊进组间的写法」。
    """
    assert re.search(r"\.srf-time\{[^}]*justify-content:flex-start", SRC), (
        "起降时段卡又用 space-between——组间间距会随卡高漂移，两栏首行错位")


def test_second_row_cards_distribute_their_extra_space():
    """r836 起第二排改为「加工与历史 | 价格带+检索特有竖向堆叠」。

    原判据要求 `.srf-price`/`.srf-evidence` 用 space-between 均分余量；
    实测那样会在两张稀疏卡里各留 57.3 / 100.5px 的大洞（用户报「衔接空格
    很大很空」）。现改为两张卡按内容收缩堆叠，卡内最大空档回到 8px。
    这里同时守住「不被拉回等高」与「两卡仍在」，避免有人只删掉 CSS 就算。
    """
    assert "srf-stack" in SRC, "第二排的堆叠容器不见了"
    m = re.search(r"#searchview \.srf-stack\{[^}]*\}", SRC)
    assert m, "找不到 .srf-stack 规则"
    assert "flex-direction:column" in m.group(0), (
        "价格带/检索特有又变回平铺——卡内会重新出现 57/100px 的洞")
    # 两张卡不得再声明 grid-area（它们是 stack 的 flex 子项，不是网格项）
    for cls in ("srf-price", "srf-evidence"):
        assert not re.search(r"#searchview \.%s\{[^}]*grid-area:(price|evidence)" % cls, SRC), (
            "%s 仍钉在旧网格区域上，会被拉回等高" % cls)


# ---- merged from tests/test_r701_filter_chip_renders_icon.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)






# ---- merged from tests/test_r836_filter_card_voids.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = _free_port()
BASE = "http://127.0.0.1:%d" % PORT

JS = r"""() => {
  const fm = document.getElementById('srxFmore');
  if(!fm) return {err:'no panel'};
  const R = e => { const b=e.getBoundingClientRect();
    return {t:b.top, b:b.bottom, h:b.height, l:b.left, r:b.right, w:b.width}; };
  const cards = [...fm.querySelectorAll('.srf-card')].map(c=>{
    const kids=[...c.children].filter(k=>k.getBoundingClientRect().height>1);
    const cr=R(c), padT=parseFloat(getComputedStyle(c).paddingTop)||0;
    let prev=cr.t+padT, maxGap=0;
    kids.forEach(k=>{ const r=R(k); if(r.t-prev>maxGap) maxGap=r.t-prev; prev=r.b; });
    return {cls:c.className.trim(), h:+cr.h.toFixed(1), maxGap:+maxGap.toFixed(1),
            l:+cr.l.toFixed(1), b:+cr.b.toFixed(1), w:+cr.w.toFixed(1)};
  });
  // 「同排底边齐平」看的是网格的**直接子项**：共同筛选 / 起降时段 /
  // 加工与历史 / 堆叠列 / 当前筛选。堆叠列内部的卡是列内堆叠，不参与
  // 同一行的比较——否则 price 底边 594.8 会被误判成「与 history 差 122px」。
  const grid = fm.querySelector('.srf-grid');
  const gridW = R(grid).w;
  const tops = [...grid.children].filter(e=>e.getBoundingClientRect().height>1).map(e=>{
    const r=e.getBoundingClientRect();
    return {cls:(e.className||'').toString().trim(), t:+r.top.toFixed(1),
            b:+r.bottom.toFixed(1), w:+r.width.toFixed(1)};
  });
  const bands=[];
  tops.forEach(k=>{
    if(k.w >= gridW - 1) return;                 // 全宽行自成一行，不参与比较
    const band=bands.find(x=>Math.abs(x.top-k.t)<=2);
    if(band)band.items.push(k); else bands.push({top:k.t, items:[k]});
  });
  const rowSpreads=bands.filter(x=>x.items.length>1).map(x=>{
    const bs=x.items.map(k=>k.b);
    return {top:+x.top.toFixed(1), spread:+(Math.max(...bs)-Math.min(...bs)).toFixed(1),
            items:x.items.map(k=>k.cls+'@'+k.b)};
  });
  return {panelH:+R(fm).h.toFixed(1), cards, rowSpreads};
}"""








def test_price_and_evidence_stack_vertically():
    """结构判据：两张稀疏卡必须在同一个堆叠列里，否则网格又会把它们拉平。

    判据跟着「谁把 price/evidence 包进堆叠列」走，不再按固定字符窗口截取
    ——往同文件别处加代码会把窗口推离目标，制造与缺陷无关的假红。
    """
    import webui
    src = webui.PAGE
    assert "'<div class=\"srf-stack\">'+price+evidence" in src, \
        "价格带/检索特有没有并进同一个堆叠列"
    assert "grid-area:stack" in src, "堆叠列没有落在网格的 stack 区域"


# ---- merged from tests/test_r874_filter_edges_and_mirror_void.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = _free_port()
BASE = "http://127.0.0.1:%d" % PORT

# 明细筛选卡：每行的「标签文字首字」与「第一个内容控件左缘」
FT = r"""() => {
  const textL = el => {
    if (!el) return null;
    const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = w.nextNode())) {
      if (!n.nodeValue.trim()) continue;
      const r = document.createRange();
      r.selectNodeContents(n);
      const b = r.getBoundingClientRect();
      if (b.width > 0) return +b.left.toFixed(1);
    }
    const inp = el.querySelector('input,select,button');
    if (inp) { const b = inp.getBoundingClientRect(); if (b.width > 0) return +b.left.toFixed(1); }
    return null;
  };
  const R = e => { const b = e.getBoundingClientRect();
    return {l:+b.left.toFixed(1), r:+b.right.toFixed(1), w:+b.width.toFixed(1)}; };
  const wrap = document.getElementById('fltwrap');
  const rows = [];
  const sel = [...wrap.querySelectorAll(':scope > .frow'), wrap.querySelector('#attrchips')]
    .filter(r => r && getComputedStyle(r).display !== 'none');
  for (const r of sel) {
    // 标签可能嵌在 .wingrp / .agrp 里，递归找（但不要把 chip 的文本当标签）
    const lab = r.querySelector(':scope > .chiplab')
             || r.querySelector('.wingrp > .chiplab')
             || r.querySelector('.agrp > .chiplab');
    rows.push({id: r.id || r.className.replace('frow','').trim(),
      labTxt: lab ? lab.textContent.trim().slice(0,6) : null,
      labTextL: textL(lab)});
  }
  const attr = document.getElementById('attrchips');
  const ags = [...attr.children]
    .filter(a => getComputedStyle(a).display !== 'none')
    .map(a => { const b = a.getBoundingClientRect();
      return {txt: a.textContent.trim().slice(0,6),
              box: {l:+b.left.toFixed(1), r:+b.right.toFixed(1),
                    w:+b.width.toFixed(1), h:+b.height.toFixed(1)}}; });
  return {rows, ags, attrCols: getComputedStyle(attr).gridTemplateColumns};
}"""

# 镜像折叠：列表右缘 vs 网格右缘、触发器两态坐标
SNAP = r"""() => {
  const R = e => { const b = e.getBoundingClientRect();
    return {l:+b.left.toFixed(1), r:+b.right.toFixed(1), t:+b.top.toFixed(1),
            w:+b.width.toFixed(1)}; };
  const g = document.getElementById('srxGrid');
  const list = document.querySelector('#srxGrid > .srx-list');
  const mir = document.querySelector('#srxGrid .srx-mirror');
  const fb = document.querySelector('#srxMirrorFold');
  const gr = R(g), lr = R(list);
  return {cols: getComputedStyle(g).gridTemplateColumns,
          gapRight: +(gr.r - lr.r).toFixed(1),
          listW: lr.w, gridW: gr.w,
          btn: R(fb), folded: mir.classList.contains('srx-folded'),
          mirDisp: getComputedStyle(mir).display};
}"""

# ---------------------------------------------------------------- r876
SRF = r"""() => {
  const R = e => { const b = e.getBoundingClientRect();
    return {l:+b.left.toFixed(1), t:+b.top.toFixed(1), w:+b.width.toFixed(1)}; };
  const fm = document.getElementById('srxFmore');
  const common = fm.querySelector('.srf-common');
  const time = fm.querySelector('.srf-time');
  const history = fm.querySelector('.srf-history');
  const firstRow = c => {
    const hd = c.querySelector(':scope > header');
    const kids = [...c.children].filter(k => k !== hd && getComputedStyle(k).display !== 'none');
    return kids.length ? +R(kids[0]).t.toFixed(1) : null;
  };
  const tl = [...(time ? time.querySelectorAll('.srf-tline') : [])].map(e => +R(e).t.toFixed(1));
  const out = {commonTop: common ? R(common).t : null, timeTop: time ? R(time).t : null,
               historyTop: history ? R(history).t : null,
               commonFirst: common ? firstRow(common) : null,
               timeFirst: time ? firstRow(time) : null,
               historyFirst: history ? firstRow(history) : null,
               tlines: tl};
  // 右栏内部行距 vs 左栏「出发机场/到达机场」行的间距
  if (common) {
    const picks = [...common.querySelectorAll('.srf-pick')];
    out.pickTops = picks.map(e => +R(e).t.toFixed(1));
  }
  return out;
}"""









# 镜像折叠只测「本来就是两列」的宽度：≤1100 网格主动收单列，
# 折叠前后都没有右列，不构成「残留空带」的前提。







# ---------------------------------------------------------------- r877
def test_srx_thead_and_rows_share_one_column_grid():
    """检索解析列表：表头六列与数据行六列必须逐列重合。

    r877 前实测 1512：表头 `26/158.1/122/103.4/76/118`，数据行
    `26/171.8/122/91.7/72/96`——除起始列外全部错开（「航班」13.7px、
    「状态」11.7px、「操作」22px），表头文字与它下面的数据整列不齐。
    根因有两条：① ≤981 档只改了数据行的列模板；② 表头内衬 10px / gap 6，
    数据行 12px / 10。两者都把「同一份模板」算出不同宽度。
    """
    import re
    import webui
    src = webui.PAGE
    m = re.search(r"@media\(min-width:981px\)\{\s*#searchview \.srx-thead,#searchview \.srx-row\{([^}]*)\}",
                  src)
    assert m, "981 档没有把表头与数据行绑成同一个选择器"
    assert "1.5fr" in m.group(1) and "72px 96px" in m.group(1), m.group(1)
    i = src.index(" #searchview .srx-thead{padding-left:12px")
    seg = src[i:src.index("}", i) + 1]
    assert "column-gap:10px" in seg, (
        "表头内衬/gap 与数据行不一致——同样的 fr 会算出不同列宽")


# ---------------------------------------------------------------- r878
FOLD_MORE = r"""() => {
  const b = document.getElementById('srxMoreBtn');
  const R = e => { const r = e.getBoundingClientRect();
    return {l:+r.left.toFixed(1), t:+r.top.toFixed(1)}; };
  const a = R(b);
  b.click();
  return new Promise(res => setTimeout(() => {
    const m = R(b);
    b.click();
    setTimeout(() => res({a, open: m, reclosed: R(b)}), 520);
  }, 520));
}"""




# ---------------------------------------------------------------- r879
AIR = r"""() => {
  const chips = document.getElementById('alchips');
  const wide = document.querySelector('#attrchips .ag-wide');
  const rows = new Set([...chips.children].map(c => +c.getBoundingClientRect().top.toFixed(1)));
  const cs = getComputedStyle(chips);
  return {rows: rows.size, n: chips.children.length,
          h: +chips.getBoundingClientRect().height.toFixed(1),
          wideH: +wide.getBoundingClientRect().height.toFixed(1),
          sw: chips.scrollWidth, cw: chips.clientWidth,
          wrap: cs.flexWrap, ox: cs.overflowX};
}"""


