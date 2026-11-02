# -*- coding: utf-8 -*-
"""r631：结论文案必须真的出现在屏幕上（后端算出来 ≠ 用户看得见）。

r630 让 `effect_verdict` 在分域结论后补「同期渠道整体 X%→Y%」。
但前端消费 `v.effect` 的地方**只取 `state`**：

    const _ef=(ef.state==='improved'||ef.state==='recovered')?'干预有效' : …
    ev=(ev?ev+' · ':'')+_ef;

整句 `hint` 被丢弃，界面上只剩「部分改善」四个字。用户在 qunar 那一行
看不到「国际域 48%→53%，而整体 44%→84%」，也就无从判断「该换域」。

修法：从 hint 里摘出「同期渠道整体…」那半句拼进 `ev`（纯文本）。
**不能塞 HTML**：18469 行是 `esc(ev||'—')`，标签会被转义成字面量
（第一版把结论放进 `<span title>`，渲染后 title 数为 0，已回退重做）。

判据必须是真渲染：注入带 hint 的 effect 后，`.e1` 文本里必须含「同期渠道整体」。
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

HINT = ("国际域：有改善但仍偏低：48% → 53%，建议再自检一次；"
        "同期渠道整体 44% → 84%（整体已可用，是这个域没用到——可换域或先观察）")

INJECT = (
    "(()=>{const fake={ok:true,quiet:{},cfg:{warmup_platforms:['qunar']},"
    "last_round:{},effect:{},channels:{},recurrences:[],paths:{platforms:{}},"
    "coverage:{ok:[],sent:[]}};"
    "fake.channels.ctrip={state:'ok',remain_s:0,"
    "advice:{state:'ok',hint:'',severity:'ok'},"
    "effect:{state:'partial',hint:" + json.dumps(HINT, ensure_ascii=False) + ","
    "severity:'wait',before:0.44,after:0.84,after_n:98,action:'probe'}};"
    "const o=window.fetch;window.fetch=function(u,x){"
    "if(String(u).indexOf('/api/pacing')>=0)"
    "return Promise.resolve(new Response(JSON.stringify(fake),"
    "{status:200,headers:{'Content-Type':'application/json'}}));"
    "return o.apply(this,arguments)};return true})()"
)


def test_effect_hint_overview_reaches_the_row():
    """真渲染：`.e1` 文本里必须出现「同期渠道整体」。"""
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
        ok = False
        for _ in range(140):
            try:
                op.open(base + "/api/state", timeout=1); ok = True; break
            except Exception:
                time.sleep(0.25)
        if not ok:
            pytest.skip("演示服务未在期限内起来")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            if not os.path.exists(pw.chromium.executable_path):
                pytest.skip("chromium 二进制缺失")
            b = pw.chromium.launch()
            pg = b.new_page(viewport={"width": 1440, "height": 1100})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base)
            pg.wait_for_function("typeof S!=='undefined'&&S&&S.users",
                                 timeout=25000)
            pg.evaluate("()=>{switchView('mon');showMonTab('health')}")
            pg.wait_for_timeout(1000)
            pg.evaluate(INJECT)
            pg.evaluate("()=>loadPacing(true)")
            pg.wait_for_timeout(1500)
            rows = pg.evaluate(
                "(()=>{const b=document.getElementById('paceBox');"
                "return b?[...b.querySelectorAll('.e1')]"
                ".map(x=>x.textContent.trim()):[]})()")
            b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()

    assert not errs, "页面抛错：%s" % errs[:3]
    assert rows, "面板没有渲染出任何渠道行（.e1 为空）"
    joined = " | ".join(rows)
    assert "部分改善" in joined, (
        "干预结论短标签没上屏：%s" % joined[:200])
    assert "同期渠道整体" in joined, (
        "渠道全貌没有上屏——用户只看到「部分改善」，"
        "看不出该域 48%→53% 而整体 44%→84%：%s" % joined[:200])
