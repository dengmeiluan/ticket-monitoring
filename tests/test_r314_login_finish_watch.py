# -*- coding: utf-8 -*-
"""r314 登录完成页状态自动跟进（TDD 先行，用户实报缺陷复现钉）：

现象：弹窗登录完成点「✅ 我已登录完成」后，登录卡停在「登录中…」，
要手动点「🔄 刷新状态」才更新为「已保存，等待采集验证…」。

根因（Phase 1 定谳）：/api/login-finish 置 Event 即返回，会话保存是
登录线程的异步尾部（Playwright 持久化上下文关闭需数秒）——
login_sessions 的 active 翻落晚于前端 finish 后的立即刷新（读到的
仍是旧态、签名门挡住重绘），此后只剩 30s 轻轮询能追上翻落：用户
感知即「不自新，点刷新才有」（点刷新时保存早已落地）。

修法：finish 成功后起有界短周跟Watch（1.6s×10≈16s；签名门重绘=
状态真变才重建卡片，不打断用户点按；active 翻落即提前停）。

行为钉用 route 拦截 scripted 状态序列离线复现：finish 后 2.5s 才
放行翻落态（模拟会话保存耗时），断言 9s 内卡片自动跟进且零手动
刷新——旧实现唯一翻落追上点是 30s 轮询，钉必红。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r314_login_finish_watch.py
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PORT = None      # fixture 期取空闲端口（r251 同款动态口）
BASE = ""
_proc = None


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_up(timeout=20.0):
    # 本机探活显式空代理（LESSONS 廿四§9：默认 opener 吃环境代理假失败）
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    end = time.time() + timeout
    while time.time() < end:
        try:
            with opener.open(BASE + "/api/state", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


@pytest.fixture(scope="module")
def srv():
    global PORT, BASE, _proc
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    PORT = _free_port()
    BASE = "http://127.0.0.1:%d" % PORT
    _proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
         "--port", str(PORT)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert _wait_up(), "demo 启动失败"
    yield _proc
    _proc.terminate()
    try:
        _proc.wait(timeout=5)
    except Exception:
        _proc.kill()


@pytest.fixture(scope="module")
def pg(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1280, "height": 900})
        page.set_default_timeout(10000)
        page.goto(BASE, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        yield page
        b.close()


def _plats(qunar):
    d = {"saved": False, "active": False, "stale": False, "pending": False}
    d.update(qunar)
    return {"ok": True, "plats": {
        "qunar": d, "ctrip": dict(d), "tongcheng": dict(d),
        "tuniu": dict(d), "fliggy": dict(d)}}


# finish 前态：qunar 登录窗开着（active）→ 卡片渲染「我已登录完成」钮
PLATS_A = _plats({"saved": False, "active": True})
# 翻落态：会话已保存、验证窗内（stale+pending）→「已保存，等待采集验证…」
PLATS_B = _plats({"saved": True, "active": False, "stale": True, "pending": True})


def test_login_finish_watch_source_pin():
    """源码钉：有界短周跟Watch 在场 + finish 成功分支接线。"""
    import webui
    import pathlib
    src = pathlib.Path(webui.__file__).read_text(encoding="utf-8")
    assert "function lgFinishWatch(p,left)" in src, (
        "缺 finish 后短周跟Watch：会话保存是登录线程异步尾部，"
        "finish 返回时 active 尚未翻落，立即刷读旧态、30s 轮询太晚")
    i = src.index("function lgFinishWatch")
    seg = src[i:i + 420]
    assert "if(left<=0)return" in seg, "Watch 缺有界停点（登录线程悬挂时不得无限轮询）"
    assert "lgFinishWatch(p,10)" in src, "finish 成功分支未接线 Watch"
    # 接线必须在 j.ok 分支内（失败路径不轮询：「没有进行中的登录」错误态重拉无益）
    j = src.index("lgFinishWatch(p,10)")
    head = src[max(0, j - 300):j]
    assert "toast(j.ok?" in head, "Watch 接线未落在成功 toast 分支内"


def test_login_finish_status_follows(pg):
    """行为钉：finish 后服务端翻落（模拟保存耗时 2.5s）须在 9s 内自动
    呈现为「已保存，等待采集验证…」，零手动刷新。旧实现唯一
    追上点是 30s 轻轮询，本钉必红。附带零 pageerror 门：loadLogin 的
    return 值引用若逃出 try 块作用域（r314 P1-3 实锤），凡成功渲染
    路径必抛 ReferenceError——卡片内容断言抓不到它，零错窗钉补位。"""
    state = {"finish_t": None}
    js_errors = []
    pg.on("pageerror", lambda e: js_errors.append(str(e)))

    def on_state(route):
        if (state["finish_t"] is not None
                and time.time() - state["finish_t"] >= 2.5):
            route.fulfill(json=PLATS_B)
        else:
            route.fulfill(json=PLATS_A)

    def on_finish(route):
        state["finish_t"] = time.time()
        route.fulfill(json={"ok": True, "plat": "qunar"})

    pg.route("**/api/login-state", on_state)
    pg.route("**/api/login-finish", on_finish)
    try:
        pg.evaluate("switchView('cfg');showCfgPanel('login');")
        pg.wait_for_selector(".lgcard.active button")
        pg.click(".lgcard.active button")
        pg.wait_for_function(
            "document.querySelector('#loginRows').innerHTML"
            ".indexOf('已保存，等待采集验证')>=0",
            timeout=9000)
    finally:
        pg.evaluate("lgWatchStop()")   # 停 30s 轮询再关浏览器（teardown 在途 fetch 噪音）
        pg.unroute("**/api/login-state")
        pg.unroute("**/api/login-finish")
    assert not js_errors, "登录流程产生 pageerror（零 JS 错门禁）: %s" % js_errors[:3]
