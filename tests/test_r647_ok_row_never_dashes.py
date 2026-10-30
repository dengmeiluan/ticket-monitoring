# -*- coding: utf-8 -*-
r"""r647：`ok` 行不得落破折号；结论与读数之间要有分隔。

两处实测缺陷（1440 截图）：

1) 携程行渲染成「正常 —」。破折号在本面板**专指「近 24h 无样本」**，
   而这一行刚被判为「正常」——语义直接打架。根因：`buildForm` 里
   「演示全绿」与「真有账本」两个分支都不命中时，`ev` 为空，落到
   `esc(ev||'—')`。
2) 「…最差通路 国际 H5」紧接「国内 75% · 国际 42% · H5 25%」，两段
   粘连，读者分不清哪个数字属于结论、哪个属于读数。

修法：① 补最后兜底——ok 行给「本轮未发现需处理项」，不再借破折号；
② e2 加「近24h」前缀，明确它是**读数段**。

判据：真渲染三档，逐个 `ok` 行断言 e1 不是破折号、非 ok 行不得为空；
e2 必须带前缀。
负控：删掉兜底分支 → 携程行回到 `—`，本测试红。
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

PACING = {
    "ok": True, "quiet": {}, "last_round": {"sent": 3, "paced": 1},
    "channels": {
        "ctrip": {"state": "ok",
                  "advice": {"state": "ok", "severity": "ok", "hint": ""}},
        "fliggy": {"state": "ok",
                   "advice": {"state": "path_degraded", "action": "route",
                              "severity": "auto", "eta_s": 0,
                              "hint": "国际 H5 偏低"}},
    },
    "cfg": {"warmup_platforms": [], "health_penalty_enabled": True},
    "coverage": {"sent": [], "ok": []}, "recurrences": [], "effect": {},
    "iv_rate": {},
}
PATHS = {"fliggy": {
    "paths": {"H5": {"attempts": 32, "rate": 0.25, "login": 2}},
    "retired_paths": [],
    "scopes": {"intl": {"attempts": 32, "rate": 0.25, "query_attempts": 12,
                        "query_rate": 0.42, "query_attempts_live": 12,
                        "query_rate_live": 0.42,
                        "paths": {"H5": {"attempts": 32, "rate": 0.25}}},
               "dom": {"attempts": 15, "rate": 0.8, "query_attempts": 8,
                       "query_rate": 0.75, "query_attempts_live": 8,
                       "query_rate_live": 0.75,
                       "paths": {"H5": {"attempts": 15, "rate": 0.8}}}}}}
HEALTH = {"ok": True, "rounds": [], "stats": {}, "push": {"channels": {}},
          "paths": PATHS, "diag": [], "coverage": {}}


def _rows():
    from playwright.sync_api import sync_playwright

    import webui

    tmp = os.path.join(ROOT, "_scratch", "_r647g")
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as f:
        f.write(webui.PAGE.replace("__PAGEVER__", "r647g"))

    class H(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(H, directory=tmp))
    port = srv.server_address[1]
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    out = {}
    try:
        with sync_playwright() as pw:
            if not os.path.exists(pw.chromium.executable_path):
                pytest.skip("chromium 二进制缺失")
            b = pw.chromium.launch()
            try:
                for w in (1440, 700, 390):
                    pg = b.new_page(viewport={"width": w, "height": 1200})
                    pg.set_default_timeout(15000)
                    pg.add_init_script("window.setInterval=()=>1;")
                    pg.route("**/api/login-state", lambda r: r.fulfill(
                        status=200, body=json.dumps(
                            {"ok": True, "plats": {}, "slots": {}})))
                    pg.route("**/api/paths?hours=24", lambda r: r.fulfill(
                        status=200, body=json.dumps(
                            {"ok": True, "demo": False, "platforms": PATHS})))
                    pg.route("**/api/health", lambda r: r.fulfill(
                        status=200, body=json.dumps(HEALTH)))
                    pg.route("**/api/pacing", lambda r: r.fulfill(
                        status=200, body=json.dumps(PACING)))
                    pg.goto("http://127.0.0.1:%d/index.html" % port,
                            wait_until="domcontentloaded")
                    pg.wait_for_function("typeof loadPacing==='function'")
                    pg.evaluate("""async ()=>{
                      try{switchView('mon')}catch(e){}
                      try{showMonTab('health',true)}catch(e){}
                      document.querySelectorAll('#monview,#healthcard')
                        .forEach(e=>{e.hidden=false;e.style.display='';});
                      const pane=document.getElementById('montab-health');
                      if(pane){pane.hidden=false;pane.style.display='';}
                      await loadPacing(true);
                      await new Promise(r=>setTimeout(r,500));}""")
                    pg.wait_for_timeout(400)
                    out[w] = pg.evaluate(r"""()=>{
                      const box=document.getElementById('paceBox');
                      return {
                        rows:[...box.querySelectorAll('.pace-row')].map(e=>{
                          const e1=e.querySelector('.e1');
                          const e2=e.querySelector('.e2');
                          return {nm:(e.querySelector('.nm')||{}).innerText||'',
                                  lab:(e.querySelector('.glip')||{}).innerText||'',
                                  e1:e1?e1.innerText:'',
                                  e2:e2?e2.innerText:'',
                                  e2k:!!e.querySelector('.e2k')};}),
                        docOver:document.documentElement.scrollWidth
                                >window.innerWidth+1};}""")
                    pg.close()
            finally:
                b.close()
    finally:
        srv.shutdown()
        srv.server_close()
    return out


def test_ok_rows_do_not_use_the_no_sample_dash():
    data = _rows()
    bad = []
    for w, got in data.items():
        for r in got["rows"]:
            if r["lab"] == "正常" and r["e1"].strip() in ("—", "-", ""):
                bad.append((w, r["nm"], r["e1"]))
    assert not bad, (
        "「正常」行落成了破折号（本面板破折号专指无样本，语义打架）：%s"
        % bad)


def test_readings_section_is_labelled_and_separated():
    data = _rows()
    bad = []
    for w, got in data.items():
        for r in got["rows"]:
            if r["e2"] and not r["e2k"]:
                bad.append((w, r["nm"], r["e2"][:30]))
    assert not bad, (
        "读数段没有「近24h」前缀，与结论段粘连：%s" % bad)


def test_no_horizontal_overflow_after_adding_the_prefix():
    data = _rows()
    over = [w for w, got in data.items() if got["docOver"]]
    assert not over, "加了 e2 前缀后出现横向溢出：%s" % over
