# -*- coding: utf-8 -*-
"""r1049e：镜像渠道轨改为「常驻一行」的渠道切换条。

旧 r999 契约是 390 两列等宽网格（10 家 5 行）；用户 2026-11-06 明确否定
「穷举默认铺开」：常驻一行，展开最多两行。现在只列本航线真有行的渠道
（0 行渠道点开也只有空态，没有可看内容），整轨恒为一行；390 放不下时
在轨内横向滑动，右缘渐隐提示还有内容。当前渠道永远保留。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_static_mirror_rail_is_one_scrollable_row():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        src = f.read()
    assert "#searchview .srx-mirror .srx-mrail{display:flex!important;flex-wrap:nowrap!important" in src
    assert "#searchview .srx-mrail-tabs{display:flex;align-items:center;gap:4px;min-width:0;" in src
    assert "mask-image:linear-gradient(90deg,#000 calc(100% - 18px),transparent)" in src
    # 只列有数据渠道的过滤不能丢
    assert "chans.filter(c=>cnt[c]>0||c===ch)" in src


def _boot():
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


def test_rendered_mirror_rail_is_one_row_without_zero_channels():
    import pytest
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
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            try:
                for width in (390, 1512):
                    pg = b.new_page(viewport={"width": width, "height": 950})
                    pg.goto(base)
                    pg.wait_for_function(
                        "typeof S!=='undefined'&&S&&S.users", timeout=30000)
                    pg.evaluate("()=>{switchView('search')}")
                    pg.wait_for_timeout(500)
                    try:
                        pg.get_by_text("原页镜像", exact=True).click()
                    except Exception:
                        pass
                    pg.wait_for_timeout(700)
                    d = pg.evaluate(r"""()=>{
                      const rail=document.querySelector('#searchview .srx-mirror .srx-mrail');
                      if(!rail)return {err:'no rail'};
                      const tabs=[...rail.querySelectorAll('.srx-mtab')];
                      const fold=rail.querySelector('.srx-foldbtn');
                      const R=e=>{const r=e.getBoundingClientRect();
                        return {x:+r.x.toFixed(1),y:+r.y.toFixed(1),
                          w:+r.width.toFixed(1),h:+r.height.toFixed(1),
                          right:+r.right.toFixed(1),bottom:+r.bottom.toFixed(1)}};
                      const rs=tabs.map(R);
                      const fr=fold?R(fold):null;
                      const tabsBox=rail.querySelector('.srx-mrail-tabs').getBoundingClientRect();
                      const visible=tabs.filter(t=>{const r=t.getBoundingClientRect();
                        return r.left < tabsBox.right-0.5 && r.right > tabsBox.left+0.5});
                      const overlap=fr?visible.filter(t=>{const r=t.getBoundingClientRect();
                        /* 只算被 tabs 裁切后的可见右缘，溢出部分被 overflow 隐藏 */
                        const rr=Math.min(r.right,tabsBox.right), ll=Math.max(r.left,tabsBox.left);
                        return !(rr<=fr.x||ll>=fr.right||r.bottom<=fr.y||r.top>=fr.bottom)}).length:0;
                      return {n:tabs.length,disp:getComputedStyle(rail).display,
                        rows:[...new Set(rs.map(x=>x.y))].length,
                        zero:tabs.filter(t=>{
                          const n=t.querySelector('.n');
                          return n && (n.textContent||'').trim()==='0';
                        }).length,
                        rail:R(rail),fold:fr,overlap:overlap,
                        pageOverflow:document.documentElement.scrollWidth
                          -document.documentElement.clientWidth};}""")
                    assert not d.get("err"), (width, d)
                    assert d["disp"] == "flex", d
                    assert d["rows"] == 1, ("镜像渠道轨又铺成多行", width, d)
                    assert d["rail"]["h"] <= 52, (width, d)
                    assert d["zero"] == 0, ("镜像轨默认枚举了 0 行渠道", width, d)
                    assert d["overlap"] == 0, (width, d)
                    assert d["pageOverflow"] <= 0, (width, d)
                    pg.close()
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=8)
        except Exception:
            srv.kill()
