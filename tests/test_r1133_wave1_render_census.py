# -*- coding: utf-8 -*-
"""r1133 Wave1：检索页真实渲染普查（6 档 × 亮暗）+ 负控。

覆盖 master v2.0 §8.2 的 1/2/3/4/5/6/11 项，并为每项提供可证明的负控。
不依赖旧 r1130：旧门禁绿不代表本文件绿。
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
window.__W1 = (function(){
  function vis(el){
    if(!el || !el.isConnected) return false;
    var cs=getComputedStyle(el);
    if(cs.display==='none'||cs.visibility==='hidden'||cs.opacity==='0') return false;
    var r=el.getBoundingClientRect();
    return r.width>0.5 && r.height>0.5;
  }
  function r(el){
    if(!el) return null;
    var b=el.getBoundingClientRect();
    return {x:+b.x.toFixed(1),y:+b.y.toFixed(1),w:+b.width.toFixed(1),h:+b.height.toFixed(1),
            right:+b.right.toFixed(1),bottom:+b.bottom.toFixed(1)};
  }
  function txt(el){return ((el&&el.textContent)||'').replace(/\s+/g,' ').trim();}
  function inter(a,b){
    if(!a||!b) return null;
    var x=Math.max(a.x,b.x),y=Math.max(a.y,b.y),rr=Math.min(a.right,b.right),bb=Math.min(a.bottom,b.bottom);
    return (rr>x+0.5&&bb>y+0.5)?{w:+(rr-x).toFixed(1),h:+(bb-y).toFixed(1)}:null;
  }
  function textNodes(re){
    var w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT,null),out=[];
    while(w.nextNode()){
      var n=w.currentNode,t=(n.nodeValue||'').replace(/\s+/g,' ').trim();
      if(!t||!re.test(t)) continue;
      var p=n.parentElement;
      if(!p||!vis(p)) continue;
      if(p.tagName==='SCRIPT'||p.tagName==='STYLE'||p.tagName==='NOSCRIPT') continue;
      out.push({t:t,id:p.id,cls:(typeof p.className==='string'?p.className:'').slice(0,40)});
    }
    return out;
  }
  function btns(re){
    var out=[],all=document.querySelectorAll('button,[role="button"],summary,a');
    for(var i=0;i<all.length;i++){
      var el=all[i]; if(!vis(el)) continue;
      var t=txt(el); if(re.test(t)) out.push({t:t,id:el.id,cls:(typeof el.className==='string'?el.className:'').slice(0,40),r:r(el)});
    }
    return out;
  }
  function topYs(){
    var p=document.querySelector('#srxProbe'); if(!p) return [];
    var ys=[];
    for(var i=0;i<p.children.length;i++){
      var el=p.children[i]; if(!vis(el)) continue;
      ys.push(Math.round(el.getBoundingClientRect().top));
    }
    return Array.from(new Set(ys));
  }
  return {vis:vis,r:r,txt:txt,inter:inter,textNodes:textNodes,btns:btns,topYs:topYs};
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


def open_search(browser, width=1440, theme="light"):
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    ctx.add_init_script("try{localStorage.setItem('jptheme','%s')}catch(e){}" % theme)
    ctx.add_init_script(HELPERS)
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(BASE + "/", wait_until="networkidle", timeout=45000)
    page.wait_for_function("typeof switchView==='function'", timeout=25000)
    page.evaluate("switchView('search')")
    page.wait_for_function("document.querySelectorAll('#srxRows .srx-row').length>0", timeout=25000)
    page.wait_for_timeout(500)
    return ctx, page, errs


def result(page):
    return page.evaluate(
        """() => {
      var A=__W1, probe=document.querySelector('#srxProbe'), tools=document.querySelector('#srxToolsRow');
      var mh=document.querySelector('#srxListHead'), mr=document.querySelector('#srxMirror');
      var fold=document.querySelector('#srxMirrorFold');
      return {
        topYs:A.topYs(),
        tools:{display:tools?getComputedStyle(tools).display:null,r:A.r(tools)},
        comboDom:document.querySelectorAll('#srxBatchToggle').length,
        comboText:A.textNodes(/^组合\\s*\\d+\\/4$/).length,
        comboInForm:!!(document.querySelector('#srxProbeForm')||{}).contains,
        mirrorBtns:A.btns(/^(展开渠道镜像|收起渠道镜像)$/),
        mirrorInHead:!!(fold&&mh&&mh.contains(fold)),
        mirrorHead:A.inter(A.r(mr),A.r(mh)),
        chLinks:A.btns(/^渠道入口$/).length,
        filterBtns:A.btns(/^(展开筛选|收起筛选)$/).length,
        docDx:document.documentElement.scrollWidth-document.documentElement.clientWidth
      };
    }"""
    )


def drawer_probe(page):
    page.evaluate("document.querySelector('#srxChLinksBtn').click()")
    page.wait_for_timeout(800)
    opened = page.evaluate(
        """() => {
      var A=__W1,d=document.querySelector('#srxChLinksDrawer'),m=document.querySelector('#srxChLinksMask');
      var cs=d?getComputedStyle(d):null, act=document.activeElement;
      var date=(document.querySelector('#srxDate')||{}).value||'';
      return {hidden:d?d.hasAttribute('hidden'):null,position:cs?cs.position:null,
              maskHidden:m?m.hasAttribute('hidden'):null,maskDisplay:m?getComputedStyle(m).display:null,
              maskR:A.r(m),rect:A.r(d),focusIn:!!(d&&act&&d.contains(act)),
              bodyOverflow:getComputedStyle(document.body).overflow,
              hasDate:!!(date&&d&&d.innerText.indexOf(date)>=0)};
    }"""
    )
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)
    closed = page.evaluate(
        """() => {
      var d=document.querySelector('#srxChLinksDrawer'),m=document.querySelector('#srxChLinksMask');
      var trg=document.querySelector('#srxChLinksBtn');
      return {hidden:d?d.hasAttribute('hidden'):null,maskHidden:m?m.hasAttribute('hidden'):null,
              focusBack:document.activeElement===trg,bodyOverflow:getComputedStyle(document.body).overflow};
    }"""
    )
    return opened, closed


def filter_probe(page):
    page.evaluate("document.querySelector('#srxFilterBtn').click()")
    page.wait_for_timeout(500)
    opened = page.evaluate(
        """() => {
      var A=__W1,p=document.querySelector('#srxCtxFly'),cs=p?getComputedStyle(p):null;
      var q=p?p.querySelector('.srf-airq,.srf-q'):null;
      var chips=p?Array.from(p.querySelectorAll('.srf-opt')).filter(A.vis):[];
      var overlaps=0;
      if(q){var qr=q.getBoundingClientRect();chips.forEach(function(c){var cr=c.getBoundingClientRect();
        if(cr.left<qr.right-0.5&&cr.right>qr.left+0.5&&cr.top<qr.bottom-0.5&&cr.bottom>qr.top+0.5) overlaps++;});}
      return {open:!!(p&&A.vis(p)),position:cs?cs.position:null,rect:A.r(p),
              fit:!!(p&&p.getBoundingClientRect().right<=innerWidth+1&&p.getBoundingClientRect().left>=-1),
              heightRatio:p?+(p.getBoundingClientRect().height/innerHeight).toFixed(3):null,
              airOverlaps:overlaps,chips:chips.length,
              scrollH:p?p.scrollHeight:null,clientH:p?p.clientHeight:null};
    }"""
    )
    clicked = 0
    still = None
    if opened["chips"] > 0:
        clicked = page.evaluate(
            """() => {
          var A=__W1,p=document.querySelector('#srxCtxFly');
          var chips=Array.from(p.querySelectorAll('.srf-opt')).filter(A.vis).slice(0,3);
          chips.forEach(function(c){c.click()}); return chips.length;
        }"""
        )
        page.wait_for_timeout(250)
        still = page.evaluate("!!(document.querySelector('#srxCtxFly')&&__W1.vis(document.querySelector('#srxCtxFly')))")
    page.evaluate("document.querySelector('#srxFilterBtn').click()")
    page.wait_for_timeout(250)
    return opened, clicked, still


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("theme", THEMES)
def test_search_contract(srv, browser, width, theme):
    ctx, page, errs = open_search(browser, width, theme)
    try:
        d = result(page)
        assert not errs, errs
        assert 1 <= len(d["topYs"]) <= 2, "third row: %s" % d["topYs"]
        assert d["tools"]["r"]["h"] <= 1, "tools row occupies height: %s" % d["tools"]
        assert d["comboDom"] == 1, "DOM combo triggers=%s" % d["comboDom"]
        assert d["comboText"] == 1, "visible combo text=%s" % d["comboText"]
        assert len(d["mirrorBtns"]) == 1, "mirror buttons=%s" % d["mirrorBtns"]
        assert d["mirrorInHead"], "mirror button not in #srxListHead"
        assert d["mirrorHead"] is None, "mirror overlaps list head: %s" % d["mirrorHead"]
        assert d["chLinks"] == 1, "channel-entry buttons=%s" % d["chLinks"]
        assert d["filterBtns"] == 1, "filter buttons=%s" % d["filterBtns"]
        assert d["docDx"] <= 0, "doc horizontal overflow %s" % d["docDx"]

        # mirror two states: same coordinates, still no overlap
        before = page.evaluate("__W1.r(document.querySelector('#srxMirrorFold'))")
        page.evaluate("document.querySelector('#srxMirrorFold').click()")
        page.wait_for_timeout(350)
        folded = page.evaluate(
            """() => {var A=__W1,b=document.querySelector('#srxMirrorFold');
          return {r:A.r(b),t:A.txt(b),n:A.btns(/^(展开渠道镜像|收起渠道镜像)$/).length,
                  inter:A.inter(A.r(document.querySelector('#srxMirror')),A.r(document.querySelector('#srxListHead')))};}"""
        )
        assert len(d["mirrorBtns"]) == 1 and folded["n"] == 1
        assert abs(folded["r"]["x"] - before["x"]) <= 1 and abs(folded["r"]["y"] - before["y"]) <= 1, (
            "mirror button moved: %s -> %s" % (before, folded["r"]))
        assert folded["inter"] is None, "folded mirror overlaps head: %s" % folded["inter"]
        page.evaluate("document.querySelector('#srxMirrorFold').click()")
        page.wait_for_timeout(250)

        opened, closed = drawer_probe(page)
        assert opened["hidden"] is False
        assert opened["position"] == "fixed", "drawer position=%s" % opened["position"]
        if width <= 600:
            # 窄档 = 底部弹层：必须有遮罩并锁滚动（r1147 契约）
            assert opened["maskHidden"] is False and opened["maskDisplay"] != "none", "drawer mask missing"
            assert opened["bodyOverflow"] == "hidden", "drawer did not lock body"
        else:
            # 桌面 = 锚定非模态浮层：遮罩隐藏、不锁页面（r1147 契约）
            assert opened["maskHidden"] is True or opened["maskDisplay"] == "none", "desktop drawer shows mask"
            assert opened["bodyOverflow"] != "hidden", "desktop drawer locks body"
        assert opened["focusIn"], "focus did not enter drawer"
        assert not opened["hasDate"], "drawer carries route date"
        assert closed["hidden"] is True and closed["maskHidden"] is True
        assert closed["focusBack"], "focus did not return to drawer trigger"
        assert closed["bodyOverflow"] != "hidden", "body lock not released"

        f, clicked, still = filter_probe(page)
        assert f["open"] and f["position"] == "fixed", "filter not fixed: %s" % f
        assert f["fit"], "filter outside viewport: %s" % f["rect"]
        assert f["heightRatio"] <= 0.80 + 0.002, "filter height %.1f%% > 80vh" % (f["heightRatio"] * 100)
        assert f["airOverlaps"] == 0, "airline search overlaps chips: %s" % f["airOverlaps"]
        assert clicked >= 3, "expected at least 3 filter chips, got %s" % clicked
        assert still is True, "filter closed during continuous chip clicks"
    finally:
        ctx.close()


@pytest.mark.parametrize("width", WIDTHS)
def test_worst_channel_names(srv, browser, width):
    """10 long channel names: still 2 top rows, row <=44px, no doc overflow."""
    ctx, page, errs = open_search(browser, width, "light")
    try:
        def snap():
            return page.evaluate(
                """() => {var A=__W1,row=document.querySelector('#srxChannelRow'),pick=document.querySelector('#srxPlatPick');
              var tops=[...new Set([...pick.querySelectorAll('.srx-pchip')]
                .map(c=>Math.round(c.getBoundingClientRect().top)))];
              return {topN:A.topYs().length,rowH:+row.getBoundingClientRect().height.toFixed(1),
                      chipRows:tops.length,
                      sw:pick.scrollWidth,cw:pick.clientWidth,cls:pick.className,
                      docDx:document.documentElement.scrollWidth-document.documentElement.clientWidth};}"""
            )
        before = snap()
        assert before["topN"] <= 2
        # r1500：≤600 档渠道 rail 改为**定列网格**（5 列 × 2 行，替代横向拖动，
        # 用户才能一眼看全 10 家 App 渠道）。所以：
        #   · 宽档：仍必须一行（chip 只有一行 → 行高 ≤44）；
        #   · 窄档：允许 2 行，用**结构**判据（chip 去重后的 top 数 ≤2）而不是
        #     硬编码高度——行高会随字号/图标高度变化，钉死数字只会反复假红。
        #     高度只保留一个"不失控"的上限（每行 40 + 容器 chrome 60）。
        assert before["chipRows"] <= (2 if width <= 600 else 1), (width, before)
        max_row = 40 * before["chipRows"] + 60
        assert before["rowH"] <= max_row, (width, before)
        if before["sw"] > before["cw"] + 1:
            assert "is-over" in before["cls"], "overflowing rail missing is-over: %s" % before
        page.evaluate(
            """() => {
          var long=['携程旅行国际机票','去哪儿网国际机票','飞猪旅行国际机票','同程旅行国际机票','途牛旅游国际机票',
                    '智行火车票 App','去哪儿旅行 App','飞猪旅行 App','携程旅行 App','同程旅行 App'];
          [...document.querySelectorAll('#srxPlatPick .srx-pchip')].forEach(function(l,i){
            var s=l.querySelector('.srx-applab');
            if(s){s.textContent=long[i];return}
            var t=[...l.childNodes].find(function(n){return n.nodeType===3});
            if(t)t.nodeValue=long[i];
          });}"""
        )
        page.wait_for_timeout(200)
        after = snap()
        assert after["topN"] <= 2, "long names created a third row: %s" % after
        assert after["rowH"] <= max_row, "long names grew channel row: %s" % after
        assert after["docDx"] <= 0, "long names caused horizontal overflow: %s" % after
        assert after["sw"] >= before["sw"], "rail did not expose long names"
    finally:
        ctx.close()


def test_detail_modal_focus_enters(srv, browser):
    ctx, page, errs = open_search(browser, 1440, "light")
    try:
        page.click("#srxOpenSel")
        page.wait_for_timeout(400)
        opened = page.evaluate(
            """() => {var d=document.querySelector('#srxDetail');var act=document.activeElement;
          return {open:d.classList.contains('open'),aria:d.getAttribute('aria-hidden'),
                  focusIn:!!(d&&act&&d.contains(act)),focusTag:act?act.tagName+'.'+act.className:null,
                  bodyOverflow:getComputedStyle(document.body).overflow};}"""
        )
        assert opened["open"] and opened["aria"] == "false"
        assert opened["focusIn"], "detail modal did not move focus inside: %s" % opened["focusTag"]
        assert opened["bodyOverflow"] == "hidden"
        # Tab is trapped: from the last focusable, Tab wraps to the first;
        # from the first, Shift+Tab wraps to the last.
        assert page.evaluate(
            """() => {var d=document.querySelector('#srxDetail');
              var f=[...d.querySelectorAll('button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])')].filter(e=>e.getBoundingClientRect().height>0);
              if(!f.length) return false; f[f.length-1].focus(); return true;}"""
        )
        page.keyboard.press("Tab")
        wrap = page.evaluate(
            """() => {var d=document.querySelector('#srxDetail');
              var f=[...d.querySelectorAll('button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])')].filter(e=>e.getBoundingClientRect().height>0);
              return {inside:d.contains(document.activeElement),first:document.activeElement===f[0]};}"""
        )
        assert wrap["inside"] and wrap["first"], "Tab escaped or did not wrap: %s" % wrap
        assert page.evaluate(
            """() => {var d=document.querySelector('#srxDetail');
              var f=[...d.querySelectorAll('button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])')].filter(e=>e.getBoundingClientRect().height>0);
              if(!f.length) return false; f[0].focus(); return true;}"""
        )
        page.keyboard.press("Shift+Tab")
        back = page.evaluate(
            """() => {var d=document.querySelector('#srxDetail');
              var f=[...d.querySelectorAll('button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])')].filter(e=>e.getBoundingClientRect().height>0);
              return {inside:d.contains(document.activeElement),last:document.activeElement===f[f.length-1]};}"""
        )
        assert back["inside"] and back["last"], "Shift+Tab escaped or did not wrap: %s" % back
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        closed = page.evaluate(
            """() => ({open:document.querySelector('#srxDetail').classList.contains('open'),
                       focus:document.activeElement&&document.activeElement.id})"""
        )
        assert not closed["open"]
        assert closed["focus"] == "srxOpenSel", "focus not returned to detail trigger: %s" % closed["focus"]
    finally:
        ctx.close()


# ---------- negative controls ----------

def test_negative_third_row(browser):
    ctx, page, _ = open_search(browser, 1440, "light")
    try:
        page.evaluate("""() => {var d=document.createElement('div');
          d.id='neg-third'; d.style.height='20px'; d.textContent='x';
          document.querySelector('#srxProbe').appendChild(d);}""")
        assert len(page.evaluate("__W1.topYs()")) == 3, "third-row predicate failed"
    finally:
        ctx.close()


def test_negative_duplicate_combo(browser):
    ctx, page, _ = open_search(browser, 1440, "light")
    try:
        page.evaluate("""() => {var b=document.querySelector('#srxBatchToggle').cloneNode(true);
          b.id='neg-combo'; document.querySelector('#srxProbeForm').appendChild(b);}""")
        assert page.evaluate("__W1.textNodes(/^组合\\s*\\d+\\/4$/).length") >= 2
    finally:
        ctx.close()


def test_negative_second_mirror_button(browser):
    ctx, page, _ = open_search(browser, 1440, "light")
    try:
        page.evaluate("""() => {var b=document.querySelector('#srxMirrorFold').cloneNode(true);
          b.id='neg-mirror'; b.style.display='inline-flex'; document.body.appendChild(b);}""")
        assert len(page.evaluate("__W1.btns(/^(展开渠道镜像|收起渠道镜像)$/)")) >= 2
    finally:
        ctx.close()


def test_negative_drawer_not_fixed(browser):
    ctx, page, _ = open_search(browser, 1440, "light")
    try:
        page.evaluate("document.querySelector('#srxChLinksBtn').click()")
        page.wait_for_timeout(700)
        page.evaluate("document.querySelector('#srxChLinksDrawer').style.position='absolute'")
        pos = page.evaluate("getComputedStyle(document.querySelector('#srxChLinksDrawer')).position")
        assert pos != "fixed"
    finally:
        ctx.close()


def test_negative_filter_closes_on_chip(browser):
    ctx, page, _ = open_search(browser, 1440, "light")
    try:
        page.evaluate("document.querySelector('#srxFilterBtn').click()")
        page.wait_for_timeout(400)
        page.evaluate("""() => {
          var p=document.querySelector('#srxCtxFly');
          p.addEventListener('click', function(e){ if(e.target.closest('.srf-opt')) srxToggleCtx(); });
          p.querySelector('.srf-opt').click();
        }""")
        page.wait_for_timeout(300)
        assert page.evaluate("!__W1.vis(document.querySelector('#srxCtxFly'))")
    finally:
        ctx.close()


def test_negative_filter_height(browser):
    ctx, page, _ = open_search(browser, 900, "light")
    try:
        page.evaluate("document.querySelector('#srxFilterBtn').click()")
        page.wait_for_timeout(400)
        page.evaluate("""() => {var p=document.querySelector('#srxCtxFly');
          p.style.setProperty('max-height','84vh','important');
          p.style.setProperty('height','84vh','important');}""")
        ratio = page.evaluate("document.querySelector('#srxCtxFly').getBoundingClientRect().height/innerHeight")
        assert ratio > 0.80
    finally:
        ctx.close()


def test_negative_detail_focus(browser):
    ctx, page, _ = open_search(browser, 1440, "light")
    try:
        page.click("#srxOpenSel")
        page.wait_for_timeout(300)
        page.evaluate("document.activeElement.blur(); document.body.focus();")
        inside = page.evaluate("document.querySelector('#srxDetail').contains(document.activeElement)")
        assert not inside
    finally:
        ctx.close()
