# -*- coding: utf-8 -*-
"""r996：390 关注名册行不再四列挤压（日期折三行、平台名被省略）。

用户反复点名「组件挤压 / 字体对齐 / 大片空白」。关注名册在 390 的
原四列布局（航班/价格/状态/动作）只有 304px，日期折成三行。现改为
两行：身份整行，价格+平台+时段与状态/动作分列。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_css_keeps_two_row_mobile_contract():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        src = f.read()
    assert 'grid-template-areas:"id id state" "price act act"' in src
    # App 渠道入口跨面统一为两端动作行，不再回落到 4 列矩阵的单格
    assert ".chband-approw{display:flex" in src
    assert "chband-approw" in src


def _boot():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
         "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = "http://127.0.0.1:%d" % port
    t0 = time.time()
    while time.time() - t0 < 60:
        try:
            op.open(base + "/api/state", timeout=2)
            return srv, base
        except Exception:
            time.sleep(0.3)
    srv.kill()
    raise RuntimeError("demo server did not start")


def test_rendered_watch_row_is_readable_at_390():
    import pytest
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        pytest.skip("playwright 缺失")
    with sync_playwright() as pw:
        if not os.path.exists(pw.chromium.executable_path):
            pytest.skip("chromium 二进制缺失")
    srv, base = _boot()
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            try:
                pg = b.new_page(viewport={"width": 390, "height": 844})
                pg.goto(base)
                pg.wait_for_function(
                    "typeof S!=='undefined'&&S&&S.users", timeout=30000)
                pg.evaluate("()=>{switchView('mon');showMonTab('watch')}")
                pg.wait_for_timeout(2200)
                out = pg.evaluate(r"""()=>{
                  const row=document.querySelector('#wsList .ws-row-main');
                  if(!row)return {err:'no row'};
                  const cs=getComputedStyle(row);
                  const rr=row.getBoundingClientRect();
                  const date=row.querySelector('.ws-rc.ident .nm span');
                  const price=row.querySelector('.ws-rc.price .v');
                  const pname=row.querySelector('.ws-rc.price .ws-pname');
                  const act=row.querySelector('.ws-row-act');
                  const range=document.createRange();range.selectNodeContents(date);
                  const tops=new Set();
                  for(const b of range.getClientRects())
                    if(b.height>2)tops.add(Math.round(b.top));
                  return {w:+rr.width.toFixed(1),sw:row.scrollWidth,
                    areas:cs.gridTemplateAreas,
                    dateLines:tops.size,
                    pnameVisible:!!pname&&getComputedStyle(pname).display!=='none'
                      &&pname.getBoundingClientRect().width>1,
                    priceRight:+price.getBoundingClientRect().right.toFixed(1),
                    actLeft:+act.getBoundingClientRect().left.toFixed(1),
                    rowOverflow:document.documentElement.scrollWidth
                      -document.documentElement.clientWidth};}""")
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=8)
        except Exception:
            srv.kill()
    assert not out.get("err"), out
    assert out["areas"].replace("\n", " ").replace('"', "") == \
        "id id state price act act", out
    assert out["dateLines"] == 1, "日期/舱位在 390 仍折行：%s" % out
    assert out["pnameVisible"], "平台名被隐藏：%s" % out
    assert out["priceRight"] <= out["actLeft"] + 1, out
    assert out["sw"] <= out["w"] + 1, out
    assert out["rowOverflow"] <= 0, out
