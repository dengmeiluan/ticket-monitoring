# -*- coding: utf-8 -*-
"""r805aj：登录开窗等待期必须看得见地在走。

用户原话：「弹窗好像有点问题，弹得比较慢，飞猪 pc 和 h5 淘宝」。

先量清「慢」到底在哪（2026-11-01，生产 8765 + demo 双份实测）：
  · 弹窗本身不慢——`lgOpenFliggy()` 到布局完成 1.1–4.3ms（5 次重复），
    `lgFliggyModalHTML()` 单次 0.005ms、HTML 仅 1KB、无背景图。
  · 真正会慢的是**点弹窗里的「飞猪登录」→ `/api/login`**：该接口是
    同步阻塞的，要等后台线程里浏览器窗口**真的 open**才返回，最长 45 秒
    （`ready.wait(0.5)` 循环到 `_deadline = now + 45`）。期间如果正撞上
    采集占着渠道锁（`session["queued"]=True`），还会更久。
  · 而按钮文字原先只有静态四个字「正在打开窗口…」，分不清「在排队」
    和「浏览器起不来」——这两种情况对用户的处置完全不同。

修法（两侧）：
  ① 后端 `_start_login` 成功时回传 `waited_ms` 与 `queued`（线程里已有
     `session["queued"]` 标记，只是从没回给前端）；
  ② 前端等待期每 500ms 用 `Date.now()` 差值刷新「正在打开窗口… Ns」，
     ≥6s 补一句「等采集让出该渠道」；成功后按 `queued` / 耗时说明原因。

判据（渲染层，拦截 fetch 模拟慢响应）：
  · 第 1 秒到第 5 秒，按钮文字必须**递增**（证明计时器真的在跑，不是死字）；
  · 跨过 6 秒必须出现「等采集」；
  · 负控实测：把 setInterval 里的 `Date.now()` 换成自增变量并让 interval
    失效，第 2 秒起文字不再变化，本判据即红。
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _serve():
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
    return None, None


def test_login_wait_shows_live_progress():
    import pytest

    srv, base = _serve()
    if srv is None:
        pytest.skip("演示服务未在期限内起来")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            if not os.path.exists(pw.chromium.executable_path):
                pytest.skip("chromium 二进制缺失")
            b = pw.chromium.launch()
            try:
                pg = b.new_page(viewport={"width": 1512, "height": 1100})
                errs = []
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.set_default_timeout(25000)
                pg.goto(base)
                pg.wait_for_function(
                    "()=>typeof S!=='undefined'", timeout=30000)
                # 把 /api/login 桩成 7 秒后返回，且 queued=true
                pg.evaluate("""()=>{
                  const _f = window.fetch;
                  window.fetch = function(u, o){
                    if(String(u).indexOf('/api/login') >= 0){
                      return new Promise(res => setTimeout(() => res(
                        new Response(JSON.stringify({
                          ok: true, plat: 'fliggy', slot: 'fliggy',
                          waited_ms: 7000, queued: true
                        }), {status: 200,
                             headers: {'Content-Type': 'application/json'}})
                      ), 7000));
                    }
                    return _f.apply(this, arguments);
                  };
                }""")
                pg.evaluate(
                    "async()=>{switchView('cfg');"
                    "await new Promise(r=>setTimeout(r,2600));}")
                pg.evaluate("()=>lgOpenFliggy()")
                pg.wait_for_timeout(300)
                btn = pg.query_selector(
                    '#lgModal .lglane[data-slot="fliggy"] button')
                assert btn, "弹窗里找不到「飞猪登录」按钮"
                btn.click()
                # 采样按**页面读数**收敛，不按墙钟：整机被 xdist 挤满时，
                # 页面的 500ms ticker 会晚触发，固定采 7×1s 会读到
                # 「1,2,3,4,5,5,5」——计时器没坏，只是被饿着了。这里等到
                # 读数 ≥6s（上限 25s）再断言，判据强度不变（仍要求真的跨过
                # 6 秒并出现「等采集」）。
                seen = []
                deadline = time.time() + 25
                rebuilt = False
                while time.time() < deadline:
                    pg.wait_for_timeout(500)
                    # 每拍重新取当前可见按钮：登录分区轮询会重建卡片，持有
                    # 旧节点读到的是被替换掉的死元素（实测停在「… 5s」）。
                    cur = pg.query_selector(
                        '#lgModal .lglane[data-slot="fliggy"] button')
                    try:
                        txt = (cur.inner_text() or "").strip() if cur else "<missing>"
                    except Exception:
                        txt = "<detached>"
                    seen.append(txt)
                    digits = "".join(ch for ch in txt if ch.isdigit())
                    # 到 2s 时强制重建一次卡片/弹窗：进行中必须从同一
                    # 起点继续，不能退回「飞猪登录」或从 1s 重来。
                    if not rebuilt and digits and int(digits) >= 2:
                        pg.evaluate(
                            "()=>{try{renderLoginCards(true);"
                            "lgRefreshFliggy()}catch(e){}}")
                        rebuilt = True
                    if digits and int(digits) >= 6:
                        break
                assert rebuilt, "没能在等待中触发一次卡片重建"
                assert all(t.startswith("正在打开窗口…") for t in seen[1:]), (
                    "卡片重建后等待态被换掉：%s" % seen)
            finally:
                b.close()
        assert not errs, "页面报错：%s" % errs[:3]
        assert seen[0].startswith("正在打开窗口…"), (
            "点击后按钮没有立刻进入等待态：%r" % seen[0])
        # 秒数必须一路递增（证明计时器在跑，不是死字）
        secs = []
        for t in seen:
            digits = "".join(ch for ch in t if ch.isdigit())
            secs.append(int(digits) if digits else -1)
        assert secs == sorted(secs) and len(set(secs)) >= 4, (
            "等待秒数没有在走（读作卡死）：%s" % secs)
        assert max(secs) >= 6, "等了 25 秒读数仍没跨过 6s：%s" % secs
        assert any("等采集" in t for t in seen), (
            "跨过 6 秒没有说明「在等采集让出渠道」——用户无法区分排队与"
            "浏览器起不来：%s" % seen)
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()
