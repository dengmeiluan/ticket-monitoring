# -*- coding: utf-8 -*-
"""r1134 Wave2：渠道健康真实渲染普查（6 档 × 亮暗）+ 负控。

覆盖 master v2.0 §8.2 第 6/7/8 项：
- 健康诊断条高度/状态链-动作间距/320 无横向溢出
- 健康矩阵 10 行、行高 ≤56、证据 ≤2 行
- 节流 10 行、行高 ≤64、右栏 280–360
每项配可证明的负控（注入旧缺陷必须判红）。
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
window.__W2 = (function(){
  function vis(el){
    if(!el||!el.isConnected) return false;
    var cs=getComputedStyle(el);
    if(cs.display==='none'||cs.visibility==='hidden'||cs.opacity==='0') return false;
    var r=el.getBoundingClientRect();
    return r.width>0.5&&r.height>0.5;
  }
  function r(el){
    if(!el) return null;
    var b=el.getBoundingClientRect();
    return {x:+b.x.toFixed(1),y:+b.y.toFixed(1),w:+b.width.toFixed(1),h:+b.height.toFixed(1),
            right:+b.right.toFixed(1),bottom:+b.bottom.toFixed(1)};
  }
  return {vis:vis,r:r};
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


def open_health(browser, width, theme):
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    ctx.add_init_script("try{localStorage.setItem('jptheme','%s')}catch(e){}" % theme)
    ctx.add_init_script(HELPERS)
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(BASE + "/", wait_until="networkidle", timeout=45000)
    page.wait_for_function("typeof showMonTab==='function'", timeout=25000)
    page.evaluate("switchView('mon');showMonTab('health')")
    # r1147：「节流与干预」默认折叠；展开后 PACE 行才有可测高度。
    page.evaluate("()=>{const f=document.getElementById('hpaceFold');"
                  "if(f)f.open=true;}")
    page.wait_for_function("document.querySelectorAll('#hbody .hrow').length>0", timeout=25000)
    page.wait_for_function("document.querySelectorAll('#paceBox .pace-row').length>0", timeout=25000)
    page.wait_for_timeout(900)
    return ctx, page, errs


def health_snapshot(page):
    return page.evaluate(
        """() => {
      var A=__W2, rows=[...document.querySelectorAll('#hbody .hrow')].filter(A.vis);
      var cap=document.querySelector('#srccap'), path=document.querySelector('#srccap .scpath'), acts=document.querySelector('#srccap .scacts');
      var hs=rows.map(function(e){return +e.getBoundingClientRect().height.toFixed(1)});
      /* r1147：分端/通路证据移入行内「详情」抽屉；行内证据摘要为 .hsum。 */
      var scopes=rows.map(function(e){var s=e.querySelector('.hsum');return s?+s.getBoundingClientRect().height.toFixed(1):0});
      var cells=rows.length?rows[0].querySelector('.hcells'):null;
      var pr=A.r(path), ar=A.r(acts);
      return {rows:rows.length, hs:hs, maxH:hs.length?Math.max.apply(null,hs):null,
              scopeMax:scopes.length?Math.max.apply(null,scopes):0, scopes:scopes,
              gridW:cells?+cells.getBoundingClientRect().width.toFixed(1):0,
              cap:A.r(cap), sameRow:!!(pr&&ar&&Math.abs((pr.y+pr.h/2)-(ar.y+ar.h/2))<12),
              gap:(pr&&ar)?+(ar.x-pr.right).toFixed(1):null,
              docDx:document.documentElement.scrollWidth-document.documentElement.clientWidth};
    }"""
    )


def pace_snapshot(page):
    return page.evaluate(
        """() => {
      var A=__W2, rows=[...document.querySelectorAll('#paceBox .pace-row')].filter(A.vis);
      var hs=rows.map(function(e){return +e.getBoundingClientRect().height.toFixed(1)});
      var side=document.querySelector('#paceBox .pace-side'), main=document.querySelector('#paceBox .pace-main');
      var maxChips=rows.reduce(function(m,e){
        var n=e.querySelectorAll('.glip,.chip,.haltc,.pchip').length; return Math.max(m,n)},0);
      return {rows:rows.length, hs:hs, maxH:hs.length?Math.max.apply(null,hs):null,
              side:A.r(side), main:A.r(main), maxChips:maxChips,
              docDx:document.documentElement.scrollWidth-document.documentElement.clientWidth};
    }"""
    )


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("width", WIDTHS)
def test_health_contract(srv, browser, width, theme):
    ctx, page, errs = open_health(browser, width, theme)
    try:
        h = health_snapshot(page)
        p = pace_snapshot(page)
        assert not errs, errs
        assert h["rows"] == 10, "health rows=%s" % h["rows"]
        if width <= 760:
            # r1087：窄档 24h 格带必须换到名称下方并吃满卡宽，行高 60–90。
            assert 60 <= h["maxH"] <= 90, "narrow health row %.1fpx not in 60-90: %s" % (h["maxH"], h["hs"])
            assert h["gridW"] >= 230, "narrow 24h grid width %.1f < 230" % h["gridW"]
        else:
            assert h["maxH"] <= 56, "health row %.1fpx > 56: %s" % (h["maxH"], h["hs"])
        assert h["scopeMax"] <= 32, "evidence >2 lines: %s" % h["scopes"]
        assert h["cap"]["h"] <= (130 if width > 760 else 180), "diag cap %.1fpx too tall" % h["cap"]["h"]
        assert h["docDx"] <= 0, "health doc overflow %s" % h["docDx"]
        if width > 760:
            assert h["sameRow"], "path/actions not on one row"
            assert h["gap"] <= 24, "path-actions gap %.1f > 24" % h["gap"]
        assert p["rows"] == 10, "pacing rows=%s (default must show 10)" % p["rows"]
        assert p["maxH"] <= 64, "pacing row %.1fpx > 64: %s" % (p["maxH"], p["hs"])
        assert p["maxChips"] <= 4, "pacing row chips=%s > 4" % p["maxChips"]
        assert p["docDx"] <= 0, "pacing doc overflow %s" % p["docDx"]
        if width >= 1200:
            # r1454：节流区单列，逐渠道占满整宽；侧栏不再是 340px 窄轨。
            assert p["main"]["w"] >= 1000, "pace main width=%s" % p["main"]["w"]
            assert p["side"]["w"] >= p["main"]["w"] - 1, "pace side not full-width: %s vs %s" % (p["side"]["w"], p["main"]["w"])
    finally:
        ctx.close()


# ---------- negative controls ----------

def test_negative_health_third_evidence(browser):
    ctx, page, _ = open_health(browser, 1024, "light")
    try:
        # r1141/r1147：行内证据已收成单行、详情进抽屉；负控给行加一条
        # 整宽内容（第三行），并在同一次求值里量行高，证明 maxH 会红。
        got = page.evaluate(
            """() => {var r=document.querySelector('#hbody .hrow');
              if(!r)return -1;
              var d=document.createElement('div');
              d.style.cssText='grid-column:1/-1;height:18px;width:100%';
              d.textContent='x';r.appendChild(d);
              var hs=[...document.querySelectorAll('#hbody .hrow')]
                .map(function(e){return +e.getBoundingClientRect().height.toFixed(1)});
              return Math.max.apply(null,hs);}"""
        )
        assert got > 56, got
    finally:
        ctx.close()


def test_negative_pace_row_height(browser):
    ctx, page, _ = open_health(browser, 900, "light")
    try:
        page.evaluate(
            """() => {var r=document.querySelector('#paceBox .pace-row');
              r.style.setProperty('height','91px','important');r.style.setProperty('min-height','91px','important');}"""
        )
        assert pace_snapshot(page)["maxH"] > 64
    finally:
        ctx.close()


def test_negative_320_overflow(browser):
    ctx, page, _ = open_health(browser, 320, "light")
    try:
        page.evaluate(
            """() => {var d=document.createElement('div');d.style.cssText='width:350px;height:10px';
              document.querySelector('#hbody').appendChild(d);}"""
        )
        assert health_snapshot(page)["docDx"] > 0
    finally:
        ctx.close()


def test_negative_pace_four_rows(browser):
    ctx, page, _ = open_health(browser, 900, "light")
    try:
        page.evaluate("document.querySelector('#paceBox .pace-ch').classList.remove('all')")
        assert pace_snapshot(page)["rows"] < 10
    finally:
        ctx.close()
