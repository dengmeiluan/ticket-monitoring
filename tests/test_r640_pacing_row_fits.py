# -*- coding: utf-8 -*-
r"""r640：节流行的结论段（e1）不得溢出，且整行高度受控。

实测形态（注入「两个域都偏低 + 一条最差通路」的载荷，1440 档）：

    e1 溢出 899/500，行高从 44 涨到 99；390 档涨到 152。

根因：e1 把「域 + 查询 N%（M 次，低于 85% 线）」写了两遍，再叠一条
「最差通路 … 该域查询率已把它摊到 N 次查询里」。读者真正需要的是
「哪个域低、多少」；门槛值与样本数属于解释，应进 title。

判据：真渲染，量 e1 的 scrollWidth/clientWidth 与整行高度。
负控：把 e1 改回「域 + 查询 N%（M 次，低于 85% 线）」长写法 → 溢出。
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PACING = {
    "ok": True, "quiet": {}, "last_round": {"sent": 12, "paced": 5},
    "channels": {"fliggy": {
        "state": "ok",
        "advice": {"state": "path_degraded", "action": "route",
                   "severity": "auto", "eta_s": 0,
                   "hint": "国际 H5 有效率偏低"}}},
    "cfg": {"health_penalty_enabled": True, "health_ok_ratio": 0.7,
            "health_slow_ratio": 0.4, "health_slow_factor": 1.5,
            "health_slowest_factor": 3, "health_min_samples": 5,
            "warmup_platforms": []},
    "coverage": {"sent": [], "ok": []}, "recurrences": [], "effect": {},
    "iv_rate": {},
}

# 两个域都低于 85%，且域内各有一条尝试级很低的通路：最容易把 e1 撑爆
PATHS = {"fliggy": {
    "paths": {"H5": {"attempts": 32, "rate": 0.25, "login": 2, "soft": 1}},
    "retired_paths": [],
    "scopes": {
        "intl": {"attempts": 32, "rate": 0.25, "query_attempts": 12,
                 "query_rate": 0.42, "query_attempts_live": 12,
                 "query_rate_live": 0.42,
                 "paths": {"H5": {"attempts": 32, "rate": 0.25}}},
        "dom": {"attempts": 15, "rate": 0.8, "query_attempts": 8,
                "query_rate": 0.75, "query_attempts_live": 8,
                "query_rate_live": 0.75,
                "paths": {"H5": {"attempts": 15, "rate": 0.8}}}},
    "query_attempts_live": 20, "query_rate_live": 0.55}}

HEALTH = {"ok": True, "rounds": [], "stats": {}, "push": {"channels": {}},
          "paths": PATHS, "diag": [], "coverage": {}}


def _measure(width):
    from playwright.sync_api import sync_playwright

    import webui

    tmp = os.path.join(ROOT, "_scratch", "_r640t")
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as f:
        f.write(webui.PAGE.replace("__PAGEVER__", "r640t"))
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
                pg = b.new_page(viewport={"width": width, "height": 1200})
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
                return pg.evaluate("""()=>{
                  const box=document.getElementById('paceBox');
                  const row=[...box.querySelectorAll('.pace-row')]
                    .find(e=>/路径劣化/.test(e.innerText));
                  if(!row)return {err:'no row', boxH:box?box.getBoundingClientRect().height:-1,
                                  boxHidden: box?getComputedStyle(box).display:'?'};
                  /* 元素必须真的可见，否则 Range/rect 全是 0（实测踩过：
                     lines 与 h 都返回 0，判据恒真）。 */
                  const vis=row.getBoundingClientRect();
                  if(vis.width<=0||vis.height<=0)
                    return {err:'row not visible', h:Math.round(vis.height)};
                  const e1=row.querySelector('.e1');
                  const r=row.getBoundingClientRect();
                  /* 宽档 e1 是 nowrap+ellipsis，scrollWidth 不会超（看不出问题）；
                     真正撑高整行的是窄档 white-space:normal 后的**行数**。
                     所以用 Range 数文本实际占了几个视觉行。 */
                  let lines=0;
                  try{const rg=document.createRange();
                    rg.selectNodeContents(e1);
                    lines=rg.getClientRects().length;}catch(e){}
                  const lh=e1?parseFloat(getComputedStyle(e1).lineHeight)||0:0;
                  return {lines:lines, lh:Math.round(lh),
                          h:Math.round(r.height),
                          txt:e1?e1.innerText.slice(0,120):''};
                }""")
            finally:
                b.close()
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.parametrize("width,cap", [(1440, 48), (700, 96), (390, 128)])
def test_path_degraded_row_keeps_its_height(width, cap):
    """e1 的文本行数与整行高度都要受控。

    宽档 e1 是 nowrap+ellipsis，长文只会被省略号截断（读不全文），
    窄档是 normal 会折行（把整行撑高）。两个后果都要拦：
      - 行数 ≤ 2：超过就是「一行塞不下」；
      - 行高 ≤ 同档上限：窄档折行会顶高整行。
    """
    got = _measure(width)
    assert not got.get("err"), "飞猪行没渲染出来：%s" % got
    assert got["lines"] <= 2, (
        "w=%d 结论段占 %d 行（该压到 2 行内）：%r"
        % (width, got["lines"], got["txt"]))
    assert got["h"] <= cap, (
        "w=%d 行高 %d 超过同档上限 %d（结论太长）：%r"
        % (width, got["h"], cap, got["txt"]))
