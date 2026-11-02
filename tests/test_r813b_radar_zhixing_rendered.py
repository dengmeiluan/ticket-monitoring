# -*- coding: utf-8 -*-
"""r813b：智行低价雷达入口必须真的可用（真浏览器往返）。

缺陷事实（2026-11-01）：r732 已把智行「特价」接成逐天报价源，但
`core/special_radar._CHANNELS` 与前端 `SRX_RADAR_APP_KEYS` 都没跟上。
后果不是「少一个开关」，而是：配置页勾得到（旧版其实连勾都勾不到），
就算勾上，`parse_query()` 也会把智行**静默过滤掉**——请求发出去了，
结果里永远没有它。静态断言「键存在」抓不到这种断链。

本门禁走真渲染 + 真点击 + 真请求体：
1. 「用户与航线」面板里 7 个渠道 chip 全部可见，智行可勾选；
2. 勾上智行点「查低价」，发给 `/api/special-radar` 的 JSON 里必须有
   `app_zhixing`；
3. 负控：取消勾选再查一次，请求体里必须**没有** `app_zhixing`
   （防止请求体写死全渠道冒充通过）；
4. 全程零 pageerror。
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


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def server():
    port = _free_port()
    p = subprocess.Popen([sys.executable, "webui.py", "--demo",
                          "--port", str(port)],
                         cwd=ROOT, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    up = False
    for _ in range(160):
        try:
            op.open("http://127.0.0.1:%d/api/state" % port, timeout=1)
            up = True
            break
        except Exception:
            time.sleep(0.25)
    if not up:
        p.terminate()
        pytest.skip("演示服务未在期限内起来")
    yield port
    p.terminate()


def _open_users_panel(port):
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    b = pw.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1512, "height": 1100})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto("http://127.0.0.1:%d/#cfg" % port,
            wait_until="domcontentloaded", timeout=30000)
    pg.wait_for_timeout(2200)
    pg.click('.cnav[data-p="users"]')
    pg.wait_for_timeout(1800)
    return pw, b, pg, errs


def test_zhixing_chip_is_visible_and_selectable(server):
    pw, b, pg, errs = _open_users_panel(server)
    try:
        info = pg.evaluate("""()=>{
          const chips=[...document.querySelectorAll('[data-radch]')];
          const zx=document.querySelector('[data-radch="app_zhixing"]');
          return {
            keys:[...chips].map(x=>x.dataset.radch),
            zxVisible:!!(zx&&(zx.offsetWidth||zx.offsetHeight)),
            zxChecked:!!(zx&&zx.checked),
            navKeys:(typeof srxRadarChannelKeys==='function')
              ?srxRadarChannelKeys():null,
          };
        }""")
        from core.channels import APP_CHANNELS, BROWSER_CHANNELS
        expected = set(BROWSER_CHANNELS) | set(APP_CHANNELS)
        assert set(info["keys"]) == expected, info
        assert "app_zhixing" in info["keys"], info
        assert info["zxVisible"], "智行 chip 在「用户与航线」面板里不可见"
        assert set(info["navKeys"] or []) == expected, info
        assert not errs, errs[:3]
    finally:
        b.close()
        pw.stop()


def test_zhixing_is_in_the_actual_radar_request(server):
    """勾上 → 请求体有；取消 → 请求体没有（负控同一条链路）。"""
    pw, b, pg, errs = _open_users_panel(server)
    try:
        pg.evaluate("""()=>{
          window.__radarPayload=null;
          const orig=window.fetch;
          window.fetch=function(url,opt){
            if(String(url).indexOf('/api/special-radar')>=0){
              try{window.__radarPayload=JSON.parse((opt&&opt.body)||'{}')}catch(e){}
              return Promise.resolve(new Response(JSON.stringify(
                {ok:true,channels:['app_zhixing'],days:[],status:{}}),
                {status:200,headers:{'Content-Type':'application/json'}}));
            }
            return orig.apply(this,arguments);
          };
          const zx=document.querySelector('[data-radch="app_zhixing"]');
          if(zx&&!zx.checked)zx.click();
          const fi=document.querySelector('[data-rad="from_name"]');
          const ti=document.querySelector('[data-rad="to_name"]');
          if(fi)fi.value='上海';
          if(ti)ti.value='北京';
        }""")
        pg.click("#uradGo-0")
        pg.wait_for_function("() => window.__radarPayload !== null",
                             timeout=8000)
        on = pg.evaluate("() => window.__radarPayload")
        assert "app_zhixing" in (on.get("channels") or []), on

        # 负控：取消勾选后同一条链路不得再带智行
        pg.evaluate("""()=>{
          window.__radarPayload=null;
          const zx=document.querySelector('[data-radch="app_zhixing"]');
          if(zx&&zx.checked)zx.click();
        }""")
        pg.click("#uradGo-0")
        pg.wait_for_function("() => window.__radarPayload !== null",
                             timeout=8000)
        off = pg.evaluate("() => window.__radarPayload")
        assert "app_zhixing" not in (off.get("channels") or []), off
        assert not errs, errs[:3]
    finally:
        b.close()
        pw.stop()
