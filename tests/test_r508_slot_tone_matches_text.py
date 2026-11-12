# -*- coding: utf-8 -*-
"""r508：登录槽位徽标的颜色必须和它自己的文字同义。

实测缺陷：`saved`（只保存了会话、**从未核验**）在色调判定里被并进
`ok` 分支——

    const ok = s.status==='available' || s.status==='page_ok'
               || (s.saved && !s.needs_login);

于是同一枚徽标：底色是「成功」绿、文字却是「已存待验」。飞猪 PC / H5
两端长期停在这个状态（会话存了、没有任何核验证据），读者会把绿读成
「已生效」，而这恰恰是「还不知道能不能用」。

判据：绿色只能来自**证据**——真出过明细（available）或入口核验通过
（page_ok）。待验归 warn（琥珀），与文字同义。
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


def _login_state():
    """同一厂商两个槽位：小标只在「有多个独立会话」的厂商上渲染，
    所以这里必须让 PC 与 H5 同时在场（飞猪就是这种形态）。
    三个证据强度各一档：已存待验 / 明细可用 / 入口可达。"""
    base = {"name": "飞猪", "account": "a***@b.c", "requirement": "必须登录",
            "login_url": "https://example.invalid/", "active": False,
            "saving": False, "pending": False, "error": "",
            "needs_login": False, "health_need_login": False,
            "profile": "p", "saved_at": 0, "plat": "fliggy"}
    return {"ok": True, "plats": {}, "slots": {
        "fliggy": dict(base, slot="fliggy", surface="pc",
                       surface_label="PC", saved=True, status="saved",
                       detail="", verified_at="", page_ok=False,
                       session_verified=False, detail_ok=False),
        "fliggy_h5": dict(base, slot="fliggy_h5", surface="h5",
                          surface_label="H5", saved=True,
                          status="page_ok", detail="页面未命中登录墙/验证",
                          verified_at="2026-10-29 10:00:00", page_ok=True,
                          session_verified=True, detail_ok=False),
    }}


def test_saved_but_unverified_slot_is_not_green():
    from playwright.sync_api import sync_playwright
    import webui

    tmp = os.path.join(ROOT, "_scratch", "_r508_t")
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as f:
        f.write(webui.PAGE.replace("__PAGEVER__", "r508t"))

    class H(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    _PORT = 0
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(H, directory=tmp))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    ls = _login_state()

    def _paths():
        out = {}
        for p in ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu"):
            out[p] = {
                "paths": {"PC": {"attempts": 8, "ok": 7, "rate": 0.875}},
                "retired_paths": [],
                "scopes": {"dom": {"query_rate": 0.9, "query_attempts": 10},
                           "intl": {"query_rate": 0.5, "query_attempts": 10}},
                "query_attempts": 20, "query_ok": 14,
                "last_ok_at": "2026-10-29 03:00:00"}
        return {"ok": True, "demo": False, "platforms": out}

    out = {}
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
                    status=200, body=json.dumps(ls)))
                page.route("**/api/paths?hours=24", lambda r: r.fulfill(
                    status=200, body=json.dumps(_paths())))
                page.route("**/api/health", lambda r: r.fulfill(
                    status=200, body=json.dumps(
                        {"ok": True, "demo": False,
                         "platforms": {}, "by_scope": {},
                         "paths": _paths()["platforms"]})))
                page.goto(("http://127.0.0.1:%d/index.html" % srv.server_address[1]),
                          wait_until="domcontentloaded")
                page.wait_for_function(
                    "typeof loadChannelState==='function'", timeout=12000)
                page.evaluate("""async () => {
                    try{switchView('mon');}catch(e){}
                    try{showMonTab('health',true);}catch(e){}
                    document.querySelectorAll('#monview, #healthcard')
                      .forEach(e=>{e.hidden=false;e.style.display='';});
                    const pane=document.getElementById('montab-health');
                    if(pane){pane.hidden=false;pane.style.display='';}
                    await loadChannelState(true);
                    await new Promise(r=>setTimeout(r,300));
                }""")
                out = page.evaluate("""() => {
                    /* 直接调用产品自己的渲染函数，再解析它吐出的徽标：
                       走 .hslot 的选择器要先把整张健康卡的数据喂全（rounds/
                       channels），否则量到的是「卡没渲染」，不是「颜色错了」——
                       那是两个不同的事实，不能混。 */
                    let html='';
                    try{html=healthSlotNote('fliggy')||'';}catch(e){return {err:String(e)};}
                    const box=document.createElement('div');
                    box.innerHTML=html;
                    const nodes=[...box.querySelectorAll('.hslot')];
                    const res={_n:nodes.length};
                    nodes.forEach(n=>{
                      const t=(n.textContent||'').trim();
                      const cls=n.className||'';
                      if(/待验/.test(t))res.pending={t:t, cls:cls};
                      if(/明细可用/.test(t))res.available={t:t, cls:cls};
                      if(/入口可达/.test(t))res.pageOk={t:t, cls:cls};
                    });
                    return res;
                }""")
                ctx.close()
            finally:
                b.close()
    finally:
        srv.shutdown()
        srv.server_close()

    assert not out.get("err"), "渲染函数抛错：%r" % (out,)
    assert out.get("_n", 0) >= 2, "徽标没有渲染出来：%r" % (out,)
    pend = out["pending"]
    assert "ok" not in (pend["cls"] or "").split(), \
        "「已存待验」被染成成功绿（文字说待验、颜色说已生效）：%r" % (pend,)
    assert "warn" in (pend["cls"] or "").split(), \
        "「已存待验」不是「还不知道」的琥珀档：%r" % (pend,)
    # 有证据的一档仍然是绿：修待验不许把真证据一起打灰
    assert "pageOk" in out, "入口可达档没有渲染：%r" % (out,)
    assert "ok" in (out["pageOk"]["cls"] or "").split(), \
        "入口可达丢了绿色：%r" % (out["pageOk"],)
