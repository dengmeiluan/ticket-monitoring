# -*- coding: utf-8 -*-
r"""r814b：画中画的会话断了要在界面上说，不能装作还连着。

现场：`appLoginLoop` 把帧请求的错误全吞了（`.catch(()=>{})`），404/409
（服务重启、切了渠道、会话过期）之后仍在每 700ms 轮询，画面停在最后一帧，
状态行还写着「画面已连接 · 点画面即可操作」。用户继续点，点不进去也不知道
是网络、程序还是自己点错。

判据（真渲染）：
  * 帧接口 404 时 → 状态行/等待层写「登录会话已结束」；
  * 出现可点的「重新连接」按钮；
  * 点它真的会重新 POST /api/app-login。
负控：旧代码把 404 吞掉后文案仍是「画面已连接」，本用例红。
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


def test_frame_404_is_visible_and_retry_reopens_session():
    from playwright.sync_api import sync_playwright
    srv, base = _boot()
    posts = []
    try:
        with sync_playwright() as pw:
            if not os.path.exists(pw.chromium.executable_path):
                pytest.skip("chromium 二进制缺失")
            b = pw.chromium.launch()
            try:
                pg = b.new_page(viewport={"width": 1440, "height": 1000})
                errs = []
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.add_init_script("window.setInterval=()=>1;")

                def fake(route, request):
                    u = request.url
                    if "/frame" in u:
                        route.fulfill(status=404,
                                      content_type="text/plain", body="")
                        return
                    if request.method == "POST":
                        posts.append(u)
                        route.fulfill(
                            status=200, content_type="application/json",
                            body=json.dumps({"ok": True,
                                             "session": {"status": "pending"}}))
                        return
                    route.continue_()

                pg.route("**/api/app-login**", fake)
                pg.goto(base)
                pg.wait_for_function(
                    "typeof S!=='undefined'&&S&&S.users", timeout=30000)
                pg.evaluate("()=>appLoginOpen('app_zhixing')")
                pg.wait_for_function(
                    "()=>{const w=document.getElementById('appWait');"
                    "return w&&/登录会话已结束/.test(w.textContent||'')}",
                    timeout=10000)
                got = pg.evaluate(r"""()=>{
                  const w=document.getElementById('appWait');
                  const t=document.getElementById('appTip');
                  const r=document.getElementById('appRetryBtn');
                  const img=document.getElementById('appImg');
                  return {wait:w?w.textContent.trim():'',
                          tip:t?t.textContent.trim():'',
                          retryShow:!!r&&getComputedStyle(r).display!=='none',
                          retryText:r?r.textContent.trim():'',
                          imgShown:!!img&&getComputedStyle(img).display!=='none'};}""")
                assert not errs, "页面抛错：%s" % errs[:3]
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()

    assert "登录会话已结束" in got["wait"], (
        "帧接口 404 后画面层没说会话已结束：%r" % got)
    assert "登录会话已结束" in got["tip"], (
        "状态行还在装作画面已连接：%r" % got)
    assert got["retryShow"] and "重新连接" in got["retryText"], (
        "没有给用户重新连接的入口：%r" % got)
    assert not got["imgShown"], "会话断了还留着上一帧当“实时画面”"
    assert len(posts) >= 1, "根本没发起过登录会话"


def test_narrow_pip_bar_keeps_labels_horizontal():
    """390 档：底栏按钮不能被压成竖排单字（截图实测「重新连接」四行）。

    判据用 Range 的行盒数量：一个按钮的文字占多个行盒 = 换行了；
    同时弹窗不得出现横向溢出，按钮不得跑出弹窗右缘。
    """
    from playwright.sync_api import sync_playwright
    srv, base = _boot()
    try:
        with sync_playwright() as pw:
            if not os.path.exists(pw.chromium.executable_path):
                pytest.skip("chromium 二进制缺失")
            b = pw.chromium.launch()
            try:
                pg = b.new_page(viewport={"width": 390, "height": 800})
                errs = []
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.add_init_script("window.setInterval=()=>1;")
                pg.goto(base)
                pg.wait_for_function(
                    "typeof S!=='undefined'&&S&&S.users", timeout=30000)
                pg.evaluate("()=>appLoginOpen('app_zhixing')")
                pg.wait_for_timeout(300)
                pg.evaluate(
                    "()=>appLoginFail('登录会话已结束 · 点「重新连接」重新打开画面')")
                pg.wait_for_timeout(200)
                got = pg.evaluate(r"""()=>{
                  const m=document.getElementById('lgModal');
                  const bar=document.querySelector('.appscr-bar');
                  const mr=m.getBoundingClientRect();
                  const out=[];
                  for(const b of bar.querySelectorAll('button')){
                    if(getComputedStyle(b).display==='none')continue;
                    const r=b.getBoundingClientRect();
                    const rng=document.createRange();
                    rng.selectNodeContents(b);
                    out.push({t:b.textContent.trim(),
                      lines:[...rng.getClientRects()].filter(x=>x.width>0).length,
                      right:Math.round(r.right),h:Math.round(r.height)});
                  }
                  return {modalLeft:Math.round(mr.left),
                          modalRight:Math.round(mr.right),
                          hOver:m.scrollWidth>m.clientWidth+1,
                          btns:out};}""")
                assert not errs, "页面抛错：%s" % errs[:3]
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()

    assert not got["hOver"], "390 档画中画弹窗横向溢出"
    assert got["btns"], "底栏没有按钮"
    for b in got["btns"]:
        assert b["lines"] == 1, (
            "按钮「%s」被压成竖排（%d 行文字）：%r" % (b["t"], b["lines"], b))
        assert b["right"] <= got["modalRight"] + 1, (
            "按钮「%s」跑出弹窗右缘：%r" % (b["t"], b))
