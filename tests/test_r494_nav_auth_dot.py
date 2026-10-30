# -*- coding: utf-8 -*-
"""r494：会话失效必须在**任何页面**都看得见。

缺口：`#hauthact` 与节流面板都只在「监控 · 渠道健康」页可见。用户停在
概览/明细/检索页时，一个渠道可以整天被登录墙拦着而界面上毫无提示——
这是「可干预的及时性」的实质缺口，不是观感问题。

修法要点（也是本契约要守的）：
  1) 红点数据源必须是 /api/login-state（全局 2s 轮询），
     **不能挂在 loadPacing 上**——后者只在健康页跑，挂上去会在别的页面
     永不更新，功能等于没做（这一点在实现时真的踩过）；
  2) 判据用会话级 needs_login，多会话厂商要指出是哪一端（飞猪 H5）；
  3) 全部正常时必须隐藏，不能常亮成装饰。
"""
import json
import os
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BAD = {"ok": True, "plats": {"fliggy": {"status": "login_required",
                                        "needs_login": True}},
       "slots": {
           "fliggy": {"plat": "fliggy", "name": "飞猪 PC", "surface": "pc",
                      "surface_label": "PC", "status": "saved",
                      "saved": True, "needs_login": False, "account": "a"},
           "fliggy_h5": {"plat": "fliggy", "name": "飞猪 H5", "surface": "h5",
                         "surface_label": "H5", "status": "login_required",
                         "needs_login": True, "saved": True, "account": "a"},
       }}
GOOD = {"ok": True,
        "plats": {p: {"status": "saved", "saved": True}
                  for p in ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu")},
        "slots": {k: dict(v, needs_login=False, status="saved")
                  for k, v in BAD["slots"].items()}}


def test_nav_dot_visible_on_non_health_pages(tmp_path):
    from playwright.sync_api import sync_playwright
    import webui

    tmp = os.path.join(ROOT, "_scratch", "_r494_t")
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as f:
        f.write(webui.PAGE.replace("__PAGEVER__", "r494t"))

    class H(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 8936), partial(H, directory=tmp))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    got = {}
    try:
        with sync_playwright() as drv:
            if not os.path.exists(drv.chromium.executable_path):
                pytest.skip("Chromium 未安装")
            b = drv.chromium.launch()
            try:
                ctx = b.new_context(viewport={"width": 1440, "height": 950})
                page = ctx.new_page()
                page.set_default_timeout(8000)
                page.add_init_script("window.setInterval=()=>1;")
                page.route("**/api/state", lambda r: r.fulfill(
                    status=200, body=json.dumps(
                        {"ok": True, "users": [], "version": "t"})))
                page.goto("http://127.0.0.1:8936/index.html",
                          wait_until="domcontentloaded")
                page.wait_for_function(
                    "typeof renderChannelState==='function'", timeout=12000)

                def probe(payload, view):
                    page.route("**/api/login-state", lambda r: r.fulfill(
                        status=200, body=json.dumps(payload)))
                    page.evaluate("""async v => {
                        try{switchView(v);}catch(e){}
                        window.CHANNEL_STATE=null;
                        await loadChannelState(true);   // 刻意不调 loadPacing
                        await new Promise(r=>setTimeout(r,200));
                    }""", view)
                    return page.evaluate("""() => {
                        const el=document.getElementById('navAuth');
                        const r=el.getBoundingClientRect();
                        return {vis:r.width>0&&r.height>0,
                                title:(el.title||'')};
                    }""")

                got["search"] = probe(BAD, "search")
                got["mon"] = probe(BAD, "mon")
                got["ok"] = probe(GOOD, "cfg")
                ctx.close()
            finally:
                b.close()
    finally:
        srv.shutdown()

    assert got["search"]["vis"], \
        "检索页看不到会话失效红点（用户不在健康页就完全无提示）"
    assert got["mon"]["vis"], "监控页看不到会话失效红点"
    assert "H5" in got["search"]["title"], \
        "多会话厂商未指出是哪一端：%r" % got["search"]["title"]
    assert not got["ok"]["vis"], "全部正常时红点仍亮（会变成装饰性噪声）"
