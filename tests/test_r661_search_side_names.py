# -*- coding: utf-8 -*-
r"""r661：搜索/溯源一侧的渠道名与通路名也必须是中文，且不能漏 App 渠道。

r658–r659 修的是健康卡与节流面板。同一个名字问题在搜索任务一侧还有
三类：

1. **漏渠道**：`srxTaskPaths` 只遍历写死的 `SRX_PLAT_ORDER`（5 家浏览器
   渠道），智行 App 的通路证据在溯源里**整块不出现**——渠道看得见，
   查不到它走的哪条路（与 r643「看得见却点不到」同族）。
2. **裸通道 id**：`esc(x.path)` 直接把账本键名打上屏（`app-list`）。
3. **裸渠道 id**：8 处 `(SRX_PLATS[p]||[p])[0]` —— App 渠道不在
   `SRX_PLATS` 里，于是渲染成 `app_zhixing`（空态说明、筛选栏、
   任务卡、渠道下拉…）。

判据：
① 源码里不得再出现 `(SRX_PLATS[p]||[p])[0]` 这一取名字写法；
② `srxTaskPaths` 的渠道清单按数据派生（含 App），且通路名走 pathCN；
③ 真渲染：给一个含 App + 飞猪的任务载荷，断言两块都出现且名字是中文。
负控：把渠道清单换回 `SRX_PLAT_ORDER`，③必须红（App 整块消失）。
"""
import io
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LATIN = ("app_zhixing", "app-list", "snap-restore", "android-runtime",
         "app-dump", "app-blocker", "app-route", "app-error",
         "android-device")


def _src():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_no_second_channel_name_lookup():
    src = _src()
    assert "(SRX_PLATS[p]||[p])[0]" not in src, (
        "仍有地方用 SRX_PLATS 取渠道名——App 渠道不在那张表里，"
        "会直接打出 app_zhixing；应统一走 platCN(p)")


def test_task_paths_derive_channels_from_data():
    src = _src()
    i = src.index("function srxTaskPaths(lg){")
    seg = src[i:i + 1200]
    assert "SRX_PLAT_ORDER.forEach(p=>{" not in seg, (
        "溯源通路仍按写死的 5 家浏览器渠道遍历，App 渠道的证据永不出现")
    assert "Object.keys((lg&&lg.channels)||{})" in seg, (
        "渠道清单没有按本轮真实数据派生")
    assert "pathCN(x.path" in seg, "溯源通路名没走 pathCN"


def _render():
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
            pytest.skip("演示服务未在期限内起")
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
                return pg.evaluate(r"""()=>{
                  const html=srxTaskPaths({channels:{
                    app_zhixing:{paths:[{path:'app-list',status:'ok',
                                         rows:3},
                                        {path:'snap-restore',
                                         status:'error'}]},
                    fliggy:{paths:[{path:'H5',status:'login'}]}}});
                  const d=document.createElement('div');
                  d.innerHTML=html;
                  return (d.innerText||'').replace(/\s+/g,' ');}""")
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()


def test_task_trace_shows_app_paths_in_chinese():
    txt = _render()
    assert txt, "溯源通路没渲染出来，判据无从生效"
    leaks = [k for k in LATIN
             if k in txt.replace("智行 App", "")]  # 名字本身含 App 不算
    assert not leaks, "溯源里出现英文 id：%s（实测 %r）" % (leaks, txt)
    assert "App 航班列表" in txt, "App 渠道的通路没出现在溯源里：%r" % txt
    assert "H5" in txt, "浏览器渠道的通路丢了：%r" % txt
