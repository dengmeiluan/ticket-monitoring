# -*- coding: utf-8 -*-
"""r518：有历史轮次但采集已停时，健康卡必须标注「下面是停摆前的历史」。

r517 修的是**整卡空态**（`rounds` 为空）。但真实场景更常见的是：
采集停了 13 小时，24h 窗口里仍有停摆前的部分轮次 —— 此时卡片不空，
每行徽标显示的是**停摆前**的成功率（例如 96%），而同一屏的节流面板
已经写着「采集停了」。读者会把「96%」读成现状。

做法：卡头加一枚告警标记「⚠ 采集已停 N 小时 · 下方为停摆前的历史数据」，
**不改徽标数字**（那是真实的历史数据，既不伪造也不抹掉）。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_stale_banner_is_built_once_per_render():
    """每轮轮询都会重跑，旧标记必须先清掉——否则同屏叠出好几个。"""
    w = _w()
    i = w.index("采集已停 '+Math.floor(_m2/60)")
    seg = w[max(0, i - 900):i + 200]
    assert "querySelectorAll('#hroundcnt ~ .hstale').forEach(e=>e.remove())" in seg, \
        "没有清理上一轮插入的停摆标记（会越叠越多）"


def test_stale_banner_uses_tokens_not_new_colors():
    w = _w()
    i = w.index("#healthcard .hstale{")
    seg = w[i:i + 320]
    assert "var(--warn-deep)" in seg and "var(--r-amber-soft)" in seg, \
        "停摆标记没有走全站语义色令牌"
    assert "font-size:11px" in seg, "字号不在阶上"


def test_renders_banner_only_when_collection_stalled():
    """真渲染三种情形：停摆有标记；刚采集无标记；重复渲染不叠加。

    静态断言挡不住「条件写错」——必须真渲染读 DOM。
    """
    import json
    import threading
    import time
    from functools import partial
    from http.server import (SimpleHTTPRequestHandler, ThreadingHTTPServer)

    import pytest
    import webui

    def ts(h):
        return time.strftime("%Y-%m-%d %H:%M:%S",
                             time.localtime(time.time() - h * 3600))

    def health(last_seen):
        return {"rounds": [
            {"ts": "10-01 15:00",
             "plats": {"qunar": {"s": "ok", "ok": 3, "tot": 3}}},
            {"ts": "10-01 14:40",
             "plats": {"qunar": {"s": "ok", "ok": 3, "tot": 3}}}],
            "stats": {"qunar": {"ok": 2, "part": 0, "fail": 0, "rate": 1.0}},
            "last_seen_at": last_seen}

    tmp = os.path.join(ROOT, "_scratch", "_r518_t")
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as f:
        f.write(webui.PAGE.replace("__PAGEVER__", "r518t"))

    class H(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    _PORT = 0
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(H, directory=tmp))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as drv:
            if not os.path.exists(drv.chromium.executable_path):
                pytest.skip("Chromium 未安装")
            b = drv.chromium.launch()
            out = {}
            try:
                ctx = b.new_context(viewport={"width": 1280, "height": 900})
                page = ctx.new_page()
                page.set_default_timeout(9000)
                page.add_init_script("window.setInterval=()=>1;")
                page.goto(("http://127.0.0.1:%d/index.html" % srv.server_address[1]),
                          wait_until="domcontentloaded")
                page.wait_for_function(
                    "typeof renderHealth==='function'", timeout=12000)
                for name, ls in (("stalled", ts(13)), ("fresh", ts(0.1))):
                    out[name] = page.evaluate(
                        """(b)=>{renderHealth(b);
                           return [...document.querySelectorAll(
                             '#healthcard .hstale')]
                             .map(e=>e.textContent.replace(/\\s+/g,' '));}""",
                        health(ls))
                # 同一份停摆数据连渲染三次：不得叠加
                out["repeat"] = page.evaluate(
                    """(b)=>{renderHealth(b);renderHealth(b);renderHealth(b);
                       return document.querySelectorAll(
                         '#healthcard .hstale').length;}""",
                    health(ts(13)))
                ctx.close()
            finally:
                b.close()
    finally:
        srv.shutdown()
        srv.server_close()

    assert out["stalled"], "停摆 13 小时却没有卡头标记"
    assert "采集已停" in out["stalled"][0], out["stalled"]
    assert "13 小时" in out["stalled"][0], out["stalled"]
    assert "历史" in out["stalled"][0], \
        "没有说明下方是历史数据：%r" % (out["stalled"],)
    assert not out["fresh"], "刚采集过却挂了停摆标记：%r" % (out["fresh"],)
    assert out["repeat"] == 1, \
        "重复渲染叠加了 %d 个停摆标记" % out["repeat"]
