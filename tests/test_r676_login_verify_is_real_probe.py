# -*- coding: utf-8 -*-
r"""r676：登录卡的「核验」必须是真查询，并且结论要写进登录态。

用户实报（issue #10 评论）：「携程弹窗能登录，但是核验没效果，实际不能用」。
实测缺口：
- 只有飞猪 H5 槽位有核验按钮；携程/去哪儿/同程/途牛保存会话后**没有
  任何可点的核验动作**，只能等下轮采集；
- `/api/channel/probe`（真查询自检）出数只写路径账/干预账，登录卡读的
  `_PROBE_AUTH` 不更新——就算点了，卡片状态也不变，读作「核验没效果」。

判据：
① 真渲染：ctrip 已保存态给出「立即核验」按钮，且点击真的 POST
   /api/channel/probe（不是只弹提示）；未保存态不给核验（先登录）；
   飞猪 H5 仍走页面核验（不改变既有语义）。
② 真服务：探测出数 → 写 detail 证据；0 条且有 login/blocked 通路 →
   写拒绝证据；0 条且无拦截证据 → **什么都不写**（空结果不反推失效）。

负控：把 loginProbe 的 fetch 换空实现 → ①红；删掉证据写入块 → ②红。
"""
import json
import os
import shutil
import socket
import sys
import tempfile
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


# ---------------- ② 真服务：证据写入 ----------------

def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def live():
    import webui
    port = _free_port()
    tmp = tempfile.mkdtemp(prefix="r676_")
    cfg_path = os.path.join(tmp, "c.yaml")
    shutil.copyfile(os.path.join(ROOT, "config.example.yaml"), cfg_path)
    webui.start_web(cfg={"web": {"port": port, "host": "127.0.0.1"}},
                    job=None, report_push=None, config_path=cfg_path)
    base = "http://127.0.0.1:%d" % port
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(120):
        try:
            op.open(base + "/api/state", timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    yield base, op, webui
    webui._State.probe_cb = None


def _probe(base, op, plat="ctrip"):
    req = urllib.request.Request(
        base + "/api/channel/probe", method="POST",
        data=json.dumps({"platform": plat}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with op.open(req, timeout=8) as r:
        return json.loads(r.read().decode("utf-8"))


def _install_fake(webui, out):
    webui._State.probe_cb = lambda plat, **kw: dict(out, platform=plat)


def _auth(webui, plat, key):
    return dict((webui._PROBE_AUTH.get(plat) or {}).get("dom") or {}).get(key)


def test_probe_with_rows_writes_detail_evidence(live):
    base, op, webui = live
    webui._PROBE_AUTH.pop("ctrip", None)
    _install_fake(webui, {
        "ok": True, "rows": 7, "query": ["SHA", "NRT", "2026-11-20"],
        "scope": "dom",
        "paths": [{"path": "H5", "status": "ok", "rows": 7}]})
    j = _probe(base, op)
    assert j.get("ok") and j.get("rows") == 7
    assert _auth(webui, "ctrip", "detail_count") == 7, \
        "自检出数没有写进登录态证据（登录卡不会变）"
    assert _auth(webui, "ctrip", "from") == "SHA"


def test_probe_login_wall_writes_reject_evidence(live):
    base, op, webui = live
    webui._PROBE_AUTH.pop("ctrip", None)
    _install_fake(webui, {
        "ok": True, "rows": 0, "query": ["SHA", "URC", "2026-11-21"],
        "scope": "dom",
        "paths": [{"path": "H5", "status": "login", "rows": 0},
                  {"path": "PC", "status": "empty", "rows": 0}]})
    _probe(base, op)
    assert _auth(webui, "ctrip", "auth_reason") == "登录墙", \
        "被登录墙拦却不落拒绝证据，卡片会停在「已保存」"
    assert _auth(webui, "ctrip", "auth_path") == "H5"


def test_probe_empty_without_wall_writes_nothing(live):
    base, op, webui = live
    webui._PROBE_AUTH.pop("ctrip", None)
    _install_fake(webui, {
        "ok": True, "rows": 0, "query": ["SHA", "URC", "2026-11-22"],
        "scope": "dom",
        "paths": [{"path": "H5", "status": "empty", "rows": 0}]})
    _probe(base, op)
    assert not (webui._PROBE_AUTH.get("ctrip") or {}).get("dom"), \
        "0 条且无拦截证据时不得下任何登录结论（无票≠会话失效）"


# ---------------- ① 真渲染：按钮与请求 ----------------

@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    from pathlib import Path
    with sync_playwright() as driver:
        if not Path(driver.chromium.executable_path).exists():
            pytest.skip("Chromium 二进制未安装")
        b = driver.chromium.launch(args=["--no-sandbox"])
        yield b
        b.close()


@pytest.fixture
def page(browser):
    import webui
    from urllib.parse import urlsplit
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    pg.set_default_timeout(4000)
    pg.add_init_script("window.setInterval = () => 1;")
    calls = []
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))

    def route(request):
        path = urlsplit(request.request.url).path
        if path == "/":
            request.fulfill(content_type="text/html; charset=utf-8",
                            body=webui._page_html("ui-test"))
        elif path == "/api/channel/probe":
            calls.append(json.loads(request.request.post_data or "{}"))
            request.fulfill(json={"ok": True, "rows": 3,
                                  "query": ["SHA", "NRT", "2026-11-20"],
                                  "scope": "dom",
                                  "paths": [{"path": "H5", "status": "ok",
                                             "rows": 3}]})
        elif path == "/api/login-state":
            request.fulfill(json={"ok": True, "plats": {}, "slots": {}})
        else:
            request.fulfill(json={"ok": True, "items": [], "rows": [],
                                  "users": [], "demo": False,
                                  "version": "ui-test"})

    pg.route("**/*", route)
    pg.goto("http://login-probe.test/", wait_until="networkidle")
    yield pg, calls
    ctx.close()
    assert not errors, "页面 JavaScript 错误：%s" % errors


def test_saved_slot_offers_real_probe(page):
    pg, _calls = page
    html = pg.evaluate(
        "() => lgActionHTML({slot:'ctrip',plat:'ctrip',status:'saved',"
        "saved:true,active:false,saving:false})")
    assert "立即核验" in html, "已保存的携程卡没有可点的核验动作"
    assert "loginProbe('ctrip'" in html, "核验按钮没有接到 loginProbe"


def test_missing_slot_offers_login_not_probe(page):
    pg, _calls = page
    html = pg.evaluate(
        "() => lgActionHTML({slot:'ctrip',plat:'ctrip',status:'missing',"
        "saved:false,active:false,saving:false})")
    assert "loginProbe" not in html, "还没保存会话就给核验，等于诱导空点"
    assert "loginStart('ctrip'" in html, "缺会话时应给登录入口"


def test_h5_keeps_page_verify(page):
    pg, _calls = page
    html = pg.evaluate(
        "() => lgActionHTML({slot:'fliggy_h5',plat:'fliggy',status:'saved',"
        "saved:true,active:false,saving:false})")
    assert "loginVerify('fliggy_h5'" in html, "飞猪 H5 的页面核验被无意改掉"
    assert "loginProbe" not in html


def test_clicking_verify_sends_a_real_probe(page):
    pg, calls = page
    pg.evaluate("""() => {
      const box = document.createElement('div');
      box.id = 'probe-box';
      box.innerHTML = lgActionHTML({slot:'ctrip',plat:'ctrip',status:'saved',
        saved:true,active:false,saving:false});
      document.body.appendChild(box);
    }""")
    pg.click("#probe-box button")
    pg.wait_for_timeout(700)
    assert calls and calls[0].get("platform") == "ctrip", (
        "点「核验」没有发起真查询，只弹了提示：%r" % (calls,))
