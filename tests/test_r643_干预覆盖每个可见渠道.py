# -*- coding: utf-8 -*-
r"""r643：面板上看得见的渠道，就必须能对它施加干预。

用户最高准则点名「可干预」。实测缺口：节流行里 `app_zhixing` 有状态行
（能被看见、能被判断），但自检按钮的渠道清单在前端写死成
`['qunar','fliggy','ctrip','tongcheng','tuniu']`——App 渠道看得到却
点不到任何干预按钮。后端 `probe_channel` 本是通用的
（`get_crawlers([platform])`），缺口纯粹来自前端硬编码。

判据：真渲染，逐个比对「节流行出现的渠道」与「probe 按钮覆盖的渠道」。
负控：把 PROBE 改回写死的 5 家 → app_zhixing 缺按钮，本测试红。
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

ALL = ["qunar", "fliggy", "ctrip", "tongcheng", "tuniu", "app_zhixing"]
PACING = {
    "ok": True, "quiet": {}, "last_round": {"sent": 12, "paced": 5},
    "channels": {p: {"state": "ok",
                     "advice": {"state": "ok", "severity": "ok", "hint": ""}}
                 for p in ALL},
    "cfg": {"warmup_platforms": ["qunar", "fliggy"],
            "health_penalty_enabled": True},
    "coverage": {"sent": [], "ok": []}, "recurrences": [], "effect": {},
    "iv_rate": {},
}
HEALTH = {"ok": True, "rounds": [], "stats": {}, "push": {"channels": {}},
          "paths": {}, "diag": [], "coverage": {}}


def test_every_visible_channel_has_a_probe_button():
    from playwright.sync_api import sync_playwright

    import webui

    tmp = os.path.join(ROOT, "_scratch", "_r643t")
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as f:
        f.write(webui.PAGE.replace("__PAGEVER__", "r643t"))
    import threading
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    class H(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(H, directory=tmp))
    port = srv.server_address[1]
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            if not os.path.exists(pw.chromium.executable_path):
                pytest.skip("chromium 二进制缺失")
            b = pw.chromium.launch()
            try:
                pg = b.new_page(viewport={"width": 1440, "height": 1200})
                pg.set_default_timeout(15000)
                pg.add_init_script("window.setInterval=()=>1;")
                pg.route("**/api/login-state", lambda r: r.fulfill(
                    status=200, body=json.dumps(
                        {"ok": True, "plats": {}, "slots": {}})))
                pg.route("**/api/paths?hours=24", lambda r: r.fulfill(
                    status=200, body=json.dumps(
                        {"ok": True, "demo": False, "platforms": {}})))
                pg.route("**/api/health", lambda r: r.fulfill(
                    status=200, body=json.dumps(HEALTH)))
                pg.route("**/api/pacing", lambda r: r.fulfill(
                    status=200, body=json.dumps(PACING)))
                pg.goto("http://127.0.0.1:%d/index.html" % port,
                        wait_until="domcontentloaded")
                pg.wait_for_function("typeof loadPacing==='function'")
                pg.evaluate("""async () => {
                  try{switchView('mon');}catch(e){}
                  try{showMonTab('health',true);}catch(e){}
                  document.querySelectorAll('#monview,#healthcard')
                    .forEach(e=>{e.hidden=false;e.style.display='';});
                  const pane=document.getElementById('montab-health');
                  if(pane){pane.hidden=false;pane.style.display='';}
                  await loadPacing(true);
                  await new Promise(r=>setTimeout(r,500));
                }""")
                pg.wait_for_timeout(400)
                got = pg.evaluate("""()=>{
                  const box=document.getElementById('paceBox');
                  const rows=[...box.querySelectorAll('.pace-row')].length;
                  const probes=[...box.querySelectorAll('[data-pk^="probe:"]')]
                    .map(e=>e.dataset.pk.replace('probe:',''));
                  return {rows:rows, probes:probes};
                }""")
            finally:
                b.close()
    finally:
        srv.shutdown()
        srv.server_close()

    # 六家都应出现节流行（后端把 channels 全给了）
    assert got["rows"] == len(ALL), (
        "节流行数量 %d ≠ 渠道数 %d" % (got["rows"], len(ALL)))
    # 行上出现的每一家，都必须有对应自检按钮
    missing = [p for p in ALL if p not in got["probes"]]
    assert not missing, (
        "这些渠道在节流面板上看得见、却点不到自检（可干预缺口）：%s"
        % missing)


def test_probe_all_uses_the_same_channel_list():
    """「全部自检」不得再写死渠道：写死 5 家时 App 既不单点也不进批量。

    判据是行为：把 `/api/channel/probe` 打桩记录被请求的 platform，
    点「全部」后要求覆盖全部 6 家。
    """
    from playwright.sync_api import sync_playwright

    import webui

    tmp = os.path.join(ROOT, "_scratch", "_r643t")
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as f:
        f.write(webui.PAGE.replace("__PAGEVER__", "r643b"))
    import threading
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    class H(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(H, directory=tmp))
    port = srv.server_address[1]
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    asked = []
    try:
        with sync_playwright() as pw:
            if not os.path.exists(pw.chromium.executable_path):
                pytest.skip("chromium 二进制缺失")
            b = pw.chromium.launch()
            try:
                pg = b.new_page(viewport={"width": 1440, "height": 1200})
                pg.set_default_timeout(15000)
                pg.add_init_script("window.setInterval=()=>1;")

                def _probe(route):
                    body = json.loads(route.request.post_data or "{}")
                    asked.append(body.get("platform"))
                    route.fulfill(status=200, body=json.dumps(
                        {"ok": True, "rows": 1, "platform": body.get("platform")}))

                pg.route("**/api/channel/probe", _probe)
                pg.route("**/api/login-state", lambda r: r.fulfill(
                    status=200, body=json.dumps(
                        {"ok": True, "plats": {}, "slots": {}})))
                pg.route("**/api/paths?hours=24", lambda r: r.fulfill(
                    status=200, body=json.dumps(
                        {"ok": True, "demo": False, "platforms": {}})))
                pg.route("**/api/health", lambda r: r.fulfill(
                    status=200, body=json.dumps(HEALTH)))
                pg.route("**/api/pacing", lambda r: r.fulfill(
                    status=200, body=json.dumps(PACING)))
                pg.goto("http://127.0.0.1:%d/index.html" % port,
                        wait_until="domcontentloaded")
                pg.wait_for_function("typeof probeAll==='function'")
                pg.evaluate("""async () => {
                  try{switchView('mon');}catch(e){}
                  try{showMonTab('health',true);}catch(e){}
                  document.querySelectorAll('#monview,#healthcard')
                    .forEach(e=>{e.hidden=false;e.style.display='';});
                  const pane=document.getElementById('montab-health');
                  if(pane){pane.hidden=false;pane.style.display='';}
                  await loadPacing(true);
                  await new Promise(r=>setTimeout(r,400));
                }""")
                pg.evaluate("()=>probeAll()")
                pg.wait_for_timeout(2500)
            finally:
                b.close()
    finally:
        srv.shutdown()
        srv.server_close()

    missing = [p for p in ALL if p not in asked]
    assert not missing, (
        "「全部自检」漏掉了这些渠道（写死的清单）：%s；实际请求 %s"
        % (missing, asked))
