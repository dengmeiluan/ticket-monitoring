# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1090_probe_single_row.py
- tests/test_r1139_detail_gallery_drawer.py
- tests/test_r631_effect_hint_reaches_the_row.py
- tests/test_r669_advice_probe_has_a_button.py
- tests/test_r999_chband_meta_inline.py
- tests/test_r999_route_chip_soft.py
- tests/test_r999_sparse_mobile.py
- tests/test_r999_trend_routes_wrap.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import json
import os
import pytest
import socket
import subprocess
import sys
import time
import urllib.request


# ---- merged from tests/test_r1090_probe_single_row.py ----

pytest.importorskip("playwright",
                    reason="探针布局依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None
WIDTHS = [320, 360, 361, 375, 390, 480, 600, 601, 700, 768, 900]


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p




SNAP = """(() => {
  const q=document.querySelector('#srxProbe .srx-qrow');
  const rg=e=>{if(!e)return null;const r=e.getBoundingClientRect();
    return {L:Math.round(r.left),T:Math.round(r.top),R:Math.round(r.right),
      B:Math.round(r.bottom),W:Math.round(r.width),H:Math.round(r.height)}};
  const kids=[...q.children].filter(e=>e.getBoundingClientRect().width>2);
  const items=kids.map(e=>({cls:String(e.className).split(' ').pop(),
    r:rg(e),sw:e.scrollWidth,cw:e.clientWidth}));
  const inp=document.getElementById('srxFrom');
  const to=document.getElementById('srxTo');
  const date=document.getElementById('srxDate');
  const combo=document.getElementById('srxBatchToggle');
  const go=document.getElementById('srxGo');
  const rail=document.getElementById('srxPlatPick');
  const row=document.getElementById('srxChannelRow');
  return {items,row:rg(q),formH:Math.round(document.querySelector(
      '#srxProbeForm').getBoundingClientRect().height),
    combo:rg(combo),comboInForm:!!combo.closest('#srxProbeForm'),
    comboClip:combo.scrollWidth-combo.clientWidth,
    cityClip:inp.scrollWidth-inp.clientWidth,
    toClip:to.scrollWidth-to.clientWidth,
    dateClip:date.scrollWidth-date.clientWidth,
    rail:Object.assign(rg(rail),{ov:getComputedStyle(rail).overflow}),railRow:rg(row),chips:rail.querySelectorAll('.srx-pchip').length,
    chipRows:[...new Set([...rail.querySelectorAll('.srx-pchip')]
      .map(e=>Math.round(e.getBoundingClientRect().top)))].length,
    railOver:rail.scrollWidth-rail.clientWidth,
    goTitle:go.title, goLabel:go.getAttribute('aria-label'),
    over:document.documentElement.scrollWidth-innerWidth};
})()"""




# ---- merged from tests/test_r1139_detail_gallery_drawer.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_PROBE = """() => {
 const g=e=>{if(!e)return null;const r=e.getBoundingClientRect();const cs=getComputedStyle(e);
  return {w:Math.round(r.width),h:Math.round(r.height),x:Math.round(r.left),
    right:Math.round(r.right),y:Math.round(r.top),
    disp:cs.display,cols:cs.gridTemplateColumns};};
 const d=document.getElementById('srxDetail');
 const acts=d.querySelector('.srx-dtabs .srx-dacts');
 const dg=d.querySelector('.srx-dgrid');
 return {vw:innerWidth,vh:innerHeight,
  detail:g(d),head:g(d.querySelector('.srx-dhead')),tabs:g(d.querySelector('.srx-dtabs')),
  foot:g(d.querySelector('.srx-savebar')),acts:g(acts),dgrid:g(dg),
  cols:dg?getComputedStyle(dg).gridTemplateColumns.split(' ').filter(Boolean).length:0,
  over:document.documentElement.scrollWidth-innerWidth};}"""

_GAL = """() => {
 const g=e=>{if(!e)return null;const r=e.getBoundingClientRect();
  return {w:Math.round(r.width),h:Math.round(r.height),x:Math.round(r.left),y:Math.round(r.top)};};
 const gal=document.getElementById('srxGallery');
 return {vw:innerWidth,vh:innerHeight,gal:g(gal),head:g(gal.querySelector('.srx-galhead')),
  over:document.documentElement.scrollWidth-innerWidth};}"""




def _page(browser, server, width):
    pg = browser.new_page(viewport={"width": width, "height": 950},
                          is_mobile=(width <= 600), has_touch=(width <= 600))
    pg.goto("http://127.0.0.1:%d/" % server, wait_until="domcontentloaded",
            timeout=30000)
    pg.wait_for_timeout(2200)
    pg.evaluate("switchView('search')")
    pg.wait_for_timeout(700)
    return pg


def _open_detail(pg):
    ok = pg.evaluate("""()=>{const rows=(typeof srxFiltered==='function')
        ?srxFiltered():[];const f=rows[0];if(!f)return false;
      SRX.sel=srxKey(f);srxOpenDetail();return true;}""")
    assert ok, "演示数据没有可打开的行"
    pg.wait_for_timeout(500)








# ---- merged from tests/test_r631_effect_hint_reaches_the_row.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HINT = ("国际域：有改善但仍偏低：48% → 53%，建议再自检一次；"
        "同期渠道整体 44% → 84%（整体已可用，是这个域没用到——可换域或先观察）")

INJECT = (
    "(()=>{const fake={ok:true,quiet:{},cfg:{warmup_platforms:['qunar']},"
    "last_round:{},effect:{},channels:{},recurrences:[],paths:{platforms:{}},"
    "coverage:{ok:[],sent:[]}};"
    "fake.channels.ctrip={state:'ok',remain_s:0,"
    "advice:{state:'ok',hint:'',severity:'ok'},"
    "effect:{state:'partial',hint:" + json.dumps(HINT, ensure_ascii=False) + ","
    "severity:'wait',before:0.44,after:0.84,after_n:98,action:'probe'}};"
    "const o=window.fetch;window.fetch=function(u,x){"
    "if(String(u).indexOf('/api/pacing')>=0)"
    "return Promise.resolve(new Response(JSON.stringify(fake),"
    "{status:200,headers:{'Content-Type':'application/json'}}));"
    "return o.apply(this,arguments)};return true})()"
)




# ---- merged from tests/test_r669_advice_probe_has_a_button.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _payload(action, state, hint, needs_login=False):
    ch = {}
    for i, p in enumerate(("qunar", "fliggy", "ctrip", "tongcheng", "tuniu")):
        if i == 0:
            ch[p] = {"state": state, "reason": "", "needs_login": needs_login,
                     "advice": {"state": "login" if needs_login else state,
                                "action": action, "severity": "auto",
                                "hint": hint, "eta_s": 60}}
        else:
            ch[p] = {"state": "ok", "advice": {"state": "ok",
                                               "action": "none"}}
    return {"ok": True, "quiet": {}, "last_round": {"trips": []},
            "cfg": {"min_gap_s": 0, "per_minute": 0}, "effect": {},
            "channels": ch}


# 后端真的会写「点『自检』」的三类结论
PROBE_HINTS = {
    "path_degraded": "国内 App 航班列表 近 24h 有效率 30%——可点「自检」验证",
    "calendar_only": "近 24h 只拿到日历价，没有航班明细；点「自检」看具体路径",
    "soft_reject": "上一轮被软拒 … 若连续出现，点「自检」看路径",
}






def _has_probe(row):
    return any("probeNow" in h for h in row["html"])










# ---- merged from tests/test_r999_chband_meta_inline.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_css_keeps_meta_inline_on_mobile():
    with io.StringIO(webui_full_src()) as f:
        src = f.read()
    i = src.index(" .chband-meta{white-space:normal!important")
    blk = src[i:i + 220]
    assert "flex:0 1 auto!important" in blk, blk






# ---- merged from tests/test_r999_route_chip_soft.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_css_scopes_trend_chip_selection():
    with io.StringIO(webui_full_src()) as f:
        src = f.read()
    assert "#montab-trend .frow .chip.on{background:var(--r-blue-soft)!important" in src
    assert "color:var(--r-blue)!important" in src[src.index(
        "#montab-trend .frow .chip.on"):][:200]






# ---- merged from tests/test_r999_sparse_mobile.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_css_has_mobile_sparse_override():
    with io.StringIO(webui_full_src()) as f:
        src = f.read()
    assert ".spmon-chartwrap.is-sparse{min-height:128px!important;height:128px!important}" in src
    assert ".spmon-chartwrap.is-sparse canvas{height:110px!important}" in src






# ---- merged from tests/test_r999_trend_routes_wrap.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_static_trend_routes_wrap_rule():
    with io.StringIO(webui_full_src()) as f:
        src = f.read()
    assert "#chartcard #chartRoutes{flex-wrap:wrap!important" in src
    assert "overflow-x:visible!important" in src[src.index(
        "#chartcard #chartRoutes{flex-wrap:wrap!important"):][:260]




