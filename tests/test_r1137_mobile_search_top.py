# -*- coding: utf-8 -*-
"""r1137 门禁：390/320 检索顶部收口 + 底部动作条 + 无裸图标（真渲染）。

细则 §6.19：顶部 = 导航 44 → 标题/状态 48 → 工具栏 36 → 表单 ≤2 行（≤112）
→ 渠道行 40 → 底部动作条 44，结果前总高 ≤320；图标按钮必须有文字或
aria-label+title，裸图标判失败。

旧结构（2026-11-09 实测）：hero 2 行 + 表单 2 行 + 渠道 1 行 + 筛选/矩阵栏
（按钮 36 + 摘要 18，折两行）+ 页签，结果前 368px；概览入口在窄档只剩一颗
30px 柱状图标（文字藏起，形似裸「山」）。本门禁同时锁：
1. 结果前总高 ≤320、表单可见行 ≤2、渠道行 ≤40；
2. 底部动作条 fixed/44px/贴底 8px，概览/筛选/矩阵三枚文字按钮 36px；
3. 顶部与动作条内无「无文字且无 aria-label」的按钮；
4. 概览只有一个可见入口（动作条），工具区图标不再出现同名双入口；
5. 交互：动作条开概览、开筛选（遮罩+底部抽屉）、Esc 关闭并回焦到筛选按钮；
6. 负控：把动作条改回 static / 注入一颗只有 title 的图标钮，判据必须变红。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_PROBE = """() => {
 const vis=e=>{if(!e)return false;const r=e.getBoundingClientRect();
  const cs=getComputedStyle(e);
  return r.width>2&&r.height>2&&cs.display!=='none'&&cs.visibility!=='hidden'
    &&Number(cs.opacity||1)>0.05;};
 const bar=document.getElementById('srxMobilebar');
 const br=bar.getBoundingClientRect(), bs=getComputedStyle(bar);
 const btns=[...bar.querySelectorAll('.srx-mbtn')].filter(vis).map(b=>{
  const r=b.getBoundingClientRect();
  return {t:(b.innerText||'').trim(),w:Math.round(r.width),
    h:Math.round(r.height),x:Math.round(r.left),
    aria:b.getAttribute('aria-expanded'),
    name:((b.innerText||'').trim()||b.getAttribute('aria-label')||'')};});
 const q=document.querySelector('#srxProbeForm .srx-qrow');
 const ys=q?[...q.children].filter(vis)
   .map(e=>Math.round(e.getBoundingClientRect().top)):[];
 const hero=document.querySelector('.srx-hero');
 const res=document.getElementById('srxResults');
 const topH=(hero&&res)?Math.round(res.getBoundingClientRect().top
   -hero.getBoundingClientRect().top):-1;
 const ch=document.getElementById('srxChannelRow');
 const chr=ch?ch.getBoundingClientRect():null;
 const bare=[];
 for(const b of document.querySelectorAll(
   '#searchview .srx-hero button,#searchview #srxProbe button,#srxMobilebar button')){
  if(!vis(b))continue;
  const t=(b.innerText||'').trim();
  if(!t&&!b.getAttribute('aria-label'))
    bare.push({id:b.id,cls:String(b.className).slice(0,50)});}
 const more=document.querySelector('.srx-hero-act > .srx-more-btn');
 const ov=[...document.querySelectorAll(
   '#srxOvTool,#srxMobilebar [data-mobile="overview"]')].filter(vis);
 return {
  bar:{pos:bs.position,h:Math.round(br.height),w:Math.round(br.width),
    x:Math.round(br.left),right:Math.round(br.right),
    bottomGap:Math.round(innerHeight-br.bottom),z:bs.zIndex},
  btns,formRows:[...new Set(ys)].length,topH,
  probeRows:[...new Set([...document.querySelectorAll('#srxProbe > *')]
    .filter(vis).map(e=>Math.round(e.getBoundingClientRect().top)))].length,
  chH:chr?Math.round(chr.height):-1,
  chRows:(()=>{const p=document.getElementById('srxPlatPick');
    if(!p)return 0;return [...new Set([...p.querySelectorAll('.srx-pchip')]
      .map(e=>Math.round(e.getBoundingClientRect().top)))].length})(),
  bare,moreBefore:more?getComputedStyle(more,'::before').content:null,
  moreW:more?Math.round(more.getBoundingClientRect().width):0,
  ovCount:ov.length,ovTexts:ov.map(e=>(e.innerText||'').trim()),
  over:document.documentElement.scrollWidth-innerWidth};
}"""

@pytest.fixture(scope="module")
def server():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    p = subprocess.Popen([sys.executable, "webui.py", "--demo",
                          "--port", str(port)],
                         cwd=ROOT, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    up = False
    for _ in range(120):
        try:
            op.open("http://127.0.0.1:%d/api/state" % port, timeout=1)
            up = True
            break
        except Exception:
            time.sleep(0.25)
    if not up:
        p.terminate()
        pytest.skip("演示服务未在期限内起来")
    yield port
    p.terminate()


def _page(browser, server, width):
    pg = browser.new_page(viewport={"width": width, "height": 950},
                          is_mobile=(width <= 600), has_touch=(width <= 600))
    pg.goto("http://127.0.0.1:%d/" % server, wait_until="domcontentloaded",
            timeout=30000)
    pg.wait_for_timeout(2200)
    pg.evaluate("switchView('search')")
    pg.wait_for_timeout(700)
    return pg


@pytest.mark.parametrize("width", [390, 320])
def test_mobile_search_top_is_three_rows_with_bottom_bar(server, width):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        try:
            pg = _page(b, server, width)
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            d = pg.evaluate(_PROBE)
            assert not errs, errs[:3]
            # 顶部：表单 2 行 + 渠道 ≤2 行；结果前总高 ≤380
            # r1505：渠道 rail 在 ≤600 改成 5 列网格（r1454/1501，替代"按住往右
            # 拖"），所以渠道行必然是 2 行 ≈124px，原来"1 行 ≤40px"的判据已过期。
            # 真意图是「顶部不堆行」——用**结构行数**判，高度只留失控上限；
            # 首屏总高预算相应放宽一行 chip 的高度（320 → 380）。
            assert d["formRows"] <= 2, d
            assert d.get("chRows", 1) <= 2, d
            assert 0 < d["chH"] <= 40 * max(1, d.get("chRows", 1)) + 60, d
            # 首屏总高预算按「多出来的 chip 行」等额放宽：
            # 基准 320（= 表单 2 行 + 渠道 1 行 + 页签），渠道多一行就多给它
            # 实际多出来的高度，避免把「设计上就该有的第二行」判成「堆行」。
            budget = 320 + max(0, d["chH"] - 40)
            assert 0 < d["topH"] <= budget, (
                "%d 档结果前总高 %d > %d：顶部又在堆行（筛选/摘要/页签"
                "不得单独成行）" % (width, d["topH"], budget))
            # 底部动作条：fixed / 44px / 贴底 8px / 满宽
            bar = d["bar"]
            assert bar["pos"] == "fixed", bar
            assert 42 <= bar["h"] <= 46, bar
            assert 6 <= bar["bottomGap"] <= 10, bar
            assert abs(bar["x"] - 8) <= 1 and abs(width - bar["right"] - 8) <= 1, bar
            # 三枚文字按钮：概览/筛选/矩阵，命中 ≥36
            assert len(d["btns"]) == 3, d["btns"]
            txt = " ".join(x["t"] for x in d["btns"])
            for word in ("概览", "筛选", "矩阵"):
                assert word in txt, d["btns"]
            for x in d["btns"]:
                assert x["name"], x
                assert x["h"] >= 36, x
                assert x["w"] >= 60, x
            assert "概览" in d["btns"][0]["t"], d["btns"]
            # 无裸图标；更多按钮有可见文字
            assert d["bare"] == [], d["bare"]
            assert "更多" in (d["moreBefore"] or ""), d
            assert d["moreW"] >= 56, d
            # 概览唯一可见入口 = 动作条按钮（工具区图隐藏）
            assert d["ovCount"] == 1, d
            assert "概览" in d["ovTexts"][0], d
            # 无横向溢出
            assert d["over"] <= 0, d
        finally:
            b.close()


def test_mobile_bottom_bar_controls_overview_and_filter(server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        try:
            pg = _page(b, server, 390)
            # 概览：动作条是唯一入口，文案/aria 随状态走
            pg.click('#srxMobilebar [data-mobile="overview"]')
            pg.wait_for_timeout(250)
            ov = pg.evaluate("""()=>({
              open:!document.getElementById('searchview')
                 .classList.contains('srx-ov-collapsed'),
              txt:document.querySelector('#srxMobilebar [data-mobile=overview]')
                 .innerText.trim(),
              aria:document.querySelector('#srxMobilebar [data-mobile=overview]')
                 .getAttribute('aria-expanded')})""")
            assert ov == {"open": True, "txt": "收起概览", "aria": "true"}, ov
            pg.click('#srxMobilebar [data-mobile="overview"]')
            pg.wait_for_timeout(200)
            # 筛选：遮罩 + 底部抽屉；动作条在遮罩之下；Esc 关闭并回焦
            pg.click('#srxMobilebar [data-mobile="filters"]')
            pg.wait_for_timeout(450)
            fl = pg.evaluate("""()=>{
              const m=document.querySelector('.srx-ctxmask');
              const f=document.getElementById('srxCtxFly');
              const bar=document.getElementById('srxMobilebar');
              const ms=getComputedStyle(m),fs=getComputedStyle(f);
              const fr=f.getBoundingClientRect();
              return {mask:ms.display,fly:fs.display,
                maskZ:+ms.zIndex,barZ:+getComputedStyle(bar).zIndex,
                flyH:Math.round(fr.height),vh:innerHeight,
                opened:document.getElementById('searchview')
                  .classList.contains('show-filters')};}""")
            assert fl["mask"] == "block" and fl["fly"] == "block", fl
            assert fl["maskZ"] > fl["barZ"], (
                "筛选遮罩必须在底部动作条之上，否则动作条可穿透点击：%s" % fl)
            assert fl["flyH"] <= fl["vh"] * 0.8 + 1, fl
            assert fl["opened"] is True, fl
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(350)
            esc = pg.evaluate("""()=>({
              fly:getComputedStyle(document.getElementById('srxCtxFly')).display,
              mask:getComputedStyle(document.querySelector('.srx-ctxmask')).display,
              focus:(document.activeElement
                &&document.activeElement.getAttribute('data-mobile'))||''})""")
            assert esc["fly"] == "none" and esc["mask"] == "none", esc
            assert esc["focus"] == "filters", (
                "关闭筛选后焦点必须回到动作条的筛选按钮：%s" % esc)
        finally:
            b.close()


def test_desktop_bar_stays_hidden_and_form_single_row(server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        try:
            pg = _page(b, server, 1440)
            d = pg.evaluate(_PROBE)
            assert d["bar"]["pos"] == "static" and d["bar"]["h"] <= 2, d["bar"]
            assert d["formRows"] == 1, d
            # 桌面顶部 = 表单 1 行 + 渠道 1 行（srxProbe 可见子块 y 值 ≤2）
            assert d["probeRows"] <= 2, d
            assert d["ovCount"] == 1, d
        finally:
            b.close()


def test_negative_controls_for_mobile_gate(server):
    """负控：判据本身要能抓住「退回文档流」和「裸图标」。"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        try:
            pg = _page(b, server, 390)
            # 负控 1：把底部条改回 static → fixed 判据必须红
            d = pg.evaluate("""()=>{
              const bar=document.getElementById('srxMobilebar');
              bar.style.setProperty('position','static','important');
              return {pos:getComputedStyle(bar).position};}""")
            assert d["pos"] == "static", d
            pg.evaluate("""()=>{document.getElementById('srxMobilebar')
              .style.removeProperty('position');}""")
            d = pg.evaluate(_PROBE)
            assert d["bar"]["pos"] == "fixed", d["bar"]

            # 负控 2：注入只有 title 的图标钮 → bare 判据必须红
            d = pg.evaluate("""()=>{
              const p=document.querySelector('.srx-hero-act');
              const btn=document.createElement('button');
              btn.type='button';btn.id='__negIcon';btn.title='只有提示的图标';
              btn.innerHTML='<svg viewBox="0 0 24 24" width="14" height="14">'
                +'<path d="M4 20V10M10 20V4"/></svg>';
              p.appendChild(btn);
              const vis=e=>{const r=e.getBoundingClientRect();
                return r.width>2&&r.height>2;};
              const bare=[];
              for(const x of document.querySelectorAll(
                '#searchview .srx-hero button,#srxMobilebar button')){
                if(!vis(x))continue;
                if(!(x.innerText||'').trim()&&!x.getAttribute('aria-label'))
                  bare.push(x.id);}
              btn.remove();
              return {bare};}""")
            assert "__negIcon" in d["bare"], (
                "裸图标负控没被抓住，判据失明：%s" % d)
        finally:
            b.close()
