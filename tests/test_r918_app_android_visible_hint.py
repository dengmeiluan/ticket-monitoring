# -*- coding: utf-8 -*-
"""r918：勾了 App 渠道但 Android 总开关未开，必须有可见提示。

App 渠道依赖 `android.enabled` + 本机 MuMu；只在 chip 的 title 里写说明，
用户不悬停就看不到，勾选后不出数会被读成「程序坏了」。本门禁在真实浏览器
里构造两种状态：
  1. platforms 含 app_ctrip + android.enabled=false → 可见提示必须在场；
  2. 打开 android.enabled → 提示必须消失（不能常驻制造噪音）。
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


def test_app_channel_android_hint_is_visible_and_conditional():
    from playwright.sync_api import sync_playwright

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    srv = subprocess.Popen(
        [sys.executable, "webui.py", "--demo", "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, env=env)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = "http://127.0.0.1:%d" % port
    try:
        for _ in range(160):
            try:
                op.open(base + "/api/state", timeout=1)
                break
            except Exception:
                time.sleep(0.25)
        else:
            pytest.skip("演示服务未在期限内起来")
        with sync_playwright() as pw:
            if not os.path.exists(pw.chromium.executable_path):
                pytest.skip("chromium 二进制缺失")
            b = pw.chromium.launch()
            try:
                pg = b.new_page(viewport={"width": 1440, "height": 1200})
                pg.set_default_timeout(20000)
                pg.goto(base, wait_until="domcontentloaded")
                pg.wait_for_function(
                    "()=>typeof S!=='undefined'&&S&&S.users", timeout=30000)
                pg.evaluate("switchView('cfg');showCfgPanel('users')")
                pg.wait_for_timeout(600)

                def state(app_platform, android_on):
                    return pg.evaluate("""([app, on]) => {
                      CFG[0].platforms = app ? ['app_ctrip'] : ['ctrip'];
                      GLB.android = Object.assign({}, GLB.android || {},
                                                 {enabled: !!on});
                      buildForm();
                      const el = [...document.querySelectorAll('.shint')]
                        .find(e => (e.textContent || '').includes(
                          '已勾选 App 渠道'));
                      if (!el) return {found: false};
                      const r = el.getBoundingClientRect();
                      return {found: true, w: Math.round(r.width),
                              h: Math.round(r.height),
                              text: el.textContent.trim(),
                              color: getComputedStyle(el).color};
                    }""", [app_platform, android_on])

                off = state(True, False)
                on = state(True, True)
                plain = state(False, False)
                pg.screenshot(path=os.path.join(
                    ROOT, "_scratch", "_r918_app_hint.png"))
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()

    assert off["found"], "勾了 App 渠道且 Android 未开，界面没有可见提示"
    assert off["w"] > 0 and off["h"] > 0, off
    assert "不会采集" in off["text"] and "全局参数" in off["text"], off
    assert not on["found"], "Android 已开启，提示必须消失：%r" % (on,)
    assert not plain["found"], "没勾 App 渠道时不应出现该提示：%r" % (plain,)
