# -*- coding: utf-8 -*-
"""r517：健康卡空态也必须分清「从未采集」和「采集停了」。

r516 把「停摆」接进了节流行（渠道健康时间线里的每行建议）。但健康卡
**整卡空态**（`rounds` 为空）仍写着：

    暂无扫描记录——完成一轮采集后，这里会出现 24h 渠道健康时间线

采集停 26 小时时，这句话让读者继续等；而同一屏的节流行此时可能已经写着
「采集停了」。同一页两句话互相矛盾，是「状态清晰」的直接缺口。

实测形态：`data/prices.db` 里最后一条 fetch_paths 在 10-28 14:33，
今天 `_health_state()["rounds"]` 为空 → 走空态分支。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_health_empty_state_mentions_stalled_collection():
    w = _w()
    i = w.index("function renderHealth(j)")
    seg = w[i:i + 1500]
    assert "last_seen_at" in seg, "健康卡空态没有使用最近采集时刻"
    assert "采集已停" in seg, "空态没有「采集停了」这一支"
    # 原来那句必须仍在（新装用户看到的是它，不能被替换掉）
    assert "完成一轮采集后" in seg, "「从未采集」的提示被删掉了"
    # 停摆分支要给出可执行方向，而不是只报一个时间
    assert "检查监控进程" in seg, "停摆空态没有给出下一步"


def test_health_payload_supplies_last_seen_at():
    w = _w()
    i = w.index('elif self.path == "/api/health":')
    seg = w[i:i + 3000]
    assert 'last_seen_at' in seg, "/api/health 没有下发最近采集时刻"
    assert "MAX(fetched_at)" in seg, "没有查全表最近样本"


def test_stalled_branch_needs_a_real_threshold():
    """阈值必须在场且是 6 小时（360 分钟）——与节流行同一口径。"""
    w = _w()
    i = w.index("function renderHealth(j)")
    seg = w[i:i + 1500]
    assert ">=360" in seg, "空态停摆没有 6 小时阈值（会与节流行口径不一致）"


def test_renders_stalled_text_for_an_old_last_sample():
    """真渲染：给 26 小时前的 last_seen_at，空态必须说「采集已停」。

    这条是必需的：上面几条只查源码字符串，把分支短路成 `false ? ...`
    之后文字仍在源码里、静态断言照样绿（负控实测如此）。只有渲染才抓得住。
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

    tmp = os.path.join(ROOT, "_scratch", "_r517_t")
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as f:
        f.write(webui.PAGE.replace("__PAGEVER__", "r517t"))

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
                for name, body in (
                        ("stalled", {"rounds": [], "last_seen_at": ts(26)}),
                        ("fresh", {"rounds": [], "last_seen_at": ts(0.2)}),
                        ("never", {"rounds": [], "last_seen_at": ""})):
                    out[name] = page.evaluate(
                        """(b)=>{renderHealth(b);
                           const e=document.getElementById('healthEmpty');
                           return (e.textContent||'').replace(/\\s+/g,' ');}""",
                        body)
                ctx.close()
            finally:
                b.close()
    finally:
        srv.shutdown()
        srv.server_close()

    assert "采集已停" in out["stalled"], \
        "26 小时前的样本没有渲染出「采集已停」：%r" % (out["stalled"],)
    assert "26 小时前" in out["stalled"], out["stalled"]
    assert "检查监控进程" in out["stalled"], \
        "停摆空态没有给出下一步：%r" % (out["stalled"],)
    # 另外两种情形必须仍是「暂无扫描记录」，不能被停摆文案污染
    for k in ("fresh", "never"):
        assert "采集已停" not in out[k], \
            "%s 被误判成采集停摆：%r" % (k, out[k])
        assert "完成一轮采集后" in out[k], out[k]
