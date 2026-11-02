# -*- coding: utf-8 -*-
"""r795 门禁：概览收起后，屏上必须**还有**一个可见入口能把它放回来。

来由（2026-11-01 真渲染复现）：2026-10-31 把价带改成可选项——收起时整条
`#srxOverview` `display:none`，入口挪到工具区 `#srxOvTool`（带 data-sec，
随「更多工具」收纳）。三条隐藏规则叠加后，**三档宽度的收起态可见入口数都是
0**：价带头里那颗 `#srxOvHero` 随价带一起隐藏，「价带」开关又躺在没展开的
「更多工具」里。用户收起概览后再也打不开——只能靠猜、或刷新页面。

判据（真浏览器量几何，不看源码字面）：
1. 1512 / 1000 / 760 / 430 四档，收起态至少一个入口 `offsetParent!==null`、
   宽高 > 0、且在视口内；
2. 该入口文案说的是**动作**（「展开概览」），不是「价带」这种名词——名词会
   被读成配置项；
3. 负控：真点它一次，收起态必须翻转且天数条重新可见（画得像但接错函数会红）。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

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


def _open_search(pg):
    pg.goto("http://127.0.0.1:%d/" % pg._port, wait_until="domcontentloaded",
            timeout=30000)
    pg.wait_for_timeout(2400)
    pg.evaluate("switchView('search')")
    pg.wait_for_timeout(700)


@pytest.mark.parametrize("width", [1512, 1000, 760, 430])
def test_collapsed_overview_still_has_a_way_back(server, width):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        try:
            pg = b.new_page(viewport={"width": width, "height": 950})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg._port = server
            _open_search(pg)
            d = pg.evaluate(_PROBE)
            assert not errs, errs[:3]
            assert d["collapsed"] is True, d
            assert d["days"] is False, (
                "%d 档收起态天数条仍在，收起没真的收正文：%s" % (width, d))
            assert d["shown"], (
                "%d 档收起概览后**没有任何可见入口**——用户再也打不开"
                "（价带头随价带隐藏，工具区开关又被「更多工具」收走）：%s"
                % (width, d))
            txt = " ".join(x["t"] for x in d["shown"])
            assert "展开概览" in txt, (
                "%d 档唯一的入口文案是「%s」，名词会被读成配置项，"
                "用户不知道点它能把概览放回来" % (width, txt))
        finally:
            b.close()


def test_entry_actually_restores_the_overview(server):
    """负控：只查「按钮可见 + 文案对」会漏掉接错函数的情形。"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        try:
            pg = b.new_page(viewport={"width": 1000, "height": 950})
            pg._port = server
            _open_search(pg)
            out = pg.evaluate("""()=>{
             const v=document.getElementById('searchview');
             if(!v.classList.contains('srx-ov-collapsed'))srxToggleOverview();
             const btn=[document.getElementById('srxOvTool'),
                        document.getElementById('srxOvHero')]
               .find(e=>e&&e.offsetParent!==null
                    &&e.getBoundingClientRect().width>0);
             if(!btn)return {err:'no visible entry'};
             btn.click();
             const days=document.getElementById('srxBandBody');
             return {collapsed:v.classList.contains('srx-ov-collapsed'),
                     days:!!days&&getComputedStyle(days).display!=='none'
                       &&days.getBoundingClientRect().height>0,
                     txt:(btn.textContent||'').trim()};}""")
            assert not out.get("err"), out
            assert out["collapsed"] is False, out
            assert out["days"] is True, "点了入口但正文没回来：%s" % out
            assert out["txt"] == "收起概览", out
        finally:
            b.close()
