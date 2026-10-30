# -*- coding: utf-8 -*-
"""r513：顶部「去登录」必须点名是哪一端，而不是一个没有区分度的数字。

飞猪 PC 与 H5 是**两套 cookie**（`core/login_slots.py`: fliggy / fliggy_h5，
各自独立需要重登）。实测旧实现按钮文字恒为「需处理 N · 去登录」：

    N=1，只坏 H5  →  「需处理 1 · 去登录」   看不出是 PC 还是 H5
    N=1，只坏 PC  →  「需处理 1 · 去登录」   与上一行完全一样
    两个都坏      →  「需处理 2 · 去登录」

读者必须点开配置页才知道要核哪一端，而这是每次失败后**第一眼**要做的判断。
（悬停 title 里有名字，但手机上没有悬停。）

现在按槽位直接点名：单槽位写全名；同厂多端合写成「飞猪 PC / H5」；
跨厂商用顿号列出。按钮宽度经 390 / 1280 两档验证不截断、不横向溢出。
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


def _slot(plat, name, surface, surface_label, need):
    return {"plat": plat, "name": name, "surface": surface,
            "surface_label": surface_label, "account": "a***@b.c",
            "requirement": "必须登录", "login_url": "https://x.invalid/",
            "active": False, "saving": False, "pending": False, "error": "",
            "saved": True,
            "status": "login_required" if need else "available",
            "needs_login": need, "health_need_login": need,
            "profile": "p", "saved_at": 0, "detail": "", "verified_at": "",
            "page_ok": False, "session_verified": False,
            "detail_ok": not need}


_CASES = {
    "single_h5": {"fliggy": dict(_slot("fliggy", "飞猪 PC", "pc", "PC", False),
                                 slot="fliggy"),
                  "fliggy_h5": dict(_slot("fliggy", "飞猪 H5", "h5", "H5", True),
                                    slot="fliggy_h5")},
    "both_fliggy": {"fliggy": dict(_slot("fliggy", "飞猪 PC", "pc", "PC", True),
                                   slot="fliggy"),
                    "fliggy_h5": dict(_slot("fliggy", "飞猪 H5", "h5", "H5", True),
                                      slot="fliggy_h5")},
    "cross_plat": {"fliggy": dict(_slot("fliggy", "飞猪 PC", "pc", "PC", True),
                                  slot="fliggy"),
                   "qunar": dict(_slot("qunar", "去哪儿", "", "全端", True),
                                 slot="qunar")},
    "single_plat": {"ctrip": dict(_slot("ctrip", "携程", "", "全端", True),
                                  slot="ctrip")},
}


def _button(slots, width):
    from playwright.sync_api import sync_playwright
    import webui

    tmp = os.path.join(ROOT, "_scratch", "_r513_t")
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as f:
        f.write(webui.PAGE.replace("__PAGEVER__", "r513t"))

    class H(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    # 端口用 0 让内核分配：五个用例串行各起一次服务，写死端口在并发门禁下
    # 会撞上 `ERR_SOCKET_NOT_CONNECTED`（实测 r519 门禁 5 条全红、单跑全绿）。
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(H, directory=tmp))
    srv.daemon_threads = True
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    body = json.dumps({"ok": True, "plats": {}, "slots": slots})

    def handler(r):
        r.fulfill(status=200, body=body)

    try:
        with sync_playwright() as drv:
            if not os.path.exists(drv.chromium.executable_path):
                pytest.skip("Chromium 未安装")
            b = drv.chromium.launch()
            try:
                ctx = b.new_context(viewport={"width": width, "height": 900})
                page = ctx.new_page()
                page.set_default_timeout(9000)
                page.add_init_script("window.setInterval=()=>1;")
                page.route("**/api/login-state", handler)
                page.goto("http://127.0.0.1:%d/index.html" % port,
                          wait_until="domcontentloaded")
                page.wait_for_function(
                    "typeof loadChannelState==='function'", timeout=12000)
                page.evaluate("""async () => {
                    await loadChannelState(true);
                    await new Promise(r=>setTimeout(r,200));
                }""")
                return page.evaluate("""() => {
                    const ha=document.getElementById('hauthact');
                    return {hidden:ha.hidden, text:(ha.textContent||'').trim(),
                            p:ha.dataset.p,
                            cut:ha.scrollWidth>ha.clientWidth+1,
                            docOvf:document.documentElement.scrollWidth>
                                   document.documentElement.clientWidth+1};
                }""")
            finally:
                b.close()
    finally:
        srv.shutdown()
        srv.server_close()


def test_single_broken_slot_names_that_slot():
    """只坏 H5：按钮必须写出「飞猪 H5」，不能只是一个数字。"""
    r = _button(_CASES["single_h5"], 1280)
    assert r["hidden"] is False, "只坏一端却没亮「去登录」：%r" % (r,)
    assert "飞猪 H5" in r["text"], "没有点名是哪一端：%r" % (r,)
    assert r["text"] != "需处理 1 · 去登录", "仍是那个没有区分度的数字"
    assert r["p"] == "fliggy_h5", "点击定位的槽位不对：%r" % (r,)


def test_both_surfaces_of_one_vendor_are_merged_not_repeated():
    """两端都坏：写成「飞猪 PC / H5」，不是「飞猪 PC 飞猪 H5」。"""
    r = _button(_CASES["both_fliggy"], 1280)
    assert "PC" in r["text"] and "H5" in r["text"], r
    assert r["text"].count("飞猪") == 1, \
        "同一厂商名重复出现，读起来像两家：%r" % (r,)


def test_cross_vendor_needs_are_both_listed():
    r = _button(_CASES["cross_plat"], 1280)
    assert "飞猪" in r["text"] and "去哪儿" in r["text"], \
        "跨厂商只点了一家：%r" % (r,)


def test_single_vendor_slot_has_no_dangling_surface():
    """单槽位厂商（携程/去哪儿/同程/途牛）不拼端名，避免「携程 全端」。"""
    r = _button(_CASES["single_plat"], 1280)
    assert r["text"].startswith("携程"), r
    assert "全端" not in r["text"], \
        "单槽位厂商被拼上了「全端」，读起来像有多端：%r" % (r,)


def test_button_does_not_overflow_on_narrow_screens():
    """390 档：点名会变长，不得截断或撑破页面。"""
    for case in ("both_fliggy", "cross_plat"):
        r = _button(_CASES[case], 390)
        assert r["cut"] is False, "%s 按钮文字被截断：%r" % (case, r)
        assert r["docOvf"] is False, "%s 页面横向溢出：%r" % (case, r)
