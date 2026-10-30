# -*- coding: utf-8 -*-
r"""r652：演示载荷的渠道清单要覆盖真实渠道，不能写死 5 家。

`_demo_pacing_payload()` 原先写死
`for p in ("qunar","fliggy","ctrip","tongcheng","tuniu")`，于是：
- 演示站（官方预览面）的节流面板只有 5 行，智行 App 整家不出现；
- 而 App 已能采集、有登录入口、有状态行——访客看到的「全貌」是缺的。

r628 修过同类问题（演示 /api/config 缺节流键 → 开关恒显示开），这里漏的
是**渠道本身**。

判据：演示载荷的 channels 键集必须等于真实渠道表；并且真渲染出对应行数。
负控：把清单改回写死的 5 家 → 两条各自红。
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _registry():
    from crawlers import REGISTRY
    return set(REGISTRY.keys())


def test_demo_payload_lists_every_real_channel():
    import webui

    got = set(webui._demo_pacing_payload()["channels"].keys())
    want = _registry()
    missing = sorted(want - got)
    assert not missing, (
        "演示节流载荷缺这些真实渠道（访客看到的全貌是残的）：%s" % missing)


def test_demo_payload_channels_are_rendered():
    """真渲染：演示站节流面板的行数要等于渠道数。"""
    import socket
    import subprocess
    import time
    import urllib.request

    from playwright.sync_api import sync_playwright

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
    try:
        up = False
        for _ in range(160):
            try:
                op.open(base + "/api/state", timeout=1)
                up = True
                break
            except Exception:
                time.sleep(0.25)
        if not up:
            pytest.skip("演示服务未在期限内起来")
        with sync_playwright() as pw:
            if not os.path.exists(pw.chromium.executable_path):
                pytest.skip("chromium 二进制缺失")
            b = pw.chromium.launch()
            try:
                pg = b.new_page(viewport={"width": 1440, "height": 1200})
                pg.set_default_timeout(20000)
                pg.add_init_script("window.setInterval=()=>1;")
                pg.goto(base)
                pg.wait_for_function(
                    "typeof S!=='undefined'&&S&&S.users", timeout=30000)
                pg.evaluate("""async () => {
                  try{switchView('mon');}catch(e){}
                  try{showMonTab('health',true);}catch(e){}
                  document.querySelectorAll('#monview,#healthcard')
                    .forEach(e=>{e.hidden=false;e.style.display='';});
                  const pane=document.getElementById('montab-health');
                  if(pane){pane.hidden=false;pane.style.display='';}
                  await loadPacing(true);
                  await new Promise(r=>setTimeout(r,700));
                }""")
                pg.wait_for_timeout(500)
                n = pg.evaluate(
                    "()=>document.querySelectorAll('#paceBox .pace-row').length")
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()
    assert n == len(_registry()), (
        "演示站节流面板只渲染了 %d 行，真实渠道 %d 家（App 渠道缺席）"
        % (n, len(_registry())))
