# -*- coding: utf-8 -*-
"""r1028：飞猪双端半格的登录状态不得被 113px 列宽裁成省略号。

完整句「已保存 · 页面可访问（明细未验证）」实测 173px；半格只留等义
短句「页面可达·明细待验」，完整句仍在 title。"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_static_tight_status_map_and_full_title():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        src = f.read()
    i = src.index("r1028：双端半格只有 113px")
    block = src[i:i + 900]
    assert "页面可达·明细待验" in block
    assert "会话有效·明细可用" in block
    assert "const _subTxt=tight?" in block
    j = src.index('class="lgsub" title=')
    assert "_stText" in src[j:j + 260], "短句替换后完整状态没有进 title"


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _payload():
    def slot(key, plat, status):
        return {"slot": key, "plat": plat, "status": status, "saved": True,
                "needs_login": False, "active": False, "saving": False,
                "pending": False, "account": "淘宝账号" if plat == "fliggy" else "",
                "requirement": "必须登录"}
    plats = {k: slot(k, k, "saved") for k in
             ("ctrip", "qunar", "tongcheng", "tuniu")}
    plats["fliggy"] = slot("fliggy", "fliggy", "page_ok")
    return {"ok": True, "plats": plats, "slots": {
        "ctrip": slot("ctrip", "ctrip", "saved"),
        "qunar": slot("qunar", "qunar", "saved"),
        "fliggy": slot("fliggy", "fliggy", "page_ok"),
        "fliggy_h5": slot("fliggy_h5", "fliggy", "page_ok"),
        "tongcheng": slot("tongcheng", "tongcheng", "saved"),
        "tuniu": slot("tuniu", "tuniu", "saved"),
    }}


def test_rendered_dual_slot_status_is_complete():
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
                pg = br.new_page(viewport={"width": 390, "height": 1000})
                pg.route("**/api/login-state", lambda r: r.fulfill(json=_payload()))
                pg.goto(base + "/", wait_until="domcontentloaded")
                pg.wait_for_timeout(1800)
                pg.evaluate("switchView('cfg')")
                pg.wait_for_timeout(1200)
                pg.wait_for_function(
                    "()=>[...document.querySelectorAll('#loginRows .lgsub')]"
                    ".some(e=>e.textContent.indexOf('页面可达')>=0)", timeout=8000)
                got = pg.evaluate("""()=>{
                  const subs=[...document.querySelectorAll('#loginRows .lgsub')];
                  const e=subs.find(x=>x.textContent.includes('页面可达'));
                  const b=e.getBoundingClientRect();
                  const rg=document.createRange(); rg.selectNodeContents(e);
                  const rights=[...rg.getClientRects()].map(r=>r.right);
                  return {txt:e.textContent.trim(), title:e.title,
                    w:+b.width.toFixed(1), sw:e.scrollWidth,
                    tr:+Math.max(...rights).toFixed(1), r:+b.right.toFixed(1),
                    n:subs.length,
                    pageOF:document.documentElement.scrollWidth-innerWidth};
                }""")
                assert got["n"] >= 6, got
                assert got["txt"] == "页面可达·明细待验", got
                assert "已保存 · 页面可访问（明细未验证）" in got["title"], got
                assert got["tr"] <= got["r"] + 1, ("半格状态仍被裁切", got)
                assert got["sw"] <= got["w"] + 1, ("状态胶囊仍有隐藏溢出", got)
                assert got["pageOF"] <= 1, got
                pg.close()
            finally:
                br.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=8)
        except Exception:
            srv.kill()
