# -*- coding: utf-8 -*-
"""r996：配置页说明去重 / 压缩（用户点名「去哪儿停服说明冗余突兀」、
「这么点信息按钮要放三行」）。

合同：
- 登录分区只保留一句政策（都必须登录…），底部一行核验说明；
- 去哪儿 PC 停服只留在来源接入板/该渠道行，登录卡不再重复；
- App 名称由登录卡行展示，不再在两段说明里各列一遍；
- 真渲染：1512 卡头 1 行、390 ≤2 行；底部说明 1 行；内容不贴边。
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        return f.read()


def test_login_section_has_one_policy_sentence_only():
    src = _src()
    block = src[src.index('id="sec-login"'):src.index('id="sec-chlinks"')]
    assert "都必须登录（入口页可匿名浏览" in block
    assert block.count("都必须登录") == 1, "登录分区重复了政策句"
    assert "去哪儿" not in block and "停服" not in block, (
        "去哪儿停服说明又回到登录卡")
    assert "lgAppNames" not in block, "App 名称仍在卡头整段罗列"
    # JS 里也不得再生成重复脚注
    assert "lgnote" not in src, "登录卡仍在拼重复脚注 .lgnote"
    assert "保存后按实际请求核验" in block


def _boot():
    import socket
    import subprocess
    import sys
    import time
    import urllib.request
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
         "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = "http://127.0.0.1:%d" % port
    t0 = time.time()
    while time.time() - t0 < 60:
        try:
            op.open(base + "/api/state", timeout=2)
            return srv, base
        except Exception:
            time.sleep(0.3)
    srv.kill()
    raise RuntimeError("demo server did not start")


def test_rendered_login_notes_are_compact():
    pytest = __import__("pytest")
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        pytest.skip("playwright 缺失")
    with sync_playwright() as pw:
        if not os.path.exists(pw.chromium.executable_path):
            pytest.skip("chromium 二进制缺失")
    srv, base = _boot()
    try:
        from playwright.sync_api import sync_playwright
        out = {}
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            try:
                for w in (1512, 390):
                    pg = b.new_page(viewport={"width": w, "height": 1000})
                    pg.goto(base)
                    pg.wait_for_function(
                        "typeof S!=='undefined'&&S&&S.users", timeout=30000)
                    pg.evaluate("()=>{switchView('cfg')}")
                    pg.wait_for_selector("#loginRows .lgcard", timeout=15000)
                    pg.wait_for_timeout(900)
                    out[w] = pg.evaluate(r"""()=>{
                      const lines=el=>{if(!el)return 0;
                        const r=document.createRange();
                        r.selectNodeContents(el);
                        const t=new Set();
                        for(const b of r.getClientRects())
                          if(b.height>2)t.add(Math.round(b.top));
                        return t.size;};
                      const card=document.querySelector('#sec-login');
                      const row=document.querySelector('#loginRows .lgcard');
                      const cr=card.getBoundingClientRect();
                      const rr=row?row.getBoundingClientRect():null;
                      return {secLines:lines(card.querySelector('.secnote')),
                        footLines:lines(card.querySelector('.muted')),
                        dimLines:lines(document.querySelector(
                          '#sec-dims .secnote')),
                        lgnote:!!document.querySelector('#loginRows .lgnote'),
                        qunar:card.textContent.includes('停服'),
                        padL:rr?+(rr.left-cr.left).toFixed(1):0,
                        padR:rr?+(cr.right-rr.right).toFixed(1):0,
                        cards:document.querySelectorAll(
                          '#loginRows .lgcard').length,
                        overflow:document.documentElement.scrollWidth
                          -document.documentElement.clientWidth};}""")
                    pg.close()
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=8)
        except Exception:
            srv.kill()
    a, m = out[1512], out[390]
    assert a["secLines"] == 1, a
    assert m["secLines"] <= 2, m
    assert a["footLines"] == 1 and m["footLines"] == 1, out
    assert a["dimLines"] == 1 and m["dimLines"] == 1, out
    for k in (1512, 390):
        assert not out[k]["lgnote"], out[k]
        # r1063 T68：去哪儿网页版**正式停服**，登录卡必须说出来，
        # 否则等于劝人去登一个已经不存在的入口。
        assert out[k]["qunar"], out[k]
        assert out[k]["padL"] >= 14 and out[k]["padR"] >= 14, out[k]
        assert out[k]["cards"] == 10, out[k]
        assert out[k]["overflow"] <= 0, out[k]
