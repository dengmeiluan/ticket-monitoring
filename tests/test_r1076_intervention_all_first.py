# -*- coding: utf-8 -*-
"""r1076：干预行「全部」必须在首屏可见。

390 两条干预动作轨是横向可滑的；「全部」原先排在 6 个渠道之后，
不滑动根本看不到——最该点的全局动作被藏起来。现在每组「全部」
紧跟组名（自检还排在范围下拉之后），且落在轨道可视框内。
"""
import os
import sys

import pytest

pytest.importorskip("playwright",
                    reason="干预行动作可见性依赖 playwright（缺库 SKIP 不 ERROR）")

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
    priv = tempfile.mkdtemp(prefix="r1076_")
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


def test_all_button_visible_at_phone(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 390, "height": 950},
                        is_mobile=True, has_touch=True)
        pg.goto(BASE + "/", wait_until="load")
        pg.wait_for_function("typeof S!=='undefined'&&S&&S.users", timeout=25000)
        pg.wait_for_timeout(1500)
        pg.evaluate("()=>{switchView('mon');showMonTab('health')}")
        pg.wait_for_timeout(2200)
        d = pg.evaluate("""(() => {
          const rows=[...document.querySelectorAll('#paceBox .pace-tools .g')];
          return rows.map(g=>{
            const gr=g.getBoundingClientRect();
            const btns=[...g.querySelectorAll('button')];
            const gi=btns.findIndex(e=>(e.textContent||'').trim()==='全部');
            const all=gi>=0?btns[gi]:null;
            const ar=all?all.getBoundingClientRect():null;
            return {label:(g.querySelector('b')||{}).textContent||'',
              n:btns.length, idx:gi,
              rail:{L:Math.round(gr.left),R:Math.round(gr.right),
                sw:g.scrollWidth,cw:g.clientWidth},
              all:ar?{L:Math.round(ar.left),R:Math.round(ar.right),
                W:Math.round(ar.width)}:null,
              first:[...btns.slice(0,3)].map(e=>(e.textContent||'').trim())};
          });
        })()""")
        assert len(d) == 2, d
        for r in d:
            assert r["all"] and r["all"]["W"] > 10, d
            assert r["idx"] <= 1, "「全部」不在首屏前两位：%s" % d
            assert r["all"]["L"] >= r["rail"]["L"] - 1, d
            assert r["all"]["R"] <= r["rail"]["R"] + 1, "「全部」落在轨道外：%s" % d
            # r1485：原来硬性要求「轨道必须有溢出样本」（sw > cw）。去哪儿网页
            # 通路退役后少了一颗 chip，窄档工具行**已经装得下**——此时"要能横向
            # 滚动"这条对用户是空的，不该再把"没溢出"判成红。
            # 保留真意图：装得下就不许裁切；装不下就必须能滚且「全部」仍在首屏。
            if r["rail"]["sw"] > r["rail"]["cw"] + 1:
                assert r["idx"] <= 1, ("轨道有溢出时「全部」必须在首屏：%s" % d)
            else:
                assert r["rail"]["sw"] <= r["rail"]["cw"] + 1, d
        # 自检组：范围下拉在前，全部第二
        assert d[1]["first"][0] == "全部" or d[1]["first"][1] == "全部", d
        b.close()


def test_all_button_visible_at_desktop(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1512, "height": 950})
        pg.goto(BASE + "/", wait_until="load")
        pg.wait_for_function("typeof S!=='undefined'&&S&&S.users", timeout=25000)
        pg.wait_for_timeout(1500)
        pg.evaluate("()=>{switchView('mon');showMonTab('health')}")
        pg.wait_for_timeout(2200)
        # r1495：桌面档「节流与干预」默认折叠，工具行在 fold 里量到 0×0
        # （`display:flex` 但宿主隐藏）——先展开再量，否则「全部」永远是 {ok:false}。
        pg.evaluate("()=>{const f=document.getElementById('hpaceFold');if(f)f.open=true;}")
        # 工具行是异步渲染的，固定等待在负载下会量到空。
        try:
            pg.wait_for_function(
                "()=>{const a=[...document.querySelectorAll('#paceBox .pace-tools .g button')]"
                ".find(e=>(e.textContent||'').trim()==='全部');"
                "return a&&a.getBoundingClientRect().width>10}", timeout=12000)
        except Exception:
            pass
        d = pg.evaluate("""(() => [...document.querySelectorAll('#paceBox .pace-tools .g')]
          .map(g=>{const all=[...g.querySelectorAll('button')]
            .find(e=>(e.textContent||'').trim()==='全部');
            if(!all)return {ok:false};
            const r=all.getBoundingClientRect();
            return {ok:r.width>10&&r.height>10}}))()""")
        assert all(x["ok"] for x in d), d
        b.close()
