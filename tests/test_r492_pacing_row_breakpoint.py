# -*- coding: utf-8 -*-
"""r492：节流面板的宽度连续性——断点不该在「明明放得下」时就塌成两行。

实测（旧断点 900）：视口 901 → 行高 44px，900 → 81px。而 900 时面板
boxW 还有 834px，四列（名称 64 / 状态 112 / 证据 minmax / 动作 ~88）
完全放得下。等于 760–900 这一整段每行白白多占一倍高度，一屏少看两条渠道。

现在断点收到 760：800–900 保持四列 44px，760 以下才两行。
两侧都必须无横向溢出——收紧断点的风险是把证据列压到不可读，
所以溢出检查是这条契约的另一半。
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
    for p, qa in (("ctrip", 19), ("qunar", 6), ("fliggy", 32),
                  ("tongcheng", 15), ("tuniu", 4)):
        paths[p] = {
            "paths": {"PC": {"attempts": 8, "ok": 7, "rate": 0.875},
                      "H5": {"attempts": 12, "ok": 5, "rate": 0.417}},
            "retired_paths": [],
            "scopes": {"dom": {"query_rate": 0.95, "query_attempts": qa // 2},
                       "intl": {"query_rate": 0.5, "query_attempts": qa // 2}},
            "query_attempts": qa, "query_ok": qa // 2,
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
              "recurrences": [], "effect": {}, "iv_rate": {}}
    return paths, pacing


def test_row_layout_is_continuous_across_the_breakpoint():
    from playwright.sync_api import sync_playwright
    import webui

    tmp = os.path.join(ROOT, "_scratch", "_r492_t")
    os.makedirs(tmp, exist_ok=True)
    # 必须走生产的页面渲染路径：PAGE 里还有 __PATH_CN__ 这类服务端注入的
    # 占位符。只换 __PAGEVER__ 时 `const PATH_CN=__PATH_CN__;` 会在顶层抛
    # ReferenceError，整个 <script> 从这里停住，后面的常量（SRX_BRAND_IMG
    # 等）全都没初始化——实测表现为「Cannot access 'SRX_BRAND_IMG' before
    # initialization」，看着像产品缺陷，实际是夹具没按生产口径渲染。
    with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as f:
        f.write(webui._page_html("r492t"))

    class H(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 8934), partial(H, directory=tmp))
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
                for vw in (900, 800, 761, 760, 600, 420):
                    ctx = b.new_context(viewport={"width": vw, "height": 1000})
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
                    page.goto("http://127.0.0.1:8934/index.html",
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
                        const r=box.querySelector('.pace-row');
                        return {
                          h: r?Math.round(r.getBoundingClientRect().height):0,
                          ovf: box.scrollWidth>box.clientWidth+1,
                          docOvf: document.documentElement.scrollWidth>
                                  document.documentElement.clientWidth+1,
                        };
                    }""")
                    ctx.close()
            finally:
                b.close()
    finally:
        srv.shutdown()

    # 1) 右侧（≥761）必须是单行四列；旧断点 900 会在这里给出 ~81px
    for vw in (900, 800, 761):
        assert out[vw]["h"] <= 50, \
            "视口 %d 行被折成两行（高 %dpx）：断点过早，白白多占高度" % (
                vw, out[vw]["h"])
    # 2) 左侧（≤760）必须换成两行，否则证据列会被压死
    for vw in (760, 600):
        assert out[vw]["h"] > 50, \
            "视口 %d 仍是单行（高 %dpx）：证据列会被挤到不可读" % (
                vw, out[vw]["h"])
    # 3) 两侧都不得出现横向溢出（收紧断点的主要风险）
    for vw, o in out.items():
        assert not o["ovf"], "视口 %d 面板横向溢出" % vw
        assert not o["docOvf"], "视口 %d 页面横向溢出" % vw


def test_breakpoint_value_is_pinned_statically():
    """静态钉住：节流行两行布局必须挂在 760 而非 900 的块里。

    上面那条渲染契约的负控在本机做不成——并行会话会在我改完源文件的
    几秒内把它写回去，导致「变异后仍绿」无法判定是谁造成的。这条不渲染，
    直接在源码上定位「包含 .pace-row 的那个 media 块」，负控可稳定执行。
    """
    import io
    import re
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                newline="").read()
    # 找出所有 media 块，定位包含 ".pace-row{padding:8px 0" 的那个
    found = None
    for m in re.finditer(r"@media\(max-width:(\d+)px\)\{", w):
        start = m.end()
        depth, k = 1, start
        while depth and k < len(w):
            if w[k] == "{":
                depth += 1
            elif w[k] == "}":
                depth -= 1
            k += 1
        body = w[start:k]
        if ".pace-row{padding:8px 0" in body:
            found = int(m.group(1))
            break
    assert found is not None, "找不到节流行两行布局所在的 media 块"
    assert found == 760, (
        "节流行断点是 %dpx；实测 800–900 区间四列完全放得下（视口 900 时"
        "面板仍有 834px），断点过早会让整段每行多占一倍高度" % found)
    # 顺带确认 900 块里没有把行再次压成两行（否则收紧断点没意义）
    for m in re.finditer(r"@media\(max-width:900px\)\{", w):
        start = m.end()
        depth, k = 1, start
        while depth and k < len(w):
            if w[k] == "{":
                depth += 1
            elif w[k] == "}":
                depth -= 1
            k += 1
        assert "grid-template-areas:\"nm st ac\" \"ev ev ev\"" not in w[start:k], \
            "900px 块仍在把节流行压成两行"
