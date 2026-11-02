# -*- coding: utf-8 -*-
"""r797 门禁：用户手动展开的折叠区，在表单重建后必须仍然展开。

来由（2026-11-01 实测）：`buildForm()` 重建 DOM 后由 `applyFolds()` 按
`FOLD` 回放折叠态。所以「点开一条航线」必须把状态写进 `FOLD`，只在当前
DOM 上翻 `display` 是不够的——配置拉回/保存/切换用户都会重建表单，
否则用户刚点开的航线会自己收回去（用户原话「收不回去了、非常割裂」）。

这条与 r339g 是同一处机制的两面：那边守「测试别拿临时态当持久态」，
这边守「产品的手动展开确实写进了持久态」。

判据（真浏览器）：
1. 初始收起 → 点 `.rhead` 展开后 `aria-expanded=true` 且正文可见；
2. `FOLD.route[rk]` 必须被写成 false（持久化）；
3. 调一次 `buildForm()`（等价于配置重渲）后，仍然展开、正文仍可见。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STATE = """()=>{
  const rl=document.querySelector('#cfgform .rline[data-rk]');
  if(!rl)return {none:1};
  const h=rl.querySelector('.rhead'), body=h.nextElementSibling;
  return {rk:rl.dataset.rk, aria:h.getAttribute('aria-expanded'),
          bodyDisp:body?getComputedStyle(body).display:null,
          bodyH:body?Math.round(body.getBoundingClientRect().height):null,
          fold:(typeof FOLD!=='undefined')?FOLD.route[rl.dataset.rk]:null};}"""


@pytest.fixture(scope="module")
def srv():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    base = "http://127.0.0.1:%d" % port
    proc = subprocess.Popen([sys.executable, "webui.py", "--demo",
                             "--port", str(port)],
                            cwd=ROOT, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    up = False
    for _ in range(90):
        try:
            op.open(base + "/api/state", timeout=2)
            up = True
            break
        except Exception:
            time.sleep(0.4)
    if not up:
        proc.terminate()
        pytest.skip("demo 服务未起来")
    yield base
    proc.terminate()


def test_manual_expand_survives_form_rebuild(srv):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch()
        try:
            pg = b.new_page(viewport={"width": 1440, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(srv + "/", wait_until="domcontentloaded", timeout=30000)
            pg.wait_for_timeout(1800)
            pg.evaluate("switchView('cfg')")
            pg.wait_for_function(
                "typeof CFG!=='undefined'&&CFG&&CFG.length", timeout=25000)
            pg.evaluate("showCfgPanel('users')")
            pg.wait_for_timeout(800)
            assert not errs, errs[:3]

            before = pg.evaluate(STATE)
            assert not before.get("none"), before
            if before["aria"] == "true":   # 已经是展开态就别再点（会收起）
                pg.evaluate("""()=>{const h=document.querySelector(
                  '#cfgform .rline[data-rk] .rhead');if(h)h.click();}""")
                pg.wait_for_timeout(200)
            pg.evaluate("""()=>{const h=document.querySelector(
              '#cfgform .rline[data-rk] .rhead');if(h)h.click();}""")
            pg.wait_for_timeout(250)
            opened = pg.evaluate(STATE)
            assert opened["aria"] == "true", opened
            assert opened["bodyH"] and opened["bodyH"] > 0, opened
            assert opened["fold"] is False, (
                "手动展开没有写进 FOLD——重建表单就会收回去：%s" % opened)

            pg.evaluate("buildForm()")
            pg.wait_for_timeout(500)
            after = pg.evaluate(STATE)
            assert after["aria"] == "true", (
                "重建表单后航线自己收起了（用户读作「收不回去了/状态保不住」）："
                "%s" % after)
            assert after["bodyH"] and after["bodyH"] > 0, after
            assert not errs, errs[:3]
        finally:
            b.close()
