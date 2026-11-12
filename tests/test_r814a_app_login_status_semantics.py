# -*- coding: utf-8 -*-
r"""r814a：App 登录会话的状态要说自己的话，不能借用浏览器槽位的文案。

现场（2026-11-02 04:39，8765 真渲染）：去哪儿 App 正在内嵌画面里等登录，
登录卡却写「已保存 · 下轮采集验证中」——那个 `pending` 是**登录会话在等
用户操作**，不是浏览器槽位的「会话已保存、等下一轮采集验证」。两套状态机
恰好都叫 pending，卡片直接套了浏览器文案，于是把「没保存」说成「已保存」。

另一处：`view()` 没下发 active，卡片在会话进行中仍显示「登录」而不是
「继续登录」；会话过期后状态是原样的英文 `expired`。

判据：
  1. 会话 view 下发 active；过期后 active=False、status=expired；
  2. 真浏览器里 pending 卡片写「登录画面进行中」且按钮「继续登录」，
     过期卡片写「登录会话已超时」且按钮「重新登录」；
  3. 两张 App 卡都不得出现英文状态或「已保存」（pending 时没保存）。
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class _Dev:
    def screencap(self):
        return b"\x89PNG-x"

    def window_size(self):
        return (900, 1600)

    def tap(self, x, y):
        return True

    def input_text(self, text):
        return True

    def keyevent(self, key):
        return True


class _Rt:
    def device(self):
        return _Dev()


def _session(timeout_s=900):
    from core.android.login_session import AppLoginSession
    return AppLoginSession("app_zhixing", _Rt(), "cn.suanya.zhixing",
                           timeout_s=timeout_s)


def test_session_view_reports_active():
    v = _session().view()
    assert v["status"] == "pending"
    assert v["active"] is True, "进行中的会话没下发 active，卡片不会说「继续登录」"


def test_finished_session_is_not_active():
    s = _session()
    s.finish(True, "ok")
    v = s.view()
    assert v["active"] is False
    assert v["status"] == "done"


def test_expired_session_view_is_not_active():
    from core.android.login_session import AppLoginRegistry
    s = _session(timeout_s=1)
    s.created_at -= 5
    reg = AppLoginRegistry()
    reg.put(s)
    got = reg.get("app_zhixing")
    v = got.view()
    assert v["status"] == "expired"
    assert v["active"] is False


def test_state_endpoint_reports_expired_status():
    from core.android import login_api
    from core.android.login_session import AppLoginRegistry
    s = _session(timeout_s=1)
    s.created_at -= 5
    reg = AppLoginRegistry()
    reg.put(s)
    obj, code = login_api.handle_state(
        reg, "app_zhixing",
        snapshot_info=lambda p: {"exists": True, "mtime": 123.0},
        needs_login=lambda p: True)
    assert code == 200
    assert obj["session"]["status"] == "expired"
    assert obj["session"]["active"] is False
    assert obj["session"]["saved"] is True


def _boot():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    srv = subprocess.Popen(
        [sys.executable, "webui.py", "--demo", "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, env=env)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = "http://127.0.0.1:%d" % port
    for _ in range(160):
        try:
            op.open(base + "/api/state", timeout=1)
            return srv, base
        except Exception:
            time.sleep(0.25)
    srv.terminate()
    pytest.skip("演示服务未在期限内起来")


def test_rendered_app_cards_speak_their_own_states():
    from playwright.sync_api import sync_playwright
    srv, base = _boot()
    try:
        with sync_playwright() as pw:
            if not os.path.exists(pw.chromium.executable_path):
                pytest.skip("chromium 二进制缺失")
            b = pw.chromium.launch()
            try:
                pg = b.new_page(viewport={"width": 1440, "height": 1200})
                errs = []
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.add_init_script("window.setInterval=()=>1;")

                def fake_state(route):
                    url = route.request.url
                    if "app_zhixing" in url:
                        body = {
                            "ok": True,
                            "session": {"plat": "app_zhixing",
                                        "status": "pending", "detail": "",
                                        "active": True, "saved": False},
                            "needs_login": False, "saved": False,
                            "saved_at": 0}
                    else:
                        body = {
                            "ok": True,
                            "session": {"plat": "app_qunar",
                                        "status": "expired",
                                        "detail": "登录超时，请重新发起",
                                        "active": False, "saved": False},
                            "needs_login": True, "saved": True,
                            "saved_at": 1793434103.0}
                    route.fulfill(status=200,
                                  content_type="application/json",
                                  body=json.dumps(body))

                pg.route("**/api/app-login/state**", fake_state)
                pg.goto(base)
                pg.wait_for_function(
                    "typeof S!=='undefined'&&S&&S.users", timeout=30000)
                pg.evaluate("()=>switchView('cfg')")
                pg.wait_for_timeout(800)
                pg.evaluate("()=>loadLogin(null,true)")
                pg.wait_for_function(
                    "()=>{const b=[...document.querySelectorAll("
                    "'#loginRows .lgcard')].find(e=>e.dataset.channel"
                    "==='app_zhixing');return b&&/登录画面进行中/.test("
                    "b.innerText)}", timeout=15000)
                cards = pg.evaluate(r"""()=>{
                  const m={};
                  document.querySelectorAll('#loginRows .lgcard').forEach(c=>{
                    m[c.dataset.channel]={
                      text:(c.innerText||'').replace(/\s+/g,' '),
                      btn:((c.querySelector('.lgact button')||{}).innerText
                           ||'').trim()};});
                  return m;}""")
                assert not errs, "页面抛错：%s" % errs[:3]
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()

    zx = cards.get("app_zhixing") or {}
    qn = cards.get("app_qunar") or {}
    assert "登录画面进行中" in zx.get("text", ""), (
        "进行中的 App 登录会话被写成了别的状态：%r" % zx)
    assert "已保存" not in zx.get("text", ""), (
        "会话还没保存，卡片却说已保存：%r" % zx)
    assert zx.get("btn") == "继续登录", (
        "进行中的会话按钮应是「继续登录」：%r" % zx.get("btn"))
    assert "登录会话已超时" in qn.get("text", ""), (
        "过期会话没有中文状态：%r" % qn)
    assert "expired" not in qn.get("text", ""), (
        "卡片把英文状态直接渲染上屏：%r" % qn)
    assert qn.get("btn") == "重新登录", (
        "过期会话按钮应是「重新登录」：%r" % qn.get("btn"))
