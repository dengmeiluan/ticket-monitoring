# -*- coding: utf-8 -*-
"""r1047：城市面板字母导航移出滚动容器，滚动城市不再进入冻结字母行。"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_static_abc_outside_scroll_body():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        src = f.read()
    assert '<div id="cpabc" class="cp-abc" aria-label="字母导航"></div>' in src
    i = src.index(".cp-abc{")
    block = src[i:i + 220]
    assert "position:sticky" not in block, block
    assert "flex:0 0 auto" in block, block
    j = src.index("r1047：字母导航从滚动容器里搬出来")
    build = src[j:j + 500]
    assert "abcEl.innerHTML=Ls.map" in build
    assert "h2+='<div class=\"cp-abc\"" not in src


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_rendered_letters_never_overlap_city_scroll():
    import pytest
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        pytest.skip("playwright 缺失")
    port = _free_port()
    base = "http://127.0.0.1:%d" % port
    srv = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(port)],
                           cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ok = False
        for _ in range(90):
            try:
                urllib.request.urlopen(base + "/api/state", timeout=2)
                ok = True
                break
            except Exception:
                time.sleep(0.5)
        if not ok:
            pytest.skip("demo 服务未起来")
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            try:
                for width, height in ((1400, 486), (390, 844)):
                    pg = br.new_page(viewport={"width": width, "height": height})
                    pg.goto(base + "/", wait_until="domcontentloaded")
                    pg.wait_for_timeout(1600)
                    pg.evaluate("switchView('search')")
                    pg.wait_for_timeout(700)
                    pg.evaluate("srxToggleProbe()")
                    pg.wait_for_timeout(400)
                    pg.evaluate("srxOpenCityPanel('srxFrom')")
                    pg.wait_for_timeout(600)
                    d = pg.evaluate("""()=>{
                      const R=e=>{const r=e.getBoundingClientRect();return {t:+r.top.toFixed(1),b:+r.bottom.toFixed(1),h:+r.height.toFixed(1)}};
                      const body=document.getElementById('cpbody'),abc=document.getElementById('cpabc');
                      return {outside:!body.contains(abc),abc:R(abc),body:R(body),
                        letters:abc.querySelectorAll('span').length,
                        pageOF:document.documentElement.scrollWidth-innerWidth};
                    }""")
                    assert d["outside"], (width, "字母导航仍在滚动容器里")
                    assert d["letters"] >= 10, (width, d)
                    assert d["abc"]["b"] <= d["body"]["t"] + 1, (width, d)
                    assert d["pageOF"] <= 1, (width, d)

                    # 滚动城市列表：字母条坐标不变，城市不会进入字母条区域
                    pg.evaluate("()=>{const b=document.getElementById('cpbody');b.scrollTop=400}")
                    pg.wait_for_timeout(300)
                    d2 = pg.evaluate("""()=>{
                      const abc=document.getElementById('cpabc').getBoundingClientRect();
                      const bodyEl=document.getElementById('cpbody');
                      const body=bodyEl.getBoundingClientRect();
                      return {abc:{t:abc.top,b:abc.bottom},body:{t:body.top,b:body.bottom},
                        overflow:getComputedStyle(bodyEl).overflowY,
                        st:bodyEl.scrollTop};
                    }""")
                    # 字母条在滚动容器之外，底边与 body 顶边相切；城市内容
                    # 即使坐标上移也会被 body 的 overflow 裁掉，不会进入字母行。
                    assert d2["abc"]["b"] <= d2["body"]["t"] + 1, (width, d2)
                    assert d2["overflow"] in ("auto", "scroll"), (width, d2)
                    assert d2["st"] > 0, (width, d2)

                    # 点 B 仍能跳到 B 组，组头在字母条下方可见
                    pg.evaluate("cityPanelJump('B')")
                    pg.wait_for_timeout(650)
                    d3 = pg.evaluate("""()=>{
                      const sec=document.querySelector('.cp-sec[data-l="B"]');
                      const ab=document.getElementById('cpabc').getBoundingClientRect();
                      const head=sec&&sec.querySelector('.cp-lhead');
                      const h=head?head.getBoundingClientRect():null;
                      return h?{headTop:h.top,abcBottom:ab.bottom,inView:h.top>=ab.bottom-1}:null;
                    }""")
                    assert d3 and d3["inView"], (width, "点字母后组头不可见", d3)

                    # 搜索时字母条隐藏，清空后恢复
                    pg.fill("#cpq", "北京")
                    pg.wait_for_timeout(300)
                    assert pg.evaluate("getComputedStyle(document.getElementById('cpabc')).display") == "none"
                    pg.fill("#cpq", "")
                    pg.wait_for_timeout(300)
                    assert pg.evaluate("getComputedStyle(document.getElementById('cpabc')).display") != "none"
                    pg.close()
            finally:
                br.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=8)
        except Exception:
            srv.kill()
