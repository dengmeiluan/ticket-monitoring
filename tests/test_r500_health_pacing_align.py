# -*- coding: utf-8 -*-
"""r500：健康卡徽标 与 节流行读数必须是同一个数（可对齐）。

这两处历史上打过架：徽标按查询口径显示 13%，节流面板按尝试口径显示 73%，
并列在同一屏，读者无法判断哪个是真的。r406 统一到「在用查询口径」后应当
一致——但一直没有一条**渲染级**的守卫，只有源码字符串断言。

本契约用一份「两种口径会给出不同数字」的载荷（在用 44% vs 尝试 61%）
真渲染，逐项比对两个面板显示的数字：
  厂商级：健康卡「飞猪 44%」↔ 节流行「查询 44%」
  分域  ：两边都是「国内 90% · 国际 44%」
  分通路：两边都是「PC 60% · H5 42%」
如果哪天某一边退回尝试口径，就会显示 61%，立即对不上。
"""
import json
import os
import re
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PATHS = {"fliggy": {
    "paths": {"PC": {"attempts": 10, "ok": 6, "rate": 0.6},
              "H5": {"attempts": 26, "ok": 11, "rate": 0.423}},
    "retired_paths": [],
    "scopes": {"dom": {"query_rate": 0.9, "query_attempts": 10},
               "intl": {"query_rate": 0.44, "query_attempts": 25}},
    # 尝试口径刻意给一个不同的数：若某一边误用它，立刻看得出
    "query_rate": 0.61, "query_attempts": 36, "query_ok": 22,
    "query_rate_live": 0.44, "query_attempts_live": 25,
    "last_ok_at": "2026-10-29 03:45:00"}}

HEALTH = {
    "ok": True,
    "rounds": [{"ts": "2026-10-29 03:45", "plats": {
        "fliggy": {"s": "part", "ok": 1, "tot": 2, "cal": 0, "detail": 1}}}],
    "stats": {"fliggy": {"ok": 22, "part": 2, "fail": 12, "maint": 0,
                         "rate": 0.61, "cal": 0, "detail": 22, "auth": 5}},
    "push": {"channels": {}}, "paths": PATHS,
    "diag": [], "coverage": {}}

PACING = {"ok": True, "quiet": {}, "last_round": {}, "channels": {
    "fliggy": {"state": "ok", "needs_login": False, "scene": {},
               "advice": {"state": "ok", "action": "none", "severity": "ok",
                          "hint": "正常", "eta_s": 0}}},
    "cfg": {"warmup_platforms": [], "health_penalty_enabled": True},
    "coverage": {"sent": [], "ok": []}, "recurrences": [], "effect": {},
    "iv_rate": {}}


def test_health_badge_matches_pacing_row():
    from playwright.sync_api import sync_playwright
    import webui

    tmp = os.path.join(ROOT, "_scratch", "_r500_t")
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as f:
        f.write(webui.PAGE.replace("__PAGEVER__", "r500t"))

    class H(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 8942), partial(H, directory=tmp))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    got = {}
    try:
        with sync_playwright() as drv:
            if not os.path.exists(drv.chromium.executable_path):
                pytest.skip("Chromium 未安装")
            b = drv.chromium.launch()
            try:
                ctx = b.new_context(viewport={"width": 1440,
                                              "height": 1000})
                page = ctx.new_page()
                page.set_default_timeout(9000)
                page.add_init_script("window.setInterval=()=>1;")
                page.route("**/api/login-state", lambda r: r.fulfill(
                    status=200, body=json.dumps(
                        {"ok": True, "plats": {}, "slots": {}})))
                page.route("**/api/paths?hours=24", lambda r: r.fulfill(
                    status=200, body=json.dumps(
                        {"ok": True, "demo": False, "platforms": PATHS})))
                page.route("**/api/health", lambda r: r.fulfill(
                    status=200, body=json.dumps(HEALTH)))
                page.route("**/api/pacing", lambda r: r.fulfill(
                    status=200, body=json.dumps(PACING)))
                page.goto("http://127.0.0.1:8942/index.html",
                          wait_until="domcontentloaded")
                page.wait_for_function(
                    "typeof loadPacing==='function'", timeout=12000)
                page.evaluate("""async h => {
                    try{switchView('mon');}catch(e){}
                    try{showMonTab('health',true);}catch(e){}
                    document.querySelectorAll('#monview, #healthcard')
                      .forEach(e=>{e.hidden=false;e.style.display='';});
                    const pane=document.getElementById('montab-health');
                    if(pane){pane.hidden=false;pane.style.display='';}
                    await loadChannelState(true);
                    renderHealth(h);
                    await loadPacing(true);
                    await new Promise(r=>setTimeout(r,300));
                }""", HEALTH)
                got = page.evaluate("""() => {
                    const card=document.getElementById('healthcard');
                    const h=[...card.querySelectorAll('.hrow')]
                      .find(x=>x.textContent.includes('飞猪'));
                    const box=document.getElementById('paceBox');
                    const p=[...box.querySelectorAll('.pace-row')]
                      .find(x=>x.textContent.includes('飞猪'));
                    return {h:h?h.innerText.replace(/\\s+/g,' '):'',
                            p:p?p.innerText.replace(/\\s+/g,' '):''};
                }""")
                ctx.close()
            finally:
                b.close()
    finally:
        srv.shutdown()

    h, p = got["h"], got["p"]
    assert h and p, "两张表都没渲染出飞猪行：%r" % got
    # 1) 厂商级：两边都必须是在用口径 44%，不得出现尝试口径 61%
    assert re.search(r"飞猪\s+44%", h), "健康卡徽标不是在用口径 44%%：%r" % h
    assert "查询 44%" in p, "节流行查询读数不是在用口径 44%%：%r" % p
    assert "61%" not in h and "61%" not in p, \
        "有一边退回了尝试口径 61%%：health=%r pacing=%r" % (h, p)
    # 2) 分域必须一致
    for tok in ("国内 90%", "国际 44%"):
        assert tok in h, "健康卡缺分域 %r：%r" % (tok, h)
        assert tok in p, "节流行缺分域 %r：%r" % (tok, p)
    # 3) 分通路必须一致。健康卡的通路小标自 r636 起带口径词与样本数
    #    （`PC 单次 60%（12 次）`），节流面板仍是 `PC 60%`；两者数值必须
    #    相同，但允许健康卡在名称与百分比之间夹一个口径词。
    for tok in ("PC 60%", "H5 42%"):
        name, pct = tok.split(" ")
        pat = r"%s (?:单次 )?%s" % (re.escape(name), re.escape(pct))
        assert re.search(pat, h), "健康卡缺分通路 %r：%r" % (tok, h)
        assert tok in p, "节流行缺分通路 %r：%r" % (tok, p)
