# -*- coding: utf-8 -*-
"""r1053：特价雷达「官方特价来源」不再十家竖向长铺。

用户否定的「穷举默认铺开」：1512 档 10 家渠道各占 1 行、总高 ~700px。
定案：宽档两列（5 行、~293px），窄档仍一家一行但压成 52px 的两段式
（渠道名+登录要求 / 能力入口），说明行收进 title，能力入口一个不少。
"""
import os
import sys

import pytest

pytest.importorskip("playwright",
                    reason="窄档/宽档几何依赖 playwright（缺库 SKIP 不 ERROR）")

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
    priv = tempfile.mkdtemp(prefix="r1053_")
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


def _measure(w):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        mobile = w <= 600
        pg = b.new_page(viewport={"width": w, "height": 950},
                        is_mobile=mobile, has_touch=mobile)
        pg.goto(BASE + "/", wait_until="load")
        pg.wait_for_function("typeof S!=='undefined'&&S&&S.users", timeout=25000)
        pg.wait_for_timeout(1500)
        pg.evaluate("switchView('mon')")
        pg.wait_for_timeout(500)
        pg.evaluate("showMonTab('specials')")
        pg.wait_for_timeout(2400)
        out = pg.evaluate("""(() => {
          const board=document.getElementById('spentryboard');
          if(!board) return {exists:false};
          const bands=[...board.querySelectorAll('.chband')];
          if(!bands.length) return {exists:false};
          const br=board.getBoundingClientRect();
          const rects=bands.map(x=>x.getBoundingClientRect());
          return {exists:true, n:bands.length,
            boardH:Math.round(br.height),
            rows:new Set(rects.map(r=>Math.round(r.top))).size,
            cols:new Set(rects.map(r=>Math.round(r.left))).size,
            bandH:rects.map(r=>Math.round(r.height)),
            noteVisible:[...board.querySelectorAll('.chband-note')].filter(n=>n.offsetParent).length,
            names:bands.map(x=>(x.querySelector('.chband-name b')||{}).textContent||''),
            over:board.scrollWidth>board.clientWidth+1};
        })()""")
        b.close()
    assert out.get("exists"), "%s 档特价来源板没渲染" % w
    assert out["n"] == 10, "%s 档渠道来源数应 10：%s" % (w, out)
    assert out["noteVisible"] == 0, "%s 档说明行仍占可见高度（应只在 title）：%s" % (w, out)
    assert not out["over"], "%s 档特价来源板横向溢出：%s" % (w, out)
    for name in ("携程", "去哪儿", "飞猪", "同程", "途牛",
                 "智行 App", "去哪儿 App", "飞猪 App", "携程 App", "同程 App"):
        assert name in out["names"], "%s 档特价来源缺「%s」：%s" % (w, name, out["names"])
    return out


def test_specials_sources_two_columns_on_wide(srv):
    out = _measure(1512)
    assert out["cols"] == 2, "1512 档特价来源应两列：%s" % out
    assert out["rows"] == 5, "1512 档特价来源应 5 行（两列 × 10 家）：%s" % out
    assert out["boardH"] <= 330, "1512 档特价来源仍过高：%s" % out
    assert max(out["bandH"]) <= 60, "1512 档单条渠道过高：%s" % out


def test_specials_sources_single_row_per_channel_on_phone(srv):
    out = _measure(390)
    assert out["cols"] == 1, "390 档特价来源应单列：%s" % out
    assert out["rows"] == 10, "390 档应一家渠道一行：%s" % out
    assert max(out["bandH"]) <= 58, "390 档单条渠道仍高于 58px（未收成两段式）：%s" % out
    assert out["boardH"] <= 620, "390 档特价来源仍过长：%s" % out
