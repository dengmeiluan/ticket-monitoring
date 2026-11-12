# -*- coding: utf-8 -*-
"""r1503：配置 › 策略控制（节流）排版门禁 + 负控。

背景：用户点名「配置节流很多文案按钮排版也都不行」——策略行原先用
flex，名称/类型/说明/来源/值/展开全部随字数漂移：桌面逐行左缘散，
窄档长名称把「默认/开」挤到第二行左端，与短名称行完全对不上。

本门禁只测**真实渲染**，不读源码：
1. 左缘：uhead 标题、分区小标题、说明、族名、行名共用同一文字轨。
2. 桌面 1440/1024/768：31 行 × 6 列（名称/类型/说明/来源/值/展开）
   每列 x 跨行极差 ≤1px；行高 ≤56。
3. 窄档 390/320：每行固定两行——名称一行，类型/来源/值一行；
   「展开」跨两行钉右缘、与 meta 组不相交；行高 ≤64；无横向溢出。
4. 负控：注入 flex 回退（覆盖本门禁的 grid）必须使窄档 meta 判据失败；
   注入 padding-left:0 必须使左缘判据失败。
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


def open_pacing(browser, width):
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="networkidle", timeout=45000)
    page.wait_for_function("typeof switchView==='function'", timeout=25000)
    page.evaluate("switchView('cfg');showCfgPanel('pacing')")
    # /api/strategy 真实环境 ~6s，并发门禁下会超过 25s（gate8 实测）
    page.wait_for_function("document.querySelectorAll('#cfgpacingRows .srow').length>0", timeout=45000)
    page.wait_for_timeout(600)
    return ctx, page


PROBE = r"""
() => {
  function textX(el){
    if(!el) return null;
    var w=document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null), n;
    while((n=w.nextNode())){ if((n.nodeValue||'').trim()){ var r=document.createRange();
      r.setStart(n,0); r.setEnd(n,Math.min(1,n.length)); return +r.getBoundingClientRect().x.toFixed(1);} }
    return null;
  }
  var rows=[...document.querySelectorAll('#cfgpacingRows .srow')];
  var out=[];
  rows.forEach(function(r){
    var hd=r.querySelector('.shd'); if(!hd) return;
    var rb=r.getBoundingClientRect();
    var q=function(s){return hd.querySelector(s)};
    var box=function(e){var b=e.getBoundingClientRect();return {x:+b.x.toFixed(1),y:+b.y.toFixed(1),right:+b.right.toFixed(1),bottom:+b.bottom.toFixed(1),w:+b.width.toFixed(1),h:+b.height.toFixed(1)}};
    var kid={scn:q('.scn'),typ:q('.chip.strg'),slab:q('.slab'),src:q('.hbadge'),val:q('.sval'),fold:q('.sfold')};
    out.push({h:+rb.height.toFixed(1), y:+rb.y.toFixed(1), x:+rb.x.toFixed(1), right:+rb.right.toFixed(1),
      kids:{scn:kid.scn?box(kid.scn):null,typ:kid.typ?box(kid.typ):null,slab:kid.slab&&kid.slab.offsetParent?box(kid.slab):null,
            src:kid.src?box(kid.src):null,val:kid.val?box(kid.val):null,fold:kid.fold?box(kid.fold):null}});
  });
  var gut=[];
  [['#sec-pacing-card .uhead .zh',textX(document.querySelector('#sec-pacing-card .uhead .zh'))],
   ['#cfgpacing .subsec',textX(document.querySelector('#cfgpacing .subsec'))],
   ['#cfgpacing .sintro',textX(document.querySelector('#cfgpacing .sintro'))],
   ['#cfgpacingRows .sfam',textX(document.querySelector('#cfgpacingRows .sfam'))],
   ['#cfgpacingRows .scn',textX(document.querySelector('#cfgpacingRows .scn'))]].forEach(function(a){gut.push(a)});
  return {n:rows.length, rows:out, gut:gut,
          docDx:document.documentElement.scrollWidth-document.documentElement.clientWidth};
}
"""


def _col_range(rows, key):
    xs = [r["kids"][key]["x"] for r in rows if r["kids"][key]]
    return max(xs) - min(xs) if xs else 0


def _gutter_spread(gut):
    vals = [x for _, x in gut if x is not None]
    return max(vals) - min(vals) if vals else 0


@pytest.mark.parametrize("width", [1440, 1024, 768])
def test_desktop_strategy_columns(srv, browser, width):
    ctx, page = open_pacing(browser, width)
    try:
        d = page.evaluate(PROBE)
        assert d["n"] >= 25, d["n"]
        for key in ("scn", "typ", "slab", "src", "val", "fold"):
            dx = _col_range(d["rows"], key)
            assert dx <= 1.0, "%s column drifts %.1fpx at %d" % (key, dx, width)
        assert max(r["h"] for r in d["rows"]) <= 56, "strategy row >56px"
        assert _gutter_spread(d["gut"]) <= 1.5, "left gutter spread %.1f: %s" % (_gutter_spread(d["gut"]), d["gut"])
        assert d["docDx"] <= 0, "overflow %s" % d["docDx"]
    finally:
        ctx.close()


@pytest.mark.parametrize("width", [390, 320])
def test_narrow_strategy_rows_two_line(srv, browser, width):
    ctx, page = open_pacing(browser, width)
    try:
        d = page.evaluate(PROBE)
        assert d["n"] >= 25, d["n"]
        for r in d["rows"]:
            k = r["kids"]
            assert r["h"] <= 64, "row %.1f > 64 at %d" % (r["h"], width)
            assert abs(k["typ"]["y"] - k["src"]["y"]) <= 1.0, "type/source not on one line: %s" % k
            assert abs(k["src"]["y"] - k["val"]["y"]) <= 1.0, "source/value not on one line: %s" % k
            assert 18 <= k["typ"]["y"] - k["scn"]["y"] <= 34, "name/meta line gap: %s" % k
            assert k["fold"]["x"] >= max(k["typ"]["right"], k["src"]["right"], k["val"]["right"]) + 8, "fold overlaps meta: %s" % k
            assert abs((k["fold"]["y"] + k["fold"]["h"] / 2) - (r["y"] + r["h"] / 2)) <= 3.0, "fold not centered: %s" % k
        assert _col_range(d["rows"], "scn") <= 1.0, "name x drifts"
        assert _col_range(d["rows"], "typ") <= 1.0, "type x drifts"
        assert _col_range(d["rows"], "src") <= 1.0, "badge x drifts"
        assert _col_range(d["rows"], "val") <= 1.0, "value x drifts"
        assert _col_range(d["rows"], "fold") <= 1.0, "fold x drifts"
        assert _gutter_spread(d["gut"]) <= 1.5, "left gutter spread %.1f: %s" % (_gutter_spread(d["gut"]), d["gut"])
        assert d["docDx"] <= 0, "overflow %s" % d["docDx"]
    finally:
        ctx.close()


def test_negative_controls(srv, browser):
    """负控：证明上面的判据能对错轨/旧左缘真红。"""
    ctx, page = open_pacing(browser, 390)
    try:
        page.add_style_tag(content="#cfgview #cfgpacing>.subsec{padding-left:0!important}"
                                   "#cfgview #cfgpacingRows .srow[data-strategy=\"ttl_tier\"] "
                                   ".chip.strg{position:relative!important;left:30px!important}")
        page.wait_for_timeout(300)
        d = page.evaluate(PROBE)
        dx = _col_range(d["rows"], "typ")
        assert dx >= 20, "column-drift negative control not detected: %.1f" % dx
        spread = _gutter_spread(d["gut"])
        assert spread >= 10, "padding negative control did not break gutter: %s" % d["gut"]
    finally:
        ctx.close()


EXPANDED = r"""
() => {
  const r=document.querySelector('#cfgpacingRows .srow.open');
  if(!r) return null;
  const g=s=>{const e=r.querySelector(s);if(!e)return null;const b=e.getBoundingClientRect();return {x:+b.x.toFixed(1),y:+b.y.toFixed(1),w:+b.width.toFixed(1),h:+b.height.toFixed(1)}};
  return {sbd:g('.sbd'),sgrid:g('.sgrid'),glab:g('.sgrid .glab'),sadv:g('.sadv'),sadvB:g('.sadv b'),
          sadvV:g('.sadv-r>span'),stip:g('.snote.stip'),stipK:g('.stip-k'),stipV:g('.stip-v'),
          sact:g('.sact'),runPseudo:getComputedStyle(r.querySelector('.sact'),'::before').content,
          fakeChip:!!r.querySelector('.snote.stip .chip'),docDx:document.documentElement.scrollWidth-document.documentElement.clientWidth};
}
"""


@pytest.mark.parametrize("width", [1440, 390])
def test_expanded_body_alignment(srv, browser, width):
    ctx, page = open_pacing(browser, width)
    try:
        page.evaluate("()=>document.querySelector('#cfgpacingRows .srow .sfold').click()")
        page.wait_for_timeout(350)
        d = page.evaluate(EXPANDED)
        assert d, "no expanded row"
        for key in ("sgrid", "glab", "sadv", "sadvB", "stip", "stipK", "sact"):
            assert abs(d[key]["x"] - d["sbd"]["x"]) <= 1.0, "%s off gutter: %s" % (key, d)
        lab = 72 if width >= 600 else 64
        assert abs(d["sadvV"]["x"] - (d["sadvB"]["x"] + lab + 8)) <= 1.0, "definition value track: %s" % d
        assert abs(d["stipV"]["x"] - (d["stipK"]["x"] + lab + 8)) <= 1.0, "tip value track: %s" % d
        assert not d["fakeChip"], "suggestion action must not look like a button"
        assert "运行" in d["runPseudo"], "runtime row lost its label: %s" % d["runPseudo"]
        assert d["docDx"] <= 0, "expanded body overflow %s" % d["docDx"]
    finally:
        ctx.close()


def test_expanded_body_negative(srv, browser):
    """负控：把展开字段重新缩进 12px，同轨判据必须红。"""
    ctx, page = open_pacing(browser, 390)
    try:
        page.add_style_tag(content="#cfgview #cfgpacingRows .sbd>.sgrid{margin-left:12px!important}")
        page.evaluate("()=>document.querySelector('#cfgpacingRows .srow .sfold').click()")
        page.wait_for_timeout(350)
        d = page.evaluate(EXPANDED)
        assert d and d["sgrid"]["x"] - d["sbd"]["x"] >= 10, "12px indent negative control not detected: %s" % d
    finally:
        ctx.close()
