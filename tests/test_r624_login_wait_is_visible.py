# -*- coding: utf-8 -*-
"""r624：弹窗登录的等待期必须有可见进度（r620 之后接口最长等 45 秒）。

r620 把 /api/login 从「起线程即返回」改成「等窗口真的开成才返回」，代价是
点击后最长 45 秒（含排队等 channel_slot）。旧实现瞬时返回，按钮 busy 一闪
而过；现在这段等待里界面**毫无变化**，用户读作卡死并反复点击——而 busy
守卫只能事后忽略第二次，看不见变化仍会重复点。

判据（渲染级）：点「弹窗登录」后、请求未返回期间，按钮文案必须是
「正在打开窗口…」且带 aria-busy。负控：去掉文案切换即红。

注意：中间态只能改**当前按钮节点**。实测按"重建卡片"的方式做会在 200ms 内
被下一次 renderLoginCards/loadLogin 换掉（新节点丢了中间态），反而更糟。
"""
import io
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_login_start_shows_in_progress_copy():
    """静态旁证：文案与 aria-busy 的存在（渲染判据在主测试）。"""
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                newline="").read()
    i = w.index("async function loginStart(")
    seg = w[i:i + 1400]
    assert "正在打开窗口…" in seg, "loginStart 没有换成进行中文案"
    assert "aria-busy" in seg, "进行中态没给读屏播报"
    assert "b.disabled=true" in seg, "进行中应禁用按钮，避免重复触发"


def test_waiting_state_is_visible_during_real_pending_request():
    """真渲染：请求挂起期间按钮必须一直是「正在打开窗口…」。"""
    import pytest
    s = socket.socket(); s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]; s.close()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    srv = subprocess.Popen(
        [sys.executable, "webui.py", "--demo", "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, env=env)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = "http://127.0.0.1:%d" % port
    try:
        for _ in range(120):
            try:
                op.open(base + "/api/state", timeout=1); break
            except Exception:
                time.sleep(0.25)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            if not os.path.exists(pw.chromium.executable_path):
                pytest.skip("chromium 二进制缺失")
            b = pw.chromium.launch()
            pg = b.new_page(viewport={"width": 1440, "height": 1000})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            # 挂起 /api/login：模拟 r620 的等待窗口
            pg.route("**/api/login", lambda r: None)
            pg.goto(base)
            pg.wait_for_function("typeof S!=='undefined'&&S&&S.users",
                                 timeout=25000)
            pg.evaluate("()=>{switchView('cfg')}")
            pg.wait_for_timeout(800)
            pg.evaluate("""()=>{const c=document.querySelector(
              '#cfgnav .cnav[data-p="login"]');if(c)c.click()}""")
            pg.wait_for_timeout(1200)
            clicked = pg.evaluate("""()=>{
              const btn=[...document.querySelectorAll('#loginRows button')]
                .find(b=>/弹窗登录/.test(b.textContent));
              if(!btn)return null;
              btn.click();return btn.textContent.trim();}""")
            samples = []
            for _ in range(5):
                pg.wait_for_timeout(300)
                samples.append(pg.evaluate("""()=>{
                  const b=[...document.querySelectorAll('#loginRows button')]
                    .find(x=>/正在打开|弹窗登录/.test(x.textContent));
                  return b?{t:b.textContent.trim(),
                            a:b.getAttribute('aria-busy')}:null;}"""))
            b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()

    assert clicked is not None, "登录卡上没有「弹窗登录」按钮"
    assert not errs, "页面抛错：%s" % errs[:3]
    assert samples and all(
        s and "正在打开窗口…" in s["t"] for s in samples), (
        "等待期间按钮没有保持「正在打开窗口…」（用户在等一个看不见的过程）：%s"
        % json.dumps(samples, ensure_ascii=False))
    assert all(s and s["a"] == "true" for s in samples), (
        "等待期间缺少 aria-busy：%s" % json.dumps(samples, ensure_ascii=False))
