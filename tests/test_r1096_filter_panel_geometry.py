# -*- coding: utf-8 -*-
"""r1096：检索筛选面板（更多条件）窄档几何回归。

用户点名「筛选条件航司和航司搜索框遮挡」「边缘遮挡」「组件和组件之间有遮挡」。
本测试直接打开真实筛选面板，逐档检查：
1) 面板可见、页面无横向溢出；
2) 航司搜索框在航司 chips 上方，两者零相交；
3) 面板内所有可见控件两两零相交；
4) 320/390 单列，每张 srf-card 宽 = 面板内宽。
"""
import os
import sys

import pytest

pytest.importorskip("playwright",
                    reason="筛选面板几何依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None
WIDTHS = [320, 390, 768]


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def srv():
    import subprocess
    import tempfile
    import time
    import urllib.request

    global BASE
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    logf = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    priv = tempfile.mkdtemp(prefix="r1096_")
    env = dict(os.environ, TEMP=priv, TMP=priv, TMPDIR=priv,
               PYTHONIOENCODING="utf-8")
    proc = None
    for _ in (1, 2):
        port = _free_port()
        BASE = "http://127.0.0.1:%d" % port
        proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
             "--port", str(port)],
            cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT, env=env)
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        up = False
        for _ in range(60):
            if proc.poll() is not None:
                break
            try:
                op.open(BASE + "/api/state", timeout=2)
                up = True
                break
            except Exception:
                time.sleep(0.5)
        if up:
            break
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
    else:
        pytest.fail("demo 启动失败（两次新端口重试后）")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    logf.close()


SNAP = """(() => {
  const rg=e=>{if(!e)return null;const r=e.getBoundingClientRect();
    return {L:Math.round(r.left),T:Math.round(r.top),R:Math.round(r.right),
      B:Math.round(r.bottom),W:Math.round(r.width),H:Math.round(r.height)}};
  const p=document.getElementById('srxFmore');
  const airq=p.querySelector('.srf-airq');
  const inp=document.getElementById('srfAirQ');
  const chips=document.getElementById('srfAirChips');
  const vis=e=>{const r=e.getBoundingClientRect();const c=getComputedStyle(e);
    return r.width>4&&r.height>4&&c.display!=='none'&&c.visibility!=='hidden'};
  const ctrls=[...p.querySelectorAll('input,select,button')].filter(vis);
  const over=[];
  for(let i=0;i<ctrls.length;i++)for(let j=i+1;j<ctrls.length;j++){
    const a=ctrls[i],b=ctrls[j];if(a.contains(b)||b.contains(a))continue;
    const ra=a.getBoundingClientRect(),rb=b.getBoundingClientRect();
    const ox=Math.min(ra.right,rb.right)-Math.max(ra.left,rb.left);
    const oy=Math.min(ra.bottom,rb.bottom)-Math.max(ra.top,rb.top);
    if(ox>2&&oy>2)over.push((a.id||a.className)+'×'+(b.id||b.className));
  }
  const cards=[...p.querySelectorAll('.srf-card')].map(rg);
  return {panel:rg(p),airq:rg(airq),inp:rg(inp),
    airClip:inp?inp.scrollWidth-inp.clientWidth:0,
    chips:rg(chips),
    airChipsOverlap:!!(airq&&chips&&
      chips.getBoundingClientRect().top<airq.getBoundingClientRect().bottom-1),
    ctrls:ctrls.length,over,cards,
    overPage:document.documentElement.scrollWidth-innerWidth};
})()"""


def test_filter_panel_no_overlap(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        bad = []
        for w in WIDTHS:
            pg = b.new_page(viewport={"width": w, "height": 1200},
                            is_mobile=(w <= 600), has_touch=(w <= 600))
            pg.goto(BASE + "/", wait_until="load")
            pg.wait_for_function("typeof S!=='undefined'&&S&&S.users",
                                 timeout=25000)
            pg.wait_for_timeout(900)
            pg.evaluate("()=>switchView('search')")
            pg.wait_for_timeout(650)
            pg.evaluate("""()=>{let b=document.querySelector(
              '[data-mobile="filters"]');
              if(!b||!b.offsetParent)b=document.getElementById('srxFilterBtn');
              if(b)b.click()}""")
            pg.wait_for_timeout(450)
            pg.evaluate("()=>{try{srxToggleMore()}catch(e){}}")
            pg.wait_for_timeout(650)
            d = pg.evaluate(SNAP)
            pg.close()
            if not d["panel"] or d["panel"]["W"] < 250:
                bad.append("%d 筛选面板不可见/过窄 %s" % (w, d["panel"]))
                continue
            if d["overPage"] > 1:
                bad.append("%d 筛选面板横向溢出 %d" % (w, d["overPage"]))
            if not d["airq"] or not d["chips"]:
                bad.append("%d 航司搜索框/航司 chips 缺失" % w)
            elif d["airChipsOverlap"]:
                bad.append("%d 航司搜索框与 chips 相交" % w)
            if d["airClip"] > 1:
                bad.append("%d 航司搜索框文字被裁 %d" % (w, d["airClip"]))
            if d["over"]:
                bad.append("%d 筛选控件相交: %s" % (w, d["over"][:4]))
            if len(d["cards"]) != 5:
                bad.append("%d 筛选卡数量 %d（应 5）" % (w, len(d["cards"])))
            elif w <= 600:
                pw = d["panel"]["W"]
                for c in d["cards"]:
                    if abs(c["W"] - pw) > 2:
                        bad.append("%d 档筛选卡未单列同宽（%d vs %d）"
                                   % (w, c["W"], pw))
        b.close()
    assert not bad, "筛选面板几何: " + "；".join(bad)
