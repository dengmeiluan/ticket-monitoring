# -*- coding: utf-8 -*-
"""r813i：主动探针必须能选到 7 家（含两款 App），不是 5 家。

缺陷事实（2026-11-01 审计）：探针渠道选择器 `#srxPlatPick` 是静态 HTML，
只写了 5 个浏览器 chip；后端 `/api/probe/start` 却按 `REGISTRY` 接受任意
平台（App 也在内）。结果：检索页的主动探针永远无法请求两款 App，用户
只能等定时采集——与「两款 App 要接进检索页每个角落」直接冲突。

本门禁：
1. 选择器 7 个 chip，`data-p` 与注册渠道一致，官方图标逐 chip 对上；
2. 浏览器 5 家默认勾选、两款 App 默认不勾（真机慢，需显式选择）；
3. 勾智行 → `/api/probe/start` 请求体 `plats` 只有 `app_zhixing`；
   改勾携程 → 只有 `ctrip`（负控，防请求体写死全渠道冒充通过）；
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
ALL = ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu",
       "app_zhixing", "app_qunar")
BROWSER = ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu")


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


def _open(port):
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    b = pw.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1512, "height": 1100})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto("http://127.0.0.1:%d/#search" % port,
            wait_until="domcontentloaded", timeout=30000)
    pg.wait_for_function("typeof S!=='undefined' && S && S.users",
                         timeout=15000)
    pg.wait_for_timeout(1800)
    return pw, b, pg, errs


def test_probe_picker_covers_seven_channels(server):
    pw, b, pg, errs = _open(server)
    try:
        chips = pg.evaluate("""()=>[...document.querySelectorAll(
          '#srxPlatPick .srx-pchip')].map(l=>{
            const ic=l.querySelector('[data-plat]');
            return {p:l.dataset.p,
                    checked:!!l.querySelector('input').checked,
                    txt:l.textContent.trim(),
                    aria:(l.getAttribute('aria-label')||''),
                    title:(l.getAttribute('title')||''),
                    icon:ic?ic.dataset.plat:''};})""")
        assert len(chips) == 7, chips
        assert {c["p"] for c in chips} == set(ALL), chips
        for c in chips:
            assert c["icon"] == c["p"], ("chip 没有对应官方图标", c)
            # 浏览器 5 家带文字；App 是真机可选，用官方图标 + 名称供
            # 悬停/读屏识别（带文字会挤爆「探针一行」——r813i 实测）
            if c["p"] in BROWSER:
                assert c["txt"], c
            else:
                assert "App" in (c["aria"] + c["title"]), c
        by = {c["p"]: c for c in chips}
        assert all(by[p]["checked"] for p in BROWSER), by
        assert not by["app_zhixing"]["checked"], by["app_zhixing"]
        assert not by["app_qunar"]["checked"], by["app_qunar"]
        assert not errs, errs[:3]
    finally:
        b.close()
        pw.stop()


def test_probe_request_can_target_app_channel(server):
    pw, b, pg, errs = _open(server)
    try:
        pg.evaluate("""()=>{
          window.__probePayload=null;
          const orig=window.fetch;
          window.fetch=function(url,opt){
            if(String(url).indexOf('/api/probe/start')>=0){
              try{window.__probePayload=JSON.parse((opt&&opt.body)||'{}')}catch(e){}
              return Promise.resolve(new Response(JSON.stringify(
                {ok:false,err:'测试拦截'}),{status:200,
                headers:{'Content-Type':'application/json'}}));
            }
            return orig.apply(this,arguments);
          };
          const f=$('srxFrom'),t=$('srxTo'),d=$('srxDate');
          f.value='SHA';t.value='PEK';d.value='2026-12-01';
          document.querySelectorAll('#srxPlatPick input').forEach(i=>{
            i.checked=(i.value==='app_zhixing');});
        }""")
        pg.evaluate("srxProbeRun()")
        pg.wait_for_function("() => window.__probePayload !== null",
                             timeout=6000)
        on = pg.evaluate("() => window.__probePayload")
        assert on.get("plats") == ["app_zhixing"], on

        # 负控：只勾携程时不得再带 App
        pg.evaluate("""()=>{
          window.__probePayload=null;
          document.querySelectorAll('#srxPlatPick input').forEach(i=>{
            i.checked=(i.value==='ctrip');});
        }""")
        pg.evaluate("srxProbeRun()")
        pg.wait_for_function("() => window.__probePayload !== null",
                             timeout=6000)
        off = pg.evaluate("() => window.__probePayload")
        assert off.get("plats") == ["ctrip"], off
        assert not errs, errs[:3]
    finally:
        b.close()
        pw.stop()
