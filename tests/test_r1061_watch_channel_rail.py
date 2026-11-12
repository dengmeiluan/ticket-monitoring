# -*- coding: utf-8 -*-
"""r1061：关注航班渠道价带 390 收成单行横滑。"""
import os
import sys

import pytest

pytest.importorskip("playwright", reason="窄档渠道带依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


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
    priv = tempfile.mkdtemp(prefix="r1061_")
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
  const box=document.getElementById('wsChanStrip');
  if(!box) return {exists:false};
  const chips=[...box.querySelectorAll('.ws-ch')];
  const cs=getComputedStyle(box);
  const rr=box.getBoundingClientRect();
  const first=chips[0]?chips[0].getBoundingClientRect():null;
  const before={scrollW:box.scrollWidth,clientW:box.clientWidth,
    rows:new Set(chips.map(c=>Math.round(c.getBoundingClientRect().top))).size,
    h:Math.round(rr.height),wrap:cs.flexWrap,overflowX:cs.overflowX,
    mask:(cs.maskImage||cs.webkitMaskImage||'none')!=='none',
    boxL:Math.round(rr.left),boxR:Math.round(rr.right),
    firstL:first?Math.round(first.left):null,
    clipped:chips.filter(c=>c.scrollWidth>c.clientWidth+1).length,
    labels:chips.map(c=>(c.textContent||'').trim())};
  box.scrollLeft=box.scrollWidth;
  const last=chips.length?chips[chips.length-1].getBoundingClientRect():null;
  const lastVisible=last?(last.right<=Math.round(rr.right)+1&&last.left>=Math.round(rr.left)-1):false;
  box.scrollLeft=0;
  return {exists:true,n:chips.length,before,lastVisible,
    scrollable:before.scrollW>before.clientW+1,
    over:document.documentElement.scrollWidth>innerWidth+1};
})()"""


def _open(pg):
    pg.goto(BASE + "/", wait_until="load")
    pg.wait_for_function("typeof S!=='undefined'&&S&&S.users", timeout=25000)
    pg.wait_for_timeout(1500)
    pg.evaluate("()=>{switchView('mon');showMonTab('watch')}")
    pg.wait_for_timeout(2200)


def test_watch_channel_strip_single_row_on_phone(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        _open(pg)
        d = pg.evaluate(SNAP)
        assert d.get("exists"), "关注航班渠道带未渲染"
        assert d["n"] >= 10, d
        bfr = d["before"]
        assert bfr["rows"] == 1, "390 渠道价带应单行，实为 %s 行" % bfr["rows"]
        assert bfr["wrap"] == "nowrap", bfr
        assert bfr["overflowX"] in ("auto", "scroll"), bfr
        assert bfr["mask"], "390 渠道价带缺少渐隐提示"
        assert bfr["boxL"] >= -1 and bfr["boxR"] <= 390 + 1, bfr
        assert bfr["firstL"] >= bfr["boxL"] - 1, bfr
        assert d["scrollable"], "390 渠道多于一行时应可横滑：%s" % d
        assert d["lastVisible"], "滑到末端末个渠道不可完整到达：%s" % d
        assert bfr["clipped"] == 0, bfr
        assert not d["over"], d
        b.close()


def test_watch_channel_strip_on_desktop(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1512, "height": 950})
        _open(pg)
        d = pg.evaluate(SNAP)
        assert d.get("exists") and d["n"] >= 10, d
        assert not d["over"], d
        b.close()
