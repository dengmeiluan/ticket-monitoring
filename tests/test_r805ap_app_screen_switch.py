# -*- coding: utf-8 -*-
"""r805ap：内嵌 App 画面**切换渠道**必须整体切，不能只换标题。

用户原话：「问题内嵌画面切换 app 的时候没有正确切换」。

「切了」不等于「切对了」——一个只换标题、画面还停在旧 App 的实现看起来
也在工作。所以判据要求**四样一起**换到新渠道，且旧渠道的帧必须停：
  1. 弹窗标题；
  2. `aria-label`（读屏名称，静态 HTML 写死过「飞猪双端登录」，会串）；
  3. `APP_LOGIN.plat`（帧轮询的目标）；
  4. 切换之后的帧请求**只打到新渠道**——旧渠道的帧一条都不许再来。

2026-11-01 实测（demo，拦 `/api/app-login*` 记录请求目标）：
  打开智行 → 标题/aria/plat 均为智行，帧 `?plat=app_zhixing`；
  点「切换渠道 → 去哪儿 App」→ 三者均变为去哪儿，**其后 4 条帧请求
  全部 `?plat=app_qunar`**，无一条 app_zhixing。当前实现不复现该缺陷。

注意：demo 没有真机，`/api/app-login` 会失败，所以这里把两个端点都拦掉。
但**切换本身**与真机无关，正是本判据要守的部分。
"""
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def test_switching_app_screen_moves_title_aria_target_and_frames():
    import pytest

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
        for _ in range(160):
            try:
                op.open(base + "/api/state", timeout=1)
                break
            except Exception:
                time.sleep(0.25)
        else:
            pytest.skip("演示服务未在期限内起来")
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
                calls = []
                # 必须用正则：`**/api/app-login*` 的 `*` 不跨 `/`，
                # `/api/app-login/frame` 会漏拦（实测踩过一次）。
                pg.route(re.compile(r".*/api/app-login.*"), lambda route: (
                    calls.append(route.request.url),
                    route.fulfill(
                        status=200, content_type="application/json",
                        body=json.dumps({"ok": True, "plat": "x"}))))
                pg.goto(base)
                pg.wait_for_function(
                    "()=>typeof S!=='undefined'&&S&&S.users", timeout=30000)
                pg.evaluate("async()=>{switchView('cfg');"
                            "await new Promise(r=>setTimeout(r,2600));}")

                pg.evaluate("()=>appLoginOpen('app_zhixing')")
                pg.wait_for_timeout(900)
                first = pg.evaluate("""()=>{
                  const m=document.getElementById('lgModal');
                  return {title:(m.querySelector('.lgmodal-h b')||{})
                            .textContent||'',
                          aria:m.getAttribute('aria-label')||'',
                          plat:APP_LOGIN.plat,
                          on:[...m.querySelectorAll('.appsw-b.on')]
                            .map(x=>(x.textContent||'').trim())};
                }""")
                assert "智行" in first["title"], (
                    "打开智行后标题不对：%r" % first["title"])
                assert "智行" in first["aria"], (
                    "读屏名称没跟着渠道走：%r" % first["aria"])
                assert first["plat"] == "app_zhixing", (
                    "帧轮询目标不是智行：%r" % first["plat"])

                mark = len(calls)
                clicked = pg.evaluate("""()=>{
                  const m=document.getElementById('lgModal');
                  const btn=[...m.querySelectorAll('.appsw-b')]
                    .find(x=>/去哪儿/.test(x.textContent||''));
                  if(!btn)return false;
                  btn.click();return true;
                }""")
                assert clicked, "弹窗里没有「去哪儿 App」切换按钮"
                pg.wait_for_timeout(1200)
                second = pg.evaluate("""()=>{
                  const m=document.getElementById('lgModal');
                  return {title:(m.querySelector('.lgmodal-h b')||{})
                            .textContent||'',
                          aria:m.getAttribute('aria-label')||'',
                          plat:APP_LOGIN.plat,
                          kind:m.dataset.kind||'',
                          on:[...m.querySelectorAll('.appsw-b.on')]
                            .map(x=>(x.textContent||'').trim()),
                          disabled:[...m.querySelectorAll('.appsw-b')]
                            .filter(x=>x.disabled)
                            .map(x=>(x.textContent||'').trim())};
                }""")
            finally:
                b.close()
        assert not errs, "页面报错：%s" % errs[:3]
        # 四样一起换
        assert "去哪儿" in second["title"], (
            "切换后标题仍是 %r" % second["title"])
        assert "去哪儿" in second["aria"], (
            "切换后读屏名称仍是 %r（会把它念成上一家）" % second["aria"])
        assert second["plat"] == "app_qunar", (
            "切换后帧轮询目标仍是 %r（画面不会换）" % second["plat"])
        assert second["on"] == ["去哪儿 App"], (
            "切换按钮的选中态没跟上：%s" % second["on"])
        assert second["disabled"] == ["去哪儿 App"], (
            "当前渠道的按钮应置灰（防重复点自己）：%s" % second["disabled"])
        assert second["kind"] == "app", (
            "共用弹窗的归属被改成 %r，浏览器弹窗会来抢容器" % second["kind"])
        # 旧渠道的帧必须停：切换点之后不许再出现 app_zhixing 的帧请求
        after = calls[mark:]
        stale = [u for u in after if "app_zhixing" in u]
        assert not stale, (
            "切换后仍在给旧渠道取帧（画面会跳回旧 App）：%s" % stale[:3])
        new_frames = [u for u in after if "plat=app_qunar" in u]
        assert new_frames, (
            "切换后没有向新渠道取帧（画面不会显示新 App）：%s" % after[:3])
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()
