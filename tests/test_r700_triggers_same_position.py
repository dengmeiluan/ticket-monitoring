# -*- coding: utf-8 -*-
"""r700 检索页所有展开触发器：两态必须同坐标（九档宽）。

用户原话：「展开和收起都不在同一个位置，明显不是一个按钮多态的设计」。
判据用渲染几何：同一触发器点击前后 left/top 差 ≤2px。
宽度变化允许（窄档按钮可能变宽），位置不允许。

修前实测：390 档「展开概览」top 394→426（+32px）；320 档 left 226→52
（-174px）且纵移 +52px，原因分别是摘要/翻页把按钮挤到第二行。
"""
import os
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TAG = r"""() => {
  document.querySelectorAll('[data-r700]').forEach(e=>e.removeAttribute('data-r700'));
  const vis=e=>{const s=getComputedStyle(e);const r=e.getBoundingClientRect();
    return s.visibility!=='hidden'&&s.display!=='none'&&r.width>4&&r.height>4;};
  const out=[];let i=0;
  document.querySelectorAll('#searchview [aria-expanded]').forEach(e=>{
    if(e.tagName==='INPUT'||e.tagName==='SELECT'||e.tagName==='TR')return;
    if(!vis(e))return;
    const id=e.id||'';
    if(!id&&!e.classList.length)return;
    e.setAttribute('data-r700','n'+i);
    out.push({h:'n'+i++,
      key:(id||e.className.toString().split(/\s+/)[0])+'|'+
          (e.textContent||'').trim().replace(/\s+/g,' ').slice(0,12),
      st:e.getAttribute('aria-expanded')});});
  return out;
}"""
MEASURE = r"""(h) => {
  const e=document.querySelector('[data-r700="'+h+'"]');
  if(!e)return {err:'gone'};
  const r=e.getBoundingClientRect();
  return {l:+r.left.toFixed(1), t:+r.top.toFixed(1),
          st:e.getAttribute('aria-expanded')};
}"""
CLICK = r"""(h) => {const e=document.querySelector('[data-r700="'+h+'"]');
  if(!e)return false;e.click();return true;}"""


def test_every_disclosure_trigger_keeps_its_position_across_states():
    from playwright.sync_api import sync_playwright
    port = 9020
    srv = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(port)],
                           cwd=ROOT, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        up = False
        for _ in range(80):
            try:
                op.open("http://127.0.0.1:%d/api/state" % port, timeout=2)
                up = True
                break
            except Exception:
                time.sleep(0.5)
        if not up:
            pytest.skip("demo 服务未起来")
        bad = []
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            for W in (1512, 1100, 760, 430, 320):
                pg = br.new_page(viewport={"width": W, "height": 950})
                pg.goto("http://127.0.0.1:%d/" % port, wait_until="domcontentloaded")
                pg.wait_for_timeout(1500)
                pg.evaluate("switchView('search')")
                pg.wait_for_timeout(1100)
                for t in pg.evaluate(TAG):
                    if t["st"] == "true":
                        pg.evaluate(CLICK, t["h"])
                        pg.wait_for_timeout(300)
                    a = pg.evaluate(MEASURE, t["h"])
                    if a.get("err"):
                        continue
                    pg.evaluate(CLICK, t["h"])
                    pg.wait_for_timeout(380)
                    b = pg.evaluate(MEASURE, t["h"])
                    if b.get("err"):
                        continue
                    pg.evaluate(CLICK, t["h"])
                    pg.wait_for_timeout(220)
                    dl, dt = b["l"] - a["l"], b["t"] - a["t"]
                    if abs(dl) > 2 or abs(dt) > 2:
                        bad.append("w=%d %s dl=%+.1f dt=%+.1f"
                                   % (W, t["key"][:24], dl, dt))
                pg.close()
            br.close()
        assert not bad, "展开/收起位置不一致：%r" % bad[:8]
    finally:
        srv.terminate()
