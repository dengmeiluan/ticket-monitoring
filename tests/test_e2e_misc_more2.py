# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1122_stable_overlays.py
- tests/test_r1130_combo_states.py
- tests/test_r1131_render_census.py
- tests/test_r795_collapsed_overview_has_entry.py
- tests/test_r801_chip_touch_target.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
import io
from support_webui_src import webui_full_src

import json
import os
import pytest
import socket
import subprocess
import sys
import time
import urllib.request


# ---- merged from tests/test_r1122_stable_overlays.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p




SNAP = r"""() => {
  const q=s=>document.querySelector(s);
  const rr=el=>{if(!el)return null;const b=el.getBoundingClientRect();
    return {l:+b.left.toFixed(0),t:+b.top.toFixed(0),r:+b.right.toFixed(0),b:+b.bottom.toFixed(0),
      w:+b.width.toFixed(0),h:+b.height.toFixed(0),pos:getComputedStyle(el).position,
      disp:getComputedStyle(el).display};};
  const probe=q('#srxProbe'), form=q('#srxProbeForm');
  return {sh:document.documentElement.scrollHeight,vw:innerWidth,vh:innerHeight,
    over:document.documentElement.scrollWidth-innerWidth,
    probe:rr(probe),form:rr(form),
    plat:rr(q('#srxPlatPop')),batch:rr(q('#srxBatchDock')),
    ch:rr(q('#srxChLinksDrawer')),fly:rr(q('#srxCtxFly'))};
}"""


def _open_probe(pg):
    pg.evaluate("()=>{const p=document.getElementById('srxProbe');"
                "if(p&&!p.classList.contains('open'))document.getElementById('srxProbeTool').click()}")
    pg.wait_for_timeout(500)


def _open_more(pg):
    pg.evaluate("()=>{const b=document.querySelector('#searchview .srx-more-btn');"
                "if(b&&!b.closest('.srx-hero-act').classList.contains('open'))b.click()}")
    pg.wait_for_timeout(350)




# ---- merged from tests/test_r1130_combo_states.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_static_combo_copy_and_state_source():
    with io.StringIO(webui_full_src()) as f:
        src = f.read()
    assert "srxBatchSyncAdd" in src
    assert "add.textContent=dup?'已加入':(full?'已满 4 条':'＋ 当前条件')" in src
    assert "go.textContent='运行组合'" in src
    assert "运行组合 ('+a.length+')" not in src
    assert "该航线/日期已在组合中。" not in src


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p




# ---- merged from tests/test_r1131_render_census.py ----

pytest.importorskip("playwright", reason="渲染普查依赖 playwright")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p






SEARCH = """() => {
  const vis=e=>{const c=getComputedStyle(e),r=e.getBoundingClientRect();
    return c.display!=='none'&&c.visibility!=='hidden'&&r.width>2&&r.height>2};
  const kids=[...document.querySelectorAll('#srxProbe>*')].filter(vis);
  const ys=[...new Set(kids.map(e=>Math.round(e.getBoundingClientRect().top)))];
  const comboNodes=[...document.querySelectorAll('button,span,em,b,div')]
    .filter(e=>vis(e)&&/^组合\\s*\\d\\/4$/.test((e.textContent||'').trim()));
  const btns=[...document.querySelectorAll('#srxBatchToggle')].filter(vis);
  return {ys, kids:kids.map(e=>e.id||e.className),
    toolsH:+document.getElementById('srxToolsRow').getBoundingClientRect().height.toFixed(1),
    batchN:btns.length, comboN:comboNodes.length,
    inForm:!!(btns[0]&&btns[0].closest('#srxProbeForm'))};
}"""


def _search_bad(d):
    bad = []
    if len(d["ys"]) > 2:
        bad.append("顶部可见 y 行 %d: %s" % (len(d["ys"]), d["ys"]))
    if d["toolsH"] > 1:
        bad.append("#srxToolsRow 高 %s" % d["toolsH"])
    if d["batchN"] != 1:
        bad.append("#srxBatchToggle %d 个" % d["batchN"])
    if d["comboN"] != 1:
        bad.append("可见组合 N/4 %d 个" % d["comboN"])
    if not d["inForm"]:
        bad.append("组合不在表单主行")
    return bad




DRAWER = """() => {
  const d=document.getElementById('srxChLinksDrawer'),m=document.getElementById('srxChLinksMask');
  const b=document.getElementById('srxChLinksBtn');
  if(!d||!m||!b)return {exists:false};
  const r=d.getBoundingClientRect(),cs=getComputedStyle(d);
  return {exists:true, hidden:d.hidden, pos:cs.position, vw:innerWidth,
    w:+r.width.toFixed(1), name:b.textContent.trim(), aria:b.getAttribute('aria-expanded'),
    mask:!m.hidden, maskPos:getComputedStyle(m).position,
    ctx:/当前航线|from=|date=/.test(d.innerText),
    triggers:[...document.querySelectorAll('#srxChLinksBtn')].length};
}"""


def _drawer_bad(d):
    if not d.get("exists"):
        return ["抽屉不存在"]
    bad = []
    if d["hidden"]:
        bad.append("抽屉未显示")
    if d["pos"] != "fixed":
        bad.append("position=%s" % d["pos"])
    # 用户裁定：渠道入口为 420–480 宽右抽屉；桌面非模态（无遮罩、
    # 不锁滚动），≤600 窄档才用遮罩底部抽屉。
    if not (420 <= d["w"] <= 480):
        bad.append("宽 %s 超出 420-480" % d["w"])
    if d.get("vw", 9999) > 600:
        if d["mask"]:
            bad.append("桌面不应有遮罩")
    else:
        if not d["mask"]:
            bad.append("窄档无遮罩")
        if d["maskPos"] != "fixed":
            bad.append("遮罩非 fixed")
    if d["ctx"]:
        bad.append("携带航线/日期上下文")
    if d["triggers"] != 1:
        bad.append("触发器 %d 个" % d["triggers"])
    if d["aria"] != "true":
        bad.append("aria-expanded 未同拍")
    return bad




MIRROR = """() => {
  const q=s=>{const e=document.querySelector(s);if(!e)return null;const r=e.getBoundingClientRect();
    return {x:+r.x.toFixed(1),y:+r.y.toFixed(1),w:+r.width.toFixed(1),h:+r.height.toFixed(1)}};
  const inter=(a,b)=>!!(a&&b&&a.w>0&&a.h>0&&b.w>0&&b.h>0&&
    a.x<b.x+b.w&&b.x<a.x+a.w&&a.y<b.y+b.h&&b.y<a.y+a.h);
  const fs=[...document.querySelectorAll('button')].filter(e=>/^(展开|收起)渠道镜像$/.test((e.textContent||'').trim()));
  const m=q('#srxMirror'),head=q('#srxListHead'),th=q('.srx-thead');
  return {foldN:fs.length,inHead:!!(fs[0]&&fs[0].closest('#srxListHead')),
    fold:q('#srxMirrorFold'),mirror:m,head,thead:th,
    interHead:inter(m,head),interThead:inter(m,th),
    label:fs[0]?fs[0].textContent.trim():''};
}"""




DIAG = """() => {
  const q=s=>{const e=document.querySelector(s);if(!e)return null;const r=e.getBoundingClientRect();
    return {x:+r.x.toFixed(1),y:+r.y.toFixed(1),w:+r.width.toFixed(1),h:+r.height.toFixed(1)}};
  const p=q('#healthDiag>#srccap .scpath'),a=q('#healthDiag>#srccap .scfoot');
  return {p,a,gap:p&&a?+(a.x-(p.x+p.w)).toFixed(1):null,
    ml:getComputedStyle(document.querySelector('#healthDiag>#srccap .scfoot')).marginLeft,
    diagH:+document.getElementById('healthDiag').getBoundingClientRect().height.toFixed(1)};
}"""




PACE = """() => {
  const rows=[...document.querySelectorAll('#hbody .hrow')].map(e=>+e.getBoundingClientRect().height.toFixed(1));
  const pr=[...document.querySelectorAll('#paceBox .pace-row')].map(e=>+e.getBoundingClientRect().height.toFixed(1));
  const side=document.querySelector('#paceBox .pace-side');
  const chips=[...document.querySelectorAll('#paceBox .pstrip .pchip')];
  const byTop={};chips.forEach(e=>{if(e.getBoundingClientRect().width<2)return;
    const t=Math.round(e.getBoundingClientRect().top);byTop[t]=(byTop[t]||0)+1});
  const body=document.querySelector('#paceBox .pace-body');
  const main=document.querySelector('#paceBox .pace-main');
  return {healthMax:rows.length?Math.max(...rows):0,paceMax:pr.length?Math.max(...pr):0,
    sideW:side?+side.getBoundingClientRect().width.toFixed(1):0,
    bodyW:body?+body.getBoundingClientRect().width.toFixed(1):0,
    mainW:main?+main.getBoundingClientRect().width.toFixed(1):0,
    chipPerRow:Math.max(0,...Object.values(byTop)),nChips:chips.length};
}"""




CFG = """() => {
  const g=document.querySelector('#cfgpacingRows .sgrid');
  if(!g)return {err:'no sgrid'};
  const labs=[...document.querySelectorAll('#cfgpacingRows .glab')].map(e=>e.textContent.trim());
  const cells=[...g.querySelectorAll('.glcell')];
  const mis=cells.filter(c=>{const l=c.querySelector('.glab'),i=c.querySelector('input,select,.sro');
    if(!l||!i)return false;return Math.abs(l.getBoundingClientRect().top-i.getBoundingClientRect().top)>8}).length;
  return {cols:getComputedStyle(g).gridTemplateColumns.split(/\\s+/).filter(Boolean).length,
    vals:labs.filter(x=>x==='取值').length,misaligned:mis,n:cells.length};
}"""




FILTER = """() => {
  const cards=[...document.querySelectorAll('#srxCtxFly .srf-card')];
  let maxRows=0,bad=[];
  cards.forEach(card=>{
    card.querySelectorAll('.srf-chips').forEach(ch=>{
      const cr=ch.getBoundingClientRect();
      const tops=[...new Set([...ch.children].filter(e=>{const r=e.getBoundingClientRect();
        return r.width>2&&r.top<cr.bottom-1&&r.bottom<=cr.bottom+1})
        .map(e=>Math.round(e.getBoundingClientRect().top)))];
      maxRows=Math.max(maxRows,tops.length);
      if(tops.length>2)bad.push({card:(card.querySelector('header b')||{}).textContent,n:tops.length});
    });
  });
  return {maxRows,bad:bad.slice(0,3),n:cards.length};
}"""




# ---- merged from tests/test_r795_collapsed_overview_has_entry.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_PROBE = """()=>{
 const vis=e=>{if(!e)return false;const r=e.getBoundingClientRect();
   return e.offsetParent!==null&&r.width>0&&r.height>0
     &&r.right>0&&r.bottom>0&&r.left<innerWidth;};
 const v=document.getElementById('searchview');
 if(!v.classList.contains('srx-ov-collapsed'))srxToggleOverview();
 const cands=[document.getElementById('srxOvTool'),
              document.getElementById('srxOvHero'),
              ...document.querySelectorAll('#srxMobilebar [data-mobile="overview"]'),
              ...document.querySelectorAll('[onclick*="srxToggleOverview"]')];
 const shown=cands.filter((e,i)=>e&&vis(e)&&cands.indexOf(e)===i)
   .map(e=>({id:e.id||e.className,
             t:(e.textContent||'').trim().slice(0,10),
             aria:e.getAttribute('aria-expanded')}));
 const days=document.getElementById('srxBandBody');
 const showDays=!!days&&getComputedStyle(days).display!=='none'
   &&days.getBoundingClientRect().height>0;
 return {collapsed:v.classList.contains('srx-ov-collapsed'),
         shown:shown,days:showDays};}"""




def _open_search(pg):
    pg.goto("http://127.0.0.1:%d/" % pg._port, wait_until="domcontentloaded",
            timeout=30000)
    pg.wait_for_timeout(2400)
    pg.evaluate("switchView('search')")
    pg.wait_for_timeout(700)






# ---- merged from tests/test_r801_chip_touch_target.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MEASURE = r"""() => {
  const vis = e => e.getBoundingClientRect().height > 1 && e.offsetParent !== null;
  const hit = (e, x, y) => { const t = document.elementFromPoint(x, y);
    return !!t && (t === e || e.contains(t)); };
  const chips = [...document.querySelectorAll('#searchview .srx-chip')].filter(vis);
  const rows = chips.map(e => {
    const r = e.getBoundingClientRect();
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    if (cx < 0 || cy < 0 || cx > innerWidth || cy > innerHeight) return null;
    let up = 0, dn = 0;
    const mid = hit(e, cx, cy);
    if (mid) {
      for (let d = 1; d <= 12; d++) { if (hit(e, cx, r.top - d)) up = d; else break; }
      for (let d = 1; d <= 12; d++) { if (hit(e, cx, r.bottom - 1 + d)) dn = d; else break; }
    }
    return {t: (e.textContent || '').trim().slice(0, 10), boxH: Math.round(r.height),
            up, dn, effH: mid ? Math.round(r.height) + up + dn : -1, mid};
  }).filter(Boolean);
  const days = document.getElementById('srxBandDays');
  return {coarse: matchMedia('(pointer:coarse)').matches, n: rows.length, rows,
          daysH: days ? Math.round(days.getBoundingClientRect().height) : null,
          daysScrollX: days ? days.scrollWidth - days.clientWidth : null};
}"""

# 负控：还原 r801 之前的写法（25px 盒 + 伪元素撑高）
REVERT = """
#searchview .srx-chip{min-height:25px!important}
#searchview .srx-chip{position:relative}
#searchview .srx-chip::after{content:"";position:absolute;left:0;right:0;
 top:50%;height:36px;transform:translateY(-50%)}
"""


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p






