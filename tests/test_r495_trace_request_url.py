# -*- coding: utf-8 -*-
"""r495：溯源必须显示**真实请求地址**。

账本从 r407 起就记 `request_url`（真实库实测 20/20 条都有值），但界面一处
都没显示——用户看到「H5 被拦」却不知道打的是哪个地址，无法判断是入口选错
还是真被拦，属「可定位」缺口。

边界（每条都要钉）：
  1) 有 request_url 的行渲染 `.u`，内容=数据原值，title=全文；
  2) 没有 request_url 的行**不渲染空行**（否则每条多一行空白）；
  3) 不新增网格列（会挤压证据列），而是跨满整行；
  4) 窄档单行省略但不丢信息（title 仍是全文），且不得横向溢出。
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

LONG = ("https://m.ctrip.com/html5/flight/taro/first?from=inner&tripType=ONE_WAY"
        "&depCity=SHA&arrCity=BKK&depDate=2026-11-05&channel=xx&trace=abcdef")
TRACE = {"ok": True, "platform": "fliggy",
         "rows": [
             {"fetched_at": "2026-10-29 03:20:00", "entry_path": "H5",
              "path_status": "login", "note": "登录墙", "request_url": LONG},
             {"fetched_at": "2026-10-29 03:10:00", "entry_path": "PC",
              "path_status": "ok", "note": "出数 12 条", "request_url": ""},
         ],
         "interventions": [], "effect": {}}
PACING = {"ok": True, "quiet": {}, "last_round": {}, "channels": {
    "fliggy": {"state": "ok", "needs_login": False, "scene": {},
               "advice": {"state": "ok", "action": "none", "severity": "ok",
                          "hint": "正常", "eta_s": 0}}},
    "cfg": {"warmup_platforms": [], "health_penalty_enabled": True},
    "coverage": {"sent": [], "ok": []}, "recurrences": [], "effect": {},
    "iv_rate": {}}


def test_trace_shows_request_url_without_breaking_layout():
    from playwright.sync_api import sync_playwright
    import webui

    tmp = os.path.join(ROOT, "_scratch", "_r495_t")
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as f:
        f.write(webui.PAGE.replace("__PAGEVER__", "r495t"))

    class H(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 8939), partial(H, directory=tmp))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    out = {}
    try:
        with sync_playwright() as drv:
            if not os.path.exists(drv.chromium.executable_path):
                pytest.skip("Chromium 未安装")
            b = drv.chromium.launch()
            try:
                for vw in (1440, 420):
                    ctx = b.new_context(viewport={"width": vw,
                                                  "height": 1000})
                    page = ctx.new_page()
                    page.set_default_timeout(9000)
                    page.add_init_script("window.setInterval=()=>1;")
                    page.route("**/api/login-state", lambda r: r.fulfill(
                        status=200, body=json.dumps(
                            {"ok": True, "plats": {}, "slots": {}})))
                    page.route("**/api/paths?hours=24", lambda r: r.fulfill(
                        status=200, body=json.dumps(
                            {"ok": True, "demo": False, "platforms": {}})))
                    page.route("**/api/pacing", lambda r: r.fulfill(
                        status=200, body=json.dumps(PACING)))
                    page.route("**/api/trace*", lambda r: r.fulfill(
                        status=200, body=json.dumps(TRACE)))
                    page.goto("http://127.0.0.1:8939/index.html",
                              wait_until="domcontentloaded")
                    page.wait_for_function(
                        "typeof paceTrace==='function'", timeout=12000)
                    page.evaluate("""async () => {
                        try{switchView('mon');}catch(e){}
                        try{showMonTab('health',true);}catch(e){}
                        document.querySelectorAll('#monview, #healthcard')
                          .forEach(e=>{e.hidden=false;e.style.display='';});
                        const pane=document.getElementById('montab-health');
                        if(pane){pane.hidden=false;pane.style.display='';}
                        await loadPacing(true);
                        await paceTrace('fliggy');
                        await new Promise(r=>setTimeout(r,250));
                    }""")
                    out[vw] = page.evaluate("""() => {
                        const o=document.getElementById('traceOut')||document.body;
                        const us=[...o.querySelectorAll('.pace-tline .u')];
                        // 表头也是一条 .pace-tline（.head），数据行要排除它
                        const dataLines=[...o.querySelectorAll('.pace-tline')]
                          .filter(x=>!x.classList.contains('head'));
                        return {
                          uCount: us.length,
                          text: us[0]?us[0].textContent:'',
                          title: us[0]?(us[0].getAttribute('title')||''):'',
                          truncated: us[0]
                            ?us[0].scrollWidth>us[0].clientWidth+1:false,
                          lineCount: dataLines.length,
                          ovf: o.scrollWidth>o.clientWidth+1,
                        };
                    }""")
                    ctx.close()
            finally:
                b.close()
    finally:
        srv.shutdown()

    for vw in (1440, 420):
        o = out[vw]
        assert o["lineCount"] == 2, "溯源行数异常：%r" % o
        assert o["uCount"] == 1, (
            "视口 %d：URL 行数应为 1（空 request_url 不渲染），实际 %d"
            % (vw, o["uCount"]))
        assert o["text"] == LONG, "URL 文本与账本不一致：%r" % o["text"]
        assert o["title"] == LONG, "title 未给全文（截断后无法定位）：%r" % o["title"]
        assert not o["ovf"], "视口 %d 溯源区横向溢出" % vw
    # 窄档必须靠省略号收敛，而不是撑破
    assert out[420]["truncated"], "窄档未单行省略（会撑破布局）"
