# -*- coding: utf-8 -*-
"""r1056：渠道入口是单颗多态按钮，开合只换同一位置的文案。

用户原话：「渠道入口（打开），就可以直接合并变成渠道入口按钮，点击打开，
再点击关闭，推崇按钮可以多态文案统一设计」。旧实现里 `srxChLinksToggle`
找一个不存在的 `summary em`，开合后文字始终是「渠道入口」，按钮没有状态。

判据取真渲染：收起「渠道入口」↔ 打开「收起入口」（同 4 字、宽度不跳），
`aria-expanded` 同步，浮层开合不改变按钮自身坐标。
"""
import os
import sys

import pytest

pytest.importorskip("playwright",
                    reason="多态按钮判据依赖 playwright（缺库 SKIP 不 ERROR）")

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
    priv = tempfile.mkdtemp(prefix="r1056_")
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


def _snap(pg):
    return pg.evaluate("""(() => {
      const d=document.getElementById('srxChLinksDrawer');
      const s=document.getElementById('srxChLinksBtn');
      const r=s?s.getBoundingClientRect():null;
      return {open:!!(d&&!d.hidden), text:s?(s.textContent||'').trim():'',
        aria:s?s.getAttribute('aria-expanded'):null,
        title:s?s.title:'',
        box:r?[Math.round(r.left),Math.round(r.top),Math.round(r.width),Math.round(r.height)]:null};
    })()""")


def test_channel_entry_text_toggles_and_does_not_move(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1512, "height": 950})
        pg.goto(BASE + "/", wait_until="load")
        pg.wait_for_function("typeof S!=='undefined'&&S&&S.users", timeout=25000)
        pg.wait_for_timeout(1500)
        pg.evaluate("()=>switchView('search')")
        pg.wait_for_timeout(2200)
        pg.evaluate("()=>{const b=document.getElementById('srxProbeTool');if(b)b.click()}")
        pg.wait_for_timeout(600)

        closed = _snap(pg)
        assert closed["text"] == "渠道入口", closed
        assert closed["aria"] == "false", closed
        assert "展开" in closed["title"], closed

        pg.click("#srxChLinksBtn")
        pg.wait_for_timeout(400)
        opened = _snap(pg)
        assert opened["open"] is True, opened
        assert opened["text"] == "收起入口", opened
        assert opened["aria"] == "true", opened
        assert "收起" in opened["title"], opened
        # 同词同长：按钮盒位置和宽度不因状态文案而跳
        assert opened["box"][:3] == closed["box"][:3], (closed, opened)

        pg.click("#srxChLinksDrawer .clx-x")
        pg.wait_for_timeout(300)
        again = _snap(pg)
        assert again["open"] is False, again
        assert again["text"] == "渠道入口", again
        assert again["aria"] == "false", again
        b.close()
