# -*- coding: utf-8 -*-
r"""r645：通路小标不得把「没真正试过」算成「0% 成功率」。

真实库实测（`data/prices.db`，24h）：

    android-runtime  attempts=63  rate=0.0  rate_excl_empty=None  unsupported=63

63 次全是 `unsupported`（Android 运行时未就绪），一次有效尝试都没有。
旧口径 `rate` 把它渲染成「android-runtime 单次 0%（63 次）」——读者
只会理解为「这条路跑了 63 次全失败」，而事实是「根本没跑起来」。

修法：分母改用 `rate_excl_empty`（排除 unsupported/empty）；后端判定
无效样本为 0（显式 null）时说「无有效样本」，并附「无效 N」。

判据是行为：真渲染注入真实形状的载荷，检查小标文本。
负控：把 `_rv` 改回 `_v.rate` → 又出现「单次 0%（63 次）」，本测试红。
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

# 与 path_stats 同形：android-runtime 全是 unsupported；calendar 正常
PATHS = {"app_zhixing": {
    "paths": {"android-runtime": {"attempts": 63, "rate": 0.0,
                                  "rate_excl_empty": None,
                                  "unsupported": 63, "empty": 0},
              "app-calendar": {"attempts": 40, "rate": 1.0,
                               "rate_excl_empty": 1.0, "unsupported": 0,
                               "empty": 0}},
    "retired_paths": [],
    "scopes": {"dom": {"attempts": 63, "rate": 0.5, "query_attempts": 20,
                       "query_rate": 1.0, "query_attempts_live": 20,
                       "query_rate_live": 1.0,
                       "paths": {"android-runtime": {"attempts": 63,
                                                     "rate": 0.0}},
                       "retired_paths": []},
               "intl": {"attempts": 0, "rate": 0.0, "query_attempts": 0,
                        "query_rate": None, "query_attempts_live": 0,
                        "query_rate_live": None, "paths": {},
                        "retired_paths": []}},
    "query_attempts_live": 20, "query_rate_live": 1.0,
    "query_detail_ok": 20, "query_calendar_only": 0, "retired_paths": []}}

HEALTH = {"ok": True,
          "rounds": [{"ts": "2026-10-30 10:00",
                      "plats": {"app_zhixing": {"s": "ok", "ok": 2, "tot": 2,
                                                "cal": 0, "detail": 2}}}],
          "stats": {"app_zhixing": {"ok": 20, "part": 0, "fail": 0,
                                    "maint": 0, "rate": 1.0, "cal": 0,
                                    "detail": 20, "auth": 0}},
          "push": {"channels": {}}, "paths": PATHS, "diag": [],
          "coverage": {}}


def _render_row():
    from playwright.sync_api import sync_playwright

    import webui

    tmp = os.path.join(ROOT, "_scratch", "_r645c")
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as f:
        f.write(webui.PAGE.replace("__PAGEVER__", "r645c"))

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
                        {"ok": True, "demo": False, "platforms": PATHS})))
                pg.route("**/api/health", lambda r: r.fulfill(
                    status=200, body=json.dumps(HEALTH)))
                pg.route("**/api/pacing", lambda r: r.fulfill(
                    status=200, body=json.dumps(
                        {"ok": True, "quiet": {}, "last_round": {},
                         "channels": {}, "cfg": {}, "coverage": {},
                         "recurrences": [], "effect": {}, "iv_rate": {}})))
                pg.goto("http://127.0.0.1:%d/index.html" % port,
                        wait_until="domcontentloaded")
                pg.wait_for_function("typeof renderHealth==='function'")
                pg.evaluate(r"""async h => {
                  try{switchView('mon');}catch(e){}
                  try{showMonTab('health',true);}catch(e){}
                  document.querySelectorAll('#monview,#healthcard')
                    .forEach(e=>{e.hidden=false;e.style.display='';});
                  const pane=document.getElementById('montab-health');
                  if(pane){pane.hidden=false;pane.style.display='';}
                  await loadChannelState(true);
                  renderHealth(h);
                  await new Promise(r=>setTimeout(r,400));
                }""", HEALTH)
                return pg.evaluate(r"""()=>{
                  const row=[...document.querySelectorAll(
                    '#healthcard .hrow')]
                    .find(e=>/智行/.test(e.innerText||''));
                  return row?row.innerText.replace(/\s+/g,' '):'';
                }""")
            finally:
                b.close()
    finally:
        srv.shutdown()
        srv.server_close()


def test_unsupported_only_path_is_not_reported_as_zero_percent():
    row = _render_row()
    assert row, "健康卡没有渲染出智行 App 那一行"
    assert "android-runtime" in row, "通路小标里没有 android-runtime：%r" % row
    # 关键：不能出现「android-runtime ... 0%」
    # 小标形如「android-runtime 无有效样本（63 次 · 无效 63） · app-calendar …」，
    # 用下一个通路名做右界，避免被中间的 `·` 切断。
    seg = row.split("android-runtime")[1]
    for nxt in ("app-calendar", "app-list"):
        if nxt in seg:
            seg = seg.split(nxt)[0]
    assert "0%" not in seg, (
        "把「一次都没真正试过」渲染成了 0%%（会读作这条路全失败）：%r"
        % seg)
    assert "无有效样本" in seg, (
        "无效样本为 0 时应直说「无有效样本」：%r" % seg)
    assert "无效 63" in seg, "没有交代那 63 次是无效尝试：%r" % seg


def test_healthy_path_still_shows_its_rate():
    """正常通路不能被这次改动误伤：app-calendar 100% 仍要显示百分比。"""
    row = _render_row()
    assert "app-calendar" in row, "通路小标里没有 app-calendar：%r" % row
    seg = row.split("app-calendar")[1].split("·")[0]
    assert "100%" in seg, "正常通路没有显示 100%%：%r" % seg
    assert "无有效样本" not in seg, "正常通路被误标成无有效样本：%r" % seg
