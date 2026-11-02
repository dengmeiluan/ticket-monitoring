# -*- coding: utf-8 -*-
"""r905：hint 承诺「可点自检」的建议，行内必须有自检按钮。

r669 给 `action=probe` 的四类建议补了自检按钮，但 `path_degraded/route`
的两条 hint 也写着「可点『自检』验证这条路 / 这条域的路」，而按钮分支只认
probe——这类行只剩「展开溯源」，用户照提示找不到按钮，等于把人晾在原地。

判据三层：
  1. 行为层：用真实路径账输入 `advise()`，复现 path_degraded/route 且 hint
     含「自检」；
  2. 源码契约：扫描 `advise()` 里所有 hint 含「自检」的 action，webui 的
     自检按钮分支必须覆盖每一个（当前 probe + route）；
  3. 渲染层：拦截 `/api/pacing` 注入 route 建议，真浏览器里该行必须出现
     `data-pk="ctrip:probe"` 的「自检」按钮。
"""
import ast
import json
import os
import socket
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _route_advice():
    from core.pacing import advise
    now = time.time()
    last = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - 60))
    paths = {"H5": {"attempts": 10, "ok": 1, "rate": 0.1,
                    "rate_excl_empty": 0.1, "last_at": last}}
    return advise("ctrip", ch={}, paths=paths, now=now,
                  node={"scopes": {"dom": {"paths": paths}}})


def test_route_advice_promises_probe():
    adv = _route_advice()
    assert adv["state"] == "path_degraded", adv
    assert adv["action"] == "route", adv
    assert "自检" in adv["hint"], adv["hint"]


def test_probe_button_covers_every_action_that_promises_it():
    src = open(os.path.join(ROOT, "core", "pacing.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    promised = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = {}
        for key_node, value_node in zip(node.keys, node.values):
            if isinstance(key_node, ast.Constant) and isinstance(
                    key_node.value, str):
                keys[key_node.value] = value_node
        if "action" not in keys or "hint" not in keys:
            continue
        if "自检" not in (ast.get_source_segment(src, node) or ""):
            continue
        action = keys["action"]
        if isinstance(action, ast.Constant) and isinstance(action.value, str):
            promised.add(action.value)
    assert {"probe", "route"} <= promised, (
        "advise() 里承诺「自检」的 action 集合变了：%s"
        % sorted(promised))

    web = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    start = web.index("const _advAct=")
    window = web[start:start + 1200]
    cond_start = window.index("if(")
    cond = window[cond_start:window.index("ac.push", cond_start)]
    missing = [a for a in sorted(promised) if a not in cond]
    assert not missing, (
        "这些 action 的 hint 让人点「自检」，但按钮分支没覆盖：%s\n%s"
        % (missing, cond))
    # 按钮本体在条件之后的块里；条件里只需要动作名，别把整个分支
    # 截到第一个 ac.push（那正是 probe 按钮自己）。
    body = window[cond_start:cond_start + 700]
    assert "probeNow" in body and ":probe" in body, (
        "分支没有真的渲染自检按钮：%s" % body)


def _payloads(advice):
    paths = {
        "ctrip": {
            "paths": {"H5": {"attempts": 12, "ok": 5, "rate": 0.417}},
            "retired_paths": [],
            "scopes": {"dom": {"query_rate": 0.95, "query_attempts": 9}},
            "query_attempts": 18, "query_ok": 9,
            "last_ok_at": "2026-11-02 23:00:00",
        },
    }
    pacing = {
        "ok": True, "quiet": {},
        "last_round": {"at": "2026-11-02 23:00:00", "sent": 1,
                       "paced": 0, "fast": 1, "slow": 0, "skip": 0,
                       "trips": []},
        "channels": {
            "ctrip": {"state": "", "needs_login": False, "scene": {},
                      "advice": advice, "health": {}},
        },
        "cfg": {"warmup_platforms": [], "health_penalty_enabled": True},
        "coverage": {"sent": ["ctrip"], "ok": ["ctrip"], "ratio": 1.0},
        "recurrences": [], "effect": {}, "iv_rate": {},
    }
    return paths, pacing


def test_route_advice_row_renders_probe_button():
    playwright = pytest.importorskip("playwright.sync_api")
    import webui

    advice = _route_advice()
    paths, pacing = _payloads(advice)
    tmp = os.path.join(ROOT, "_scratch", "_r905")
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(webui._page_html("r905"))

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    srv = ThreadingHTTPServer(
        ("127.0.0.1", port), partial(Handler, directory=tmp))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with playwright.sync_playwright() as drv:
            if not os.path.exists(drv.chromium.executable_path):
                pytest.skip("Chromium 未安装")
            browser = drv.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.set_default_timeout(12000)
                page.route("**/api/login-state", lambda r: r.fulfill(
                    status=200, body=json.dumps(
                        {"ok": True, "plats": {}, "slots": {}})))
                page.route("**/api/paths?hours=24", lambda r: r.fulfill(
                    status=200, body=json.dumps(
                        {"ok": True, "demo": False, "platforms": paths})))
                page.route("**/api/pacing", lambda r: r.fulfill(
                    status=200, body=json.dumps(pacing)))
                page.goto("http://127.0.0.1:%d/index.html" % port,
                          wait_until="domcontentloaded")
                page.wait_for_function(
                    "typeof loadPacing==='function'", timeout=12000)
                page.evaluate("""async () => {
                    try{switchView('mon');}catch(e){}
                    try{showMonTab('health',true);}catch(e){}
                    const pane=document.getElementById('montab-health');
                    if(pane){pane.hidden=false;pane.style.display='';}
                    await loadPacing(true);
                    await new Promise(r=>setTimeout(r,300));
                }""")
                got = page.evaluate("""() => {
                    const rows=[...document.querySelectorAll(
                        '#paceBox .pace-row')];
                    const row=rows.find(r=>/携程/.test(
                        (r.querySelector('.nm-t')||{}).textContent||''));
                    const btn=row&&row.querySelector(
                        '[data-pk="ctrip:probe"]');
                    return {
                        row:!!row,
                        title:row?(row.getAttribute('title')||''):'',
                        btn:!!btn,
                        text:btn?btn.textContent.trim():'',
                        onclick:btn?(btn.getAttribute('onclick')||''):'',
                    };
                }""")
            finally:
                browser.close()
    finally:
        srv.shutdown()

    assert got["row"], "找不到携程的节流行"
    assert "自检" in got["title"], (
        "行 title 没有承载 hint，判据失去锚点：%r" % got["title"][:120])
    assert got["btn"], (
        "hint 让用户点「自检」，行内却没有自检按钮：%r" % got)
    assert got["text"] == "自检", got
    assert "probeNow" in got["onclick"], got
