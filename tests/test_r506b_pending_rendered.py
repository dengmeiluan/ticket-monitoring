# -*- coding: utf-8 -*-
"""r506 渲染级：面板上「待判」必须真的出现在界面上，且与成功率分开写。

源码断言挡不住「字段读到了但没渲染」——r490 就是这么踩的（后端字段名
与前端读取名不同，契约用的是注入载荷，一直绿）。所以这条真渲染：
给一份 probe 判得了（75%）+ relogin 判不了（92 次待判）的载荷，
读 `.pace-sec .pace-sub` 的可见文本，逐字比对两段都在。
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


def _payloads():
    paths, advice = {}, {}
    for p in ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu"):
        paths[p] = {
            "paths": {"PC": {"attempts": 8, "ok": 7, "rate": 0.875}},
            "retired_paths": [],
            "scopes": {"dom": {"query_rate": 0.9, "query_attempts": 10},
                       "intl": {"query_rate": 0.5, "query_attempts": 10}},
            "query_attempts": 20, "query_ok": 14,
            "last_ok_at": "2026-10-29 03:00:00"}
        advice[p] = {"state": "ok", "action": "none", "severity": "ok",
                     "hint": "近 24h 正常", "eta_s": 0}
    pacing = {"ok": True, "quiet": {},
              "last_round": {"at": "2026-10-29 03:00:00", "sent": 4,
                             "paced": 1, "fast": 2, "slow": 1, "skip": 1,
                             "trips": []},
              "channels": {p: {"state": "ok", "needs_login": False,
                               "scene": {}, "advice": advice[p],
                               "health": {}} for p in advice},
              "cfg": {"warmup_platforms": ["qunar"],
                      "health_penalty_enabled": True},
              "coverage": {"sent": ["ctrip"], "ok": ["ctrip"], "ratio": 1.0},
              "recurrences": [], "effect": {},
              "iv_rate": {
                  "probe": {"n": 4, "healed": 3, "unhealed": 1,
                            "unjudged": 0, "rate": 0.75, "reliable": True},
                  "relogin": {"n": 0, "healed": 0, "unhealed": 0,
                              "unjudged": 92, "rate": None,
                              "reliable": False},
                  "reset": {"n": 1, "healed": 1, "unhealed": 0,
                            "unjudged": 0, "rate": 1.0, "reliable": False}}}
    return paths, pacing


def test_pending_interventions_are_rendered_next_to_the_rate():
    from playwright.sync_api import sync_playwright
    import webui

    tmp = os.path.join(ROOT, "_scratch", "_r506_t")
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as f:
        f.write(webui.PAGE.replace("__PAGEVER__", "r506t"))

    class H(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    _PORT = 0
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(H, directory=tmp))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    paths, pacing = _payloads()
    txt = ""
    try:
        with sync_playwright() as drv:
            if not os.path.exists(drv.chromium.executable_path):
                pytest.skip("Chromium 未安装")
            b = drv.chromium.launch()
            try:
                ctx = b.new_context(viewport={"width": 1280, "height": 1000})
                page = ctx.new_page()
                page.set_default_timeout(9000)
                page.add_init_script("window.setInterval=()=>1;")
                page.route("**/api/login-state", lambda r: r.fulfill(
                    status=200, body=json.dumps(
                        {"ok": True, "plats": {}, "slots": {}})))
                page.route("**/api/paths?hours=24", lambda r: r.fulfill(
                    status=200, body=json.dumps(
                        {"ok": True, "demo": False, "platforms": paths})))
                page.route("**/api/pacing", lambda r: r.fulfill(
                    status=200, body=json.dumps(pacing)))
                page.goto(("http://127.0.0.1:%d/index.html" % srv.server_address[1]),
                          wait_until="domcontentloaded")
                page.wait_for_function(
                    "typeof loadPacing==='function'", timeout=12000)
                page.evaluate("""async () => {
                    try{switchView('mon');}catch(e){}
                    try{showMonTab('health',true);}catch(e){}
                    document.querySelectorAll('#monview, #healthcard')
                      .forEach(e=>{e.hidden=false;e.style.display='';});
                    const pane=document.getElementById('montab-health');
                    if(pane){pane.hidden=false;pane.style.display='';}
                    await loadChannelState(true);
                    await loadPacing(true);
                    await new Promise(r=>setTimeout(r,250));
                }""")
                txt = page.evaluate("""() => {
                    const box=document.getElementById('paceBox');
                    const secs=[...box.querySelectorAll('.pace-sec')]
                      .filter(e=>/干预/.test((e.textContent||'')));
                    if(!secs.length)return {rate:'',pend:'',both:''};
                    const sec=secs[0];
                    const r=sec.querySelector('.pace-ivr');
                    const p=sec.querySelector('.pace-ivp');
                    return {rate:r?(r.textContent||''):'',
                            pend:p?(p.textContent||''):'',
                            both:(sec.textContent||'')};
                }""")
                ctx.close()
            finally:
                b.close()
    finally:
        srv.shutdown()
        srv.server_close()

    assert "近 7 天成功率" in txt["rate"], \
        "面板没有单独渲染成功率：%r" % (txt,)
    assert "75%" in txt["rate"], "判得了的样本没有给出百分比：%r" % (txt,)
    assert "重登 92 次" in txt["pend"] and "待判" in txt["pend"], \
        "判不了的干预没有单独渲染出来：%r" % (txt,)
    # 两段必须是两个节点：混在同一个 span 里会被读成一句话
    assert "待判" not in txt["rate"], \
        "「待判」被混进了成功率那一段：%r" % (txt["rate"],)
    assert "成功率" not in txt["pend"], \
        "成功率被混进了待判那一段：%r" % (txt["pend"],)
    # 整节两段都在场（不是只渲染了其中一段）
    assert "样本不足" in txt["both"] or "解除" in txt["both"], txt["both"]


def test_narrow_width_keeps_both_clauses_readable():
    """390/420 两段读数多出来会把标题行挤坏，必须仍可读且不横向溢出。

    实测（r506 修复前）：两段拼在同一个 `.pace-sub` 里，窄档直接变成
    一段长省略号，两段读数都读不全。现在各自成节点，并且只在有读数时
    才允许该行换行（`.pace-sec:has(.pace-ivr)`），没读数的小节保持单行。
    390 实测：两段各占一行、右边界 327 < 容器 338、无横向溢出。
    """
    from playwright.sync_api import sync_playwright
    import webui

    tmp = os.path.join(ROOT, "_scratch", "_r506n")
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as f2:
        f2.write(webui.PAGE.replace("__PAGEVER__", "r506n"))

    class H(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    _PORT = 0
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(H, directory=tmp))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    paths, pacing = _payloads()
    out = {}
    try:
        with sync_playwright() as drv:
            if not os.path.exists(drv.chromium.executable_path):
                pytest.skip("Chromium 未安装")
            b = drv.chromium.launch()
            try:
                for vw in (420, 390):
                    ctx = b.new_context(viewport={"width": vw, "height": 1200})
                    page = ctx.new_page()
                    page.set_default_timeout(9000)
                    page.add_init_script("window.setInterval=()=>1;")
                    page.route("**/api/login-state", lambda r: r.fulfill(
                        status=200, body=json.dumps(
                            {"ok": True, "plats": {}, "slots": {}})))
                    page.route("**/api/paths?hours=24", lambda r: r.fulfill(
                        status=200, body=json.dumps(
                            {"ok": True, "demo": False, "platforms": paths})))
                    page.route("**/api/pacing", lambda r: r.fulfill(
                        status=200, body=json.dumps(pacing)))
                    page.goto(("http://127.0.0.1:%d/index.html" % srv.server_address[1]),
                              wait_until="domcontentloaded")
                    page.wait_for_function(
                        "typeof loadPacing==='function'", timeout=12000)
                    page.evaluate("""async () => {
                        try{switchView('mon');}catch(e){}
                        try{showMonTab('health',true);}catch(e){}
                        document.querySelectorAll('#monview, #healthcard')
                          .forEach(e=>{e.hidden=false;e.style.display='';});
                        const pane=document.getElementById('montab-health');
                        if(pane){pane.hidden=false;pane.style.display='';}
                        await loadChannelState(true);
                        await loadPacing(true);
                        await new Promise(r=>setTimeout(r,250));
                    }""")
                    out[vw] = page.evaluate("""() => {
                        const box=document.getElementById('paceBox');
                        const secs=[...box.querySelectorAll('.pace-sec')]
                          .filter(e=>/干预/.test(e.textContent||''));
                        const s=secs[0];
                        const r=s.querySelector('.pace-ivr');
                        const p=s.querySelector('.pace-ivp');
                        const sb=s.getBoundingClientRect();
                        const rb=r.getBoundingClientRect();
                        const pb=p.getBoundingClientRect();
                        const secRight=sb.right;
                        const title=[...s.children]
                          .filter(e=>e.tagName==='SPAN'&&!e.classList
                                  .contains('pace-ivr')&&!e.classList
                                  .contains('pace-ivp'))[0];
                        return {
                          rCut: r.scrollWidth>r.clientWidth+1,
                          pCut: p.scrollWidth>p.clientWidth+1,
                          rOver: Math.round(rb.right-secRight),
                          pOver: Math.round(pb.right-secRight),
                          rH: Math.round(rb.height),
                          pH: Math.round(pb.height),
                          boxOvf: box.scrollWidth>box.clientWidth+1,
                          docOvf: document.documentElement.scrollWidth>
                                  document.documentElement.clientWidth+1,
                          titleCut: title?(title.scrollWidth>title.clientWidth+1)
                                         :None};
                    }""")
                    ctx.close()
            finally:
                b.close()
    finally:
        srv.shutdown()
        srv.server_close()

    for vw, d in out.items():
        assert d["boxOvf"] is False, "视口 %d 节流面板横向溢出" % vw
        assert d["docOvf"] is False, "视口 %d 页面横向溢出" % vw
        assert d["rOver"] <= 2 and d["pOver"] <= 2, \
            "视口 %d 读数超出小节右边界（%.*s）：%r" % (vw, 1, "", d)
        assert d["rCut"] is False, "视口 %d 成功率段被截断：%r" % (vw, d)
        assert d["pCut"] is False, "视口 %d 待判段被截断：%r" % (vw, d)
        assert d["rH"] <= 20 and d["pH"] <= 20, \
            "视口 %d 读数自身折行（%r）：单段应保持一行" % (vw, d)

