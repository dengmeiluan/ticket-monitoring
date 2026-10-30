# -*- coding: utf-8 -*-
"""r509：槽位徽标的 tooltip 必须说人话——不许把 epoch 浮点直接吐出来。

实测缺陷：`saved_at` 是 epoch 秒（float），旧代码 `String(s.saved_at)`
拼进 tooltip，真实 profile 里的值渲染成

    飞猪 · 账号 a***@b.c · 会话保存于 1793084689.694177 · 尚未核验

既读不出是哪天，也算不出「这会话多新」——而这正是判断要不要重登的依据
（真实值：fliggy PC 6.24 天前、qunar 1.18 天前）。

要求：绝对时刻（对账用）+ 相对时长（判断新鲜度用）同时给出；
`saved_at=0` 仍然只说「未保存会话」，不得编造时间。
"""
import json
import os
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _slots(saved_at):
    base = {"name": "飞猪", "account": "a***@b.c", "requirement": "必须登录",
            "login_url": "https://example.invalid/", "active": False,
            "saving": False, "pending": False, "error": "",
            "needs_login": False, "health_need_login": False,
            "profile": "p", "plat": "fliggy", "saved": True,
            "detail": "", "verified_at": "", "page_ok": False,
            "session_verified": False, "detail_ok": False}
    return {"ok": True, "plats": {}, "slots": {
        "fliggy": dict(base, slot="fliggy", surface="pc",
                       surface_label="PC", status="saved",
                       saved_at=saved_at),
        "fliggy_h5": dict(base, slot="fliggy_h5", surface="h5",
                          surface_label="H5", status="saved",
                          saved_at=saved_at),
    }}


def _tips(saved_at):
    from playwright.sync_api import sync_playwright
    import webui

    tmp = os.path.join(ROOT, "_scratch", "_r509_t")
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as f:
        f.write(webui.PAGE.replace("__PAGEVER__", "r509t"))

    class H(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    _PORT = 0
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(H, directory=tmp))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    ls = _slots(saved_at)
    try:
        with sync_playwright() as drv:
            if not os.path.exists(drv.chromium.executable_path):
                pytest.skip("Chromium 未安装")
            b = drv.chromium.launch()
            try:
                ctx = b.new_context(viewport={"width": 1280, "height": 900})
                page = ctx.new_page()
                page.set_default_timeout(9000)
                page.add_init_script("window.setInterval=()=>1;")
                page.route("**/api/login-state", lambda r: r.fulfill(
                    status=200, body=json.dumps(ls)))
                page.goto(("http://127.0.0.1:%d/index.html" % srv.server_address[1]),
                          wait_until="domcontentloaded")
                page.wait_for_function(
                    "typeof loadChannelState==='function'", timeout=12000)
                page.evaluate("""async () => {
                    await loadChannelState(true);
                    await new Promise(r=>setTimeout(r,200));
                }""")
                return page.evaluate("""() => {
                    let html='';
                    try{html=healthSlotNote('fliggy')||'';}catch(e){return ['ERR:'+e];}
                    const box=document.createElement('div');
                    box.innerHTML=html;
                    return [...box.querySelectorAll('.hslot')]
                      .map(n=>n.getAttribute('title')||'');
                }""")
            finally:
                b.close()
    finally:
        srv.shutdown()
        srv.server_close()


def test_tooltip_does_not_dump_raw_epoch():
    """6.24 天前保存的会话：tooltip 必须是可读时刻 + 相对时长。"""
    saved_at = time.time() - 6.24 * 86400
    tips = _tips(saved_at)
    assert tips and not str(tips[0]).startswith("ERR:"), tips
    tip = tips[0]
    # 原始 epoch 片段不得出现（1793084689.694177 这种）
    assert str(int(saved_at)) not in tip, \
        "tooltip 直接吐了 epoch 秒：%r" % (tip,)
    assert ".694177" not in tip and "e+09" not in tip.lower(), \
        "tooltip 里有浮点尾巴：%r" % (tip,)
    assert "保存于" in tip, "tooltip 没有说明保存时刻：%r" % (tip,)
    assert "天前" in tip, "tooltip 没有给相对时长（判断新鲜度的依据）：%r" % (tip,)
    # 绝对时刻形如 MM-DD HH:MM
    import re
    assert re.search(r"\d{2}-\d{2} \d{2}:\d{2}", tip), \
        "绝对时刻格式不对：%r" % (tip,)


def test_zero_saved_at_is_not_invented():
    """从未保存过：只说「未保存会话」，不得编造时间。"""
    tips = _tips(0)
    assert tips and not str(tips[0]).startswith("ERR:"), tips
    tip = tips[0]
    assert "未保存会话" in tip, "零值没走「未保存」分支：%r" % (tip,)
    assert "保存于" not in tip, "零值却编了一个保存时刻：%r" % (tip,)
    assert "天前" not in tip, "零值却编了相对时长：%r" % (tip,)


def test_recent_save_uses_minutes():
    """刚保存的会话用「分钟前」——用「0 天前」读起来像没保存。"""
    tips = _tips(time.time() - 5 * 60)
    tip = tips[0]
    assert "分钟前" in tip, "刚保存的会话没有用分钟表达：%r" % (tip,)
    assert "0 天前" not in tip, "刚保存却显示「0 天前」：%r" % (tip,)
