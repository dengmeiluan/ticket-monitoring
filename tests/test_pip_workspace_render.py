# -*- coding: utf-8 -*-
"""画中画真渲染：近全屏工作台、专注、浮窗、输入与浏览器弹窗隔离。"""
import io
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _png():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (900, 1600), (18, 28, 40)).save(buf, "PNG")
    return buf.getvalue()


def _boot():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    srv = subprocess.Popen(
        [sys.executable, "webui.py", "--demo", "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, env=env)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = "http://127.0.0.1:%d" % port
    for _ in range(160):
        try:
            op.open(base + "/api/state", timeout=1)
            return srv, base
        except Exception:
            time.sleep(0.25)
    srv.terminate()
    pytest.skip("演示服务未在期限内起来")


SHOT = os.environ.get("PIP_SHOT")


def _shot(pg, name):
    if not SHOT:
        return
    out = os.path.join(ROOT, "_scratch")
    os.makedirs(out, exist_ok=True)
    pg.screenshot(path=os.path.join(out, "pip_%s.png" % name))


def _rect(pg, sel):
    return pg.evaluate("""s => {const e=document.querySelector(s);
      if(!e)return null;const r=e.getBoundingClientRect();
      return {l:Math.round(r.left),t:Math.round(r.top),
              w:Math.round(r.width),h:Math.round(r.height),
              d:getComputedStyle(e).display};}""", sel)


def test_workspace_focus_float_input_and_browser_isolation():
    from playwright.sync_api import sync_playwright
    srv, base = _boot()
    png = _png()
    posts = []
    try:
        with sync_playwright() as pw:
            if not os.path.exists(pw.chromium.executable_path):
                pytest.skip("chromium 二进制缺失")
            b = pw.chromium.launch()
            try:
                pg = b.new_page(viewport={"width": 1512, "height": 982})
                errs = []
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.add_init_script("window.setInterval=()=>1;")

                def fake(route, req):
                    u = req.url
                    if "/frame" in u:
                        route.fulfill(status=200, content_type="image/png",
                                      body=png)
                        return
                    if "/info" in u:
                        route.fulfill(status=200,
                                      content_type="application/json",
                                      body=json.dumps({
                                          "ok": True, "width": 900,
                                          "height": 1600,
                                          "foreground": "cn.suanya.zhixing/"
                                                        ".MainActivity",
                                          "package": "cn.suanya.zhixing",
                                          "session": {"status": "pending"}}))
                        return
                    if req.method == "POST":
                        posts.append((u, req.post_data or ""))
                        route.fulfill(status=200,
                                      content_type="application/json",
                                      body='{"ok":true}')
                        return
                    route.continue_()

                pg.route("**/api/app-login**", fake)
                pg.goto(base)
                pg.wait_for_function(
                    "typeof S!=='undefined'&&S&&S.users", timeout=30000)
                pg.evaluate("()=>appLoginOpen('app_zhixing')")
                pg.wait_for_function(
                    "()=>{const i=document.getElementById('appImg');"
                    "return i&&getComputedStyle(i).display!=='none'}",
                    timeout=15000)
                m = _rect(pg, "#lgModal")
                img = _rect(pg, "#appImg")
                rail = _rect(pg, ".apprail")
                assert m and m["w"] >= 1000, m
                assert m["h"] >= 800, m
                assert img and img["h"] >= 600, img
                assert rail and rail["w"] >= 240, rail
                assert pg.evaluate(
                    "()=>{const f=document.getElementById('appFloat');"
                    "return !f||getComputedStyle(f).display==='none'}")
                _shot(pg, "workspace_1512")

                pg.fill("#appTextInput", "13800000000")
                pg.click("#lgModal .apptextrow button")
                pg.wait_for_timeout(250)
                assert any("/input" in u and "13800000000" in body
                           for u, body in posts), posts

                box = pg.locator("#appImg").bounding_box()
                cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                pg.mouse.click(cx, cy)
                pg.wait_for_timeout(250)
                assert any("/tap" in u for u, _ in posts), posts
                pg.mouse.move(cx, cy)
                pg.mouse.wheel(0, 140)
                pg.wait_for_timeout(250)
                assert any("/swipe" in u for u, _ in posts), posts

                pg.click("#appFocusBtn")
                pg.wait_for_timeout(200)
                assert pg.evaluate(
                    "()=>document.getElementById('lgModal')"
                    ".classList.contains('appfocus')")
                assert _rect(pg, ".apprail")["d"] == "none"
                _shot(pg, "focus_1512")
                pg.keyboard.press("Escape")
                pg.wait_for_timeout(200)
                assert not pg.evaluate(
                    "()=>document.getElementById('lgModal')"
                    ".classList.contains('appfocus')")
                assert pg.evaluate(
                    "()=>document.getElementById('lgModal')"
                    ".classList.contains('open')")

                pg.get_by_role("button", name="缩小浮窗").click()
                pg.wait_for_timeout(300)
                fl = _rect(pg, "#appFloat")
                assert fl and fl["d"] != "none", fl
                assert 300 <= fl["w"] <= 380, fl
                assert pg.evaluate(
                    "()=>document.body.style.overflow") == ""
                assert _rect(pg, "#appImg")["h"] >= 400
                drag = _rect(pg, "#appFloatDrag")
                x0 = drag["l"] + 36
                y0 = drag["t"] + drag["h"] / 2
                pg.mouse.move(x0, y0)
                pg.mouse.down()
                pg.mouse.move(x0 + 60, y0 + 40)
                pg.mouse.up()
                pg.wait_for_timeout(150)
                dragged = _rect(pg, "#appFloat")
                assert dragged["l"] != fl["l"] or dragged["t"] != fl["t"], (
                    fl, dragged)
                assert dragged["l"] >= 0 and dragged["t"] >= 0
                _shot(pg, "float_1512")

                pg.get_by_role("button", name="放大").click()
                pg.wait_for_timeout(300)
                assert pg.evaluate(
                    "()=>document.getElementById('lgModal')"
                    ".classList.contains('open')")
                assert pg.evaluate(
                    "()=>document.body.style.overflow") == "hidden"
                pg.click("#lgModal .x")
                pg.wait_for_timeout(200)
                assert not pg.evaluate(
                    "()=>document.getElementById('lgModal')"
                    ".classList.contains('open')")
                assert pg.evaluate(
                    "()=>document.body.style.overflow") == ""

                pg.evaluate("()=>lgOpenFliggy()")
                pg.wait_for_timeout(250)
                bm = _rect(pg, "#lgModal")
                assert bm and 500 <= bm["w"] <= 560, bm
                assert pg.evaluate(
                    "()=>document.getElementById('lgModal').dataset.kind") == "fliggy"
                pg.click("#lgModal .x")
                pg.wait_for_timeout(150)

                pg.set_viewport_size({"width": 390, "height": 844})
                pg.evaluate("()=>appLoginOpen('app_zhixing')")
                pg.wait_for_function(
                    "()=>{const i=document.getElementById('appImg');"
                    "return i&&getComputedStyle(i).display!=='none'}",
                    timeout=15000)
                m390 = _rect(pg, "#lgModal")
                img390 = _rect(pg, "#appImg")
                over = pg.evaluate(
                    "()=>{const m=document.getElementById('lgModal');"
                    "return m.scrollWidth>m.clientWidth+1||"
                    "document.documentElement.scrollWidth>"
                    "document.documentElement.clientWidth+1}")
                assert not over, m390
                assert m390["l"] >= 0 and m390["w"] <= 391, m390
                assert img390 and img390["h"] >= 300, img390
                _shot(pg, "workspace_390")
                pg.get_by_role("button", name="缩小浮窗").click()
                pg.wait_for_timeout(250)
                f390 = _rect(pg, "#appFloat")
                assert f390 and f390["l"] >= 0 and f390["l"] + f390["w"] <= 391, f390
                assert not errs, "页面抛错：%s" % errs[:3]
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()
