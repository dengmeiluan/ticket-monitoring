# -*- coding: utf-8 -*-
"""r1135 Wave3：全站 P1 真实渲染普查 + 负控。

覆盖：
- 390 coarse 主控件有效热区 ≥36（elementFromPoint 实测，非只看盒子）
- 检索控件圆角只用令牌（4/8px 清零）
- 配置·节流窄档行高 ≤64
- 全局参数 6 个折叠段全部可达、58 字段、无重复「取值」、无横向溢出
- 10 表面 × 6 档 × 亮暗 doc dx ≤0
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

pytest.importorskip("playwright", reason="渲染门禁依赖 playwright")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None
WIDTHS = [1440, 1024, 900, 768, 390, 320]
THEMES = ["light", "dark"]

HELPERS = r"""
window.__W3 = (function(){
  function vis(el){
    if(!el||!el.isConnected) return false;
    var cs=getComputedStyle(el);
    if(cs.display==='none'||cs.visibility==='hidden'||cs.opacity==='0') return false;
    var r=el.getBoundingClientRect();
    return r.width>0.5&&r.height>0.5;
  }
  function r(el){var b=el.getBoundingClientRect();return {x:+b.x.toFixed(1),y:+b.y.toFixed(1),w:+b.width.toFixed(1),h:+b.height.toFixed(1),right:+b.right.toFixed(1),bottom:+b.bottom.toFixed(1)}}
  function eff(el){
    var b=el.getBoundingClientRect(), cx=b.left+b.width/2, cy=b.top+b.height/2;
    function hit(x,y){var e=document.elementFromPoint(x,y);return !!(e&&(e===el||el.contains(e)))}
    var hw=0,hh=0;
    for(var d=18;d>=1;d--){if(hit(cx-d,cy)&&hit(cx+d,cy)){hw=d;break}}
    for(var d2=18;d2>=1;d2--){if(hit(cx,cy-d2)&&hit(cx,cy+d2)){hh=d2;break}}
    return {effW:hw*2,effH:hh*2,w:+b.width.toFixed(0),h:+b.height.toFixed(0)};
  }
  return {vis:vis,r:r,eff:eff};
})();
"""


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def srv():
    global BASE
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失")
    port = free_port()
    BASE = "http://127.0.0.1:%d" % port
    proc = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(port)],
                            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(100):
        try:
            op.open(BASE + "/api/state", timeout=2)
            break
        except Exception:
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.fail("demo 未启动")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


@pytest.fixture
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def open_page(browser, width, theme, mobile=False):
    kw = {"viewport": {"width": width, "height": 900}}
    if mobile:
        kw.update({"is_mobile": True, "has_touch": True})
    ctx = browser.new_context(**kw)
    ctx.add_init_script("try{localStorage.setItem('jptheme','%s')}catch(e){}" % theme)
    ctx.add_init_script(HELPERS)
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="networkidle", timeout=45000)
    page.wait_for_function("typeof switchView==='function'", timeout=25000)
    return ctx, page


def test_touch_primary_controls(srv, browser):
    ctx, page = open_page(browser, 390, "light", mobile=True)
    try:
        page.evaluate("switchView('search')")
        page.wait_for_function("document.querySelectorAll('#srxRows .srx-row').length>0", timeout=25000)
        page.wait_for_timeout(600)
        bad = page.evaluate(
            """() => {
          var A=__W3, out=[];
          document.querySelectorAll('#srxProbeForm .srx-citychev,#srxProbeForm .srx-datefield,#srxGo,#srxBatchToggle,#srxPlatPick .srx-pchip').forEach(function(e){
            if(!A.vis(e)) return;
            var b=e.getBoundingClientRect();
            if(b.right<=0||b.left>=innerWidth||b.bottom<=0||b.top>=innerHeight) return;
            var cx=b.left+b.width/2, cy=b.top+b.height/2;
            var hit=document.elementFromPoint(cx,cy);
            if(!(hit&&(hit===e||e.contains(hit)))) return;
            var x=A.eff(e);
            if(x.effW<36||x.effH<36) out.push({tag:e.tagName,id:e.id,cls:(e.className||'').toString().slice(0,24),t:(e.textContent||'').trim().slice(0,10),x:x});
          });
          return out;
        }"""
        )
        assert not bad, "touch targets <36: %s" % bad[:8]
    finally:
        ctx.close()


def test_search_token_radii(srv, browser):
    ctx, page = open_page(browser, 1440, "light")
    try:
        page.evaluate("switchView('search')")
        page.wait_for_function("document.querySelectorAll('#srxRows .srx-row').length>0", timeout=25000)
        page.wait_for_timeout(500)
        bad = page.evaluate(
            """() => {
          var A=__W3, out=[];
          document.querySelectorAll('#searchview *').forEach(function(e){
            if(!A.vis(e)) return;
            var rad=getComputedStyle(e).borderRadius;
            if(rad==='4px'||rad==='8px') out.push({tag:e.tagName,cls:(e.className||'').toString().slice(0,30),rad:rad});
          });
          return out;
        }"""
        )
        assert not bad, "non-token radii: %s" % bad[:10]
    finally:
        ctx.close()


@pytest.mark.parametrize("width", [390, 320])
def test_cfg_pacing_narrow_density(srv, browser, width):
    ctx, page = open_page(browser, width, "light")
    try:
        page.evaluate("switchView('cfg');showCfgPanel('pacing')")
        # /api/strategy 真实环境 ~6s，并发门禁下会超过 25s（gate8 实测）
        page.wait_for_function("document.querySelectorAll('#cfgpacingRows .srow').length>0", timeout=45000)
        page.wait_for_timeout(900)
        d = page.evaluate(
            """() => {
          var A=__W3, rows=[...document.querySelectorAll('#cfgpacingRows .srow')].filter(A.vis);
          var hs=rows.map(function(e){return +e.getBoundingClientRect().height.toFixed(1)});
          return {n:rows.length,max:hs.length?Math.max.apply(null,hs):null,hs:hs,
                  docDx:document.documentElement.scrollWidth-document.documentElement.clientWidth};
        }"""
        )
        assert d["n"] >= 20, d
        assert d["max"] <= 64, "cfg pacing row %.1fpx > 64: %s" % (d["max"], d["hs"][:8])
        assert d["docDx"] <= 0, "cfg pacing overflow %s" % d["docDx"]
    finally:
        ctx.close()


def test_globals_folded_reachable(srv, browser):
    ctx, page = open_page(browser, 900, "light")
    try:
        page.evaluate("switchView('cfg');showCfgPanel('globals')")
        page.wait_for_function("document.querySelector('#cfgglobals .glgrid')", timeout=25000)
        page.wait_for_timeout(700)
        d = page.evaluate(
            """() => {
          var box=document.querySelector('#cfgglobals');
          var folded=[...box.querySelectorAll('.subsec.folded')];
          folded.forEach(function(e){e.click()});
          var vis=[...box.querySelectorAll('.glcell')].filter(function(e){var r=e.getBoundingClientRect();return r.width>0&&r.height>0});
          var dup=0,w=document.createTreeWalker(box,NodeFilter.SHOW_TEXT,null);
          while(w.nextNode()){if((w.currentNode.nodeValue||'').trim()==='取值')dup++}
          return {folded:folded.length,cells:vis.length,dup:dup,
                  docDx:document.documentElement.scrollWidth-document.documentElement.clientWidth};
        }"""
        )
        assert d["folded"] >= 5, d
        assert d["cells"] == 58, "globals cells=%s" % d["cells"]
        assert d["dup"] == 0, "duplicate 取值=%s" % d["dup"]
        assert d["docDx"] <= 0, "globals overflow %s" % d["docDx"]
    finally:
        ctx.close()


SURFACES = [
    ("overview", "switchView('mon');showMonTab('overview')"),
    ("specials", "switchView('mon');showMonTab('specials')"),
    ("trend", "switchView('mon');showMonTab('trend')"),
    ("watch", "switchView('mon');showMonTab('watch')"),
    ("details", "switchView('mon');showMonTab('details')"),
    ("health", "switchView('mon');showMonTab('health')"),
    ("search", "switchView('search')"),
    ("cfg-login", "switchView('cfg');showCfgPanel('login')"),
    ("cfg-users", "switchView('cfg');showCfgPanel('users')"),
    ("cfg-globals", "switchView('cfg');showCfgPanel('globals')"),
]


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("width", WIDTHS)
def test_all_surfaces_no_doc_overflow(srv, browser, width, theme):
    ctx, page = open_page(browser, width, theme)
    try:
        bad = []
        for name, expr in SURFACES:
            page.evaluate(expr)
            page.wait_for_timeout(450 if name not in ("health", "cfg-globals") else 1100)
            dx = page.evaluate("document.documentElement.scrollWidth-document.documentElement.clientWidth")
            if dx > 0:
                bad.append("%s:%s" % (name, dx))
        assert not bad, "doc overflow: %s" % bad
    finally:
        ctx.close()


# ---------- negative controls ----------

def test_negative_touch_shrink(srv, browser):
    ctx, page = open_page(browser, 390, "light", mobile=True)
    try:
        page.evaluate("switchView('search')")
        page.wait_for_timeout(700)
        page.evaluate("document.querySelector('.srx-citychev').style.cssText='width:24px!important;min-width:24px!important;height:24px!important;pointer-events:none!important'")
        x = page.evaluate("__W3.eff(document.querySelector('.srx-citychev'))")
        assert x["effW"] < 36 and x["effH"] < 36
    finally:
        ctx.close()


def test_negative_token_radius(srv, browser):
    ctx, page = open_page(browser, 1440, "light")
    try:
        page.evaluate("switchView('search')")
        page.wait_for_timeout(600)
        page.evaluate("document.querySelector('#srxGo').style.setProperty('border-radius','4px','important')")
        page.wait_for_timeout(300)
        assert page.evaluate("getComputedStyle(document.querySelector('#srxGo')).borderRadius") == "4px"
    finally:
        ctx.close()


def test_negative_cfg_pacing_height(srv, browser):
    ctx, page = open_page(browser, 390, "light")
    try:
        page.evaluate("switchView('cfg');showCfgPanel('pacing')")
        page.wait_for_function("document.querySelectorAll('#cfgpacingRows .srow').length>0", timeout=25000)
        page.wait_for_timeout(600)
        page.evaluate("""() => {var e=document.querySelector('#cfgpacingRows .srow');
          e.style.setProperty('height','86px','important');e.style.setProperty('min-height','86px','important');}""")
        h = page.evaluate("document.querySelector('#cfgpacingRows .srow').getBoundingClientRect().height")
        assert h > 64
    finally:
        ctx.close()


def test_negative_duplicate_quzhi(srv, browser):
    ctx, page = open_page(browser, 900, "light")
    try:
        page.evaluate("switchView('cfg');showCfgPanel('globals')")
        page.wait_for_timeout(900)
        page.evaluate("""() => {var d=document.createElement('div');d.textContent='取值';
          document.querySelector('#cfgglobals').appendChild(d);}""")
        n = page.evaluate("""() => {var box=document.querySelector('#cfgglobals'),n=0;
          var w=document.createTreeWalker(box,NodeFilter.SHOW_TEXT,null);
          while(w.nextNode()){if((w.currentNode.nodeValue||'').trim()==='取值')n++}return n}""")
        assert n >= 1
    finally:
        ctx.close()


def test_negative_320_overflow(srv, browser):
    ctx, page = open_page(browser, 320, "light")
    try:
        page.evaluate("switchView('mon');showMonTab('health')")
        page.wait_for_timeout(1200)
        page.evaluate("""() => {var d=document.createElement('div');d.style.cssText='width:350px;height:10px';
          document.querySelector('#hbody').appendChild(d);}""")
        assert page.evaluate("document.documentElement.scrollWidth-document.documentElement.clientWidth") > 0
    finally:
        ctx.close()
