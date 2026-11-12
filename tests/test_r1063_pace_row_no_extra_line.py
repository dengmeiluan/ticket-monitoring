# -*- coding: utf-8 -*-
"""r1063 T55：我加的读数**不许把渠道行顶出新的一行**。

背景：健康行的 `.e2`（读数行）当前设计是"自己占一行、可折行"（`flex:1 1 100%`）。
r640 那条 48px 上限是更早的假设，与这个设计冲突——**那是设计归属问题，不在这里判**。

这条门禁只管**我加的东西**：会话重建 / 渠道等待 / 降频 三段必须并进**同一条 `.e2`**，
不许再长出第三个块、也不许让行高多出超过一行的高度。

做法：真渲染两次（一次不含我的字段、一次全含），比较
`.ev` 的子块数量 与 行高增量。
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

BASE = {
    "ok": True, "quiet": {}, "last_round": {"sent": 12, "paced": 5},
    "channels": {"fliggy": {"state": "ok",
                            "advice": {"state": "path_degraded",
                                       "action": "route", "severity": "auto",
                                       "eta_s": 0, "hint": "国际 H5 有效率偏低"}}},
    "coverage": {"sent": [], "ok": []}, "recurrences": [], "effect": {},
    "iv_rate": {}, "cfg": {},
}
PATHS = {"fliggy": {"paths": {"H5": {"attempts": 32, "rate": 0.25}},
                    "retired_paths": [],
                    "scopes": {"intl": {"attempts": 32, "rate": 0.25,
                                        "query_attempts": 12,
                                        "query_rate": 0.42}}}}
HEALTH = {"ok": True, "rounds": [], "stats": {}, "push": {"channels": {}},
          "paths": PATHS, "diag": [], "coverage": {}}


def _with_my_fields(pacing):
    out = json.loads(json.dumps(pacing))
    ch = out["channels"]["fliggy"]
    ch["resets"] = 2
    ch["waited_s"] = 210.0
    ch["health_paths"] = {"intl/H5/API": {"penalty": 2}}
    ch["sr"] = {"fails": 3, "kind": "captcha", "day": 1,
                "why": "连续被拦 3 次"}
    return out


def _measure(width, pacing):
    from playwright.sync_api import sync_playwright

    import webui

    tmp = os.path.join(ROOT, "_scratch", "_r1063t55")
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as f:
        f.write(webui.PAGE.replace("__PAGEVER__", "r1063t55"))

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
                pg = b.new_page(viewport={"width": width, "height": 1200})
                pg.set_default_timeout(15000)
                pg.add_init_script("window.setInterval=()=>1;")
                pg.route("**/api/login-state", lambda r: r.fulfill(
                    status=200, body=json.dumps({"ok": True, "plats": {},
                                                 "slots": {}})))
                pg.route("**/api/paths?hours=24", lambda r: r.fulfill(
                    status=200, body=json.dumps({"ok": True, "demo": False,
                                                 "platforms": PATHS})))
                pg.route("**/api/health", lambda r: r.fulfill(
                    status=200, body=json.dumps(HEALTH)))
                pg.route("**/api/pacing", lambda r: r.fulfill(
                    status=200, body=json.dumps(pacing)))
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
                  /* r1147：「节流与干预」默认折叠；行文本须在展开态读取 */
                  const _f=document.getElementById('hpaceFold');
                  if(_f)_f.open=true;
                  await loadPacing(true);
                  await new Promise(r=>setTimeout(r,500));
                }""")
                return pg.evaluate("""()=>{
                  const box=document.getElementById('paceBox');
                  const row=[...box.querySelectorAll('.pace-row')]
                    .find(e=>/路径劣化/.test(e.innerText));
                  if(!row)return {err:'no row'};
                  const ev=row.querySelector('.ev');
                  const e2=row.querySelector('.e2');
                  return {blocks: ev?ev.children.length:0,
                          rowH: Math.round(row.getBoundingClientRect().height),
                          e2txt: e2?(e2.innerText||'').slice(0,120):'',
                          e2title: e2?String(e2.getAttribute('title')||''):''};
                }""")
            finally:
                b.close()
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.parametrize("width", [1440, 700])
def test_my_segments_stay_in_the_same_block(width):
    a = _measure(width, BASE)
    b = _measure(width, _with_my_fields(BASE))
    assert not a.get("err") and not b.get("err"), (a, b)
    assert a["blocks"] == b["blocks"] == 2, (
        ".ev 应只有 e1 + e2 两个块（我加的段必须并进 e2）", a, b)
    # 最多多出一行（16px 量级）——多两行说明又长出了新块
    assert b["rowH"] - a["rowH"] <= 20, (
        "我加的读数把行高顶多了 %dpx" % (b["rowH"] - a["rowH"]))
    assert "已重建" in b["e2txt"] or "重建" in b["e2title"], b


def test_readout_row_has_full_text_in_title():
    """`.e2` 会被裁/折——全文必须挂在 title 上（可识别且零布局代价）。"""
    got = _measure(1440, _with_my_fields(BASE))
    assert got.get("e2title"), got
    # 用本载荷里确实存在的数字（别照抄另一条用例的 75%）
    assert "42%" in got["e2title"], got["e2title"]
