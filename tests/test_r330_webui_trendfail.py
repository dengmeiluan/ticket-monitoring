# -*- coding: utf-8 -*-
"""C330-1（WebUI P2，audit_c330_webui.md）：长窗走势加载失败被缓存
为空数据。/api/trend 返回 200+ok:false（服务端 DB 异常/缺参的真实
在产形态）时，前端 `if(!j||!j.ok)j={direct:[],transfer:[]}` 把失败
改写成空数组写入 st.long 成功缓存——失败词面永不可达（「暂无走势
数据」误导词面把服务瞬时故障伪装成还没采集）、缓存命中让服务恢复后
切档/轮询均不重试，唯一出路整页刷新。catch 分支的「失败不写缓存」
意图只覆盖网络级失败。

修复：`!j.ok` 抛出交既有 catch 接管（seq/缓存缺席守卫语义恰好闭合）。

钉面三段：①失败不写缓存+失败词面在场；②解除拦截后切档重取自愈；
③正常成功路径缓存照写（修复不伤成功路）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r330_webui_trendfail.py -q
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

import pytest

pytest.importorskip("playwright",
                    reason="行为钉依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8798
BASE = "http://127.0.0.1:%d" % PORT


def _wait_up():
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(40):
        try:
            op.open(BASE + "/api/state", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


@pytest.fixture(scope="module")
def srv():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        import os as _os
        if not _os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    r = subprocess.run(["netstat", "-ano"], capture_output=True)
    for ln in r.stdout.decode("utf-8", errors="ignore").splitlines():
        if ("127.0.0.1:%d" % PORT) in ln and "LISTENING" in ln:
            subprocess.run(["taskkill", "/PID", ln.split()[-1], "/F"],
                           capture_output=True)
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
         "--port", str(PORT)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert _wait_up(), "demo 启动失败"
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


@pytest.fixture(scope="module")
def pg(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1280, "height": 900})
        page.set_default_timeout(10000)
        page.goto(BASE, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        yield page
        b.close()


def _long_keys(pg):
    return pg.evaluate("()=>{const u=Object.keys(CHR)[0];"
                       "return Object.keys(((CHR[u]||{}).long)||{});}")


def test_trend_fail_not_cached_fail_word_shown(pg):
    """ok:false 响应 → 缓存不写入、chartEmpty 覆写失败词面（修复前
    空数组入缓存 + 「暂无走势数据」误导词面）。"""
    pg.route("**/api/trend*", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"ok": False, "err": "c330 钉"})))
    try:
        pg.evaluate("switchView('mon');showMonTab('trend');setRange('90d');")
        pg.wait_for_timeout(1200)
        keys = _long_keys(pg)
        assert not any(k.endswith("|90") for k in keys), \
            "失败响应不得写入长窗缓存（自愈通道被缓存焊死）: %s" % keys
        word = pg.evaluate(
            "()=>{const ce=document.querySelector('#chartEmpty');"
            "return ce&&ce.style.display!=='none'?ce.innerHTML:'';}")
        assert "加载失败" in word, "失败词面须在场（非「暂无走势数据」误导）：%r" % word
    finally:
        pg.unroute("**/api/trend*")


def test_trend_recovers_after_service_back(pg):
    """解除拦截后切档再切回 → 缓存缺席守卫放行重取，真实数据落缓存
    （修复前 cache-hit 早退永久空）。"""
    pg.evaluate("switchView('mon');showMonTab('trend');setRange('90d');")
    pg.wait_for_timeout(1800)
    keys = _long_keys(pg)
    assert any(k.endswith("|90") for k in keys), \
        "服务恢复后重取应落真实缓存: %s" % keys
    n = pg.evaluate("()=>{const u=Object.keys(CHR)[0];"
                    "const c=((CHR[u]||{}).long||{});"
                    "const k=Object.keys(c).find(k=>k.endsWith('|90'));"
                    "return c[k]?c[k].direct.length:-1;}")
    assert n > 0, "恢复后的缓存应是真实数据非空数组：%r" % n
