# -*- coding: utf-8 -*-
"""r1038：320 档渠道登录名称完整 + 能力矩阵滑动提示按真实宽度显示。"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_static_narrow_login_and_hint_rules():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        src = f.read()
    i = src.index("r1038：320 档卡名被")
    block = src[i:i + 700]
    assert "@media(max-width:360px)" in block
    assert "#loginRows .lgcard .lgreq{display:none!important}" in block
    assert '#loginRows .lgcard[data-channel^="app_"] .lgtag{display:none!important}' in block
    j = src.index("r1038：能力矩阵常在配置页隐藏时返回")
    hint = src[j:j + 400]
    assert "requestAnimationFrame(()=>{try{dimScrollHint()}catch(e){}})" in hint
    # 提示仍只在真实溢出时出现（不是固定显示）
    k = src.index("function dimScrollHint()")
    assert "scrollWidth>wrap.clientWidth+2" in src[k:k + 260]


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


MEASURE = """()=>{
  const disp=el=>getComputedStyle(el).display;
  const names=[...document.querySelectorAll('#loginRows .lgnm')].map(el=>({
    t:el.textContent.trim(),sw:el.scrollWidth,cw:el.clientWidth,w:+el.getBoundingClientRect().width.toFixed(1)}));
  const req=[...document.querySelectorAll('#loginRows .lgreq')].map(disp);
  const appTags=[...document.querySelectorAll('#loginRows .lgcard[data-channel^="app_"] .lgtag')].map(disp);
  const webTags=[...document.querySelectorAll('#loginRows .lgcard:not([data-channel^="app_"]) .lgtag')].map(disp);
  const wrap=document.querySelector('#cfgDimMatrix .dimwrap');
  const hint=document.querySelector('#cfgDimMatrix .dimscroll');
  const before=wrap.scrollLeft;
  wrap.scrollLeft=9999;
  const th=wrap.querySelector('tbody th:not([colspan])');
  const wr=wrap.getBoundingClientRect(), tr=th.getBoundingClientRect();
  const out={names,req,appTags,webTags,hint:disp(hint),
    mx:{sw:wrap.scrollWidth,cw:wrap.clientWidth,thL:+tr.left.toFixed(1),thR:+tr.right.toFixed(1),
        wrapL:+wr.left.toFixed(1),wrapR:+wr.right.toFixed(1),maxScroll:wrap.scrollLeft},
    pageOF:document.documentElement.scrollWidth-innerWidth};
  wrap.scrollLeft=before;
  return out;
}"""


def test_rendered_320_names_and_matrix_hint():
    import pytest
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        pytest.skip("playwright 缺失")
    port = _free_port()
    base = "http://127.0.0.1:%d" % port
    srv = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(port)],
                           cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ok = False
        for _ in range(90):
            try:
                urllib.request.urlopen(base + "/api/state", timeout=2)
                ok = True
                break
            except Exception:
                time.sleep(0.5)
        if not ok:
            pytest.skip("demo 服务未起来")
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            try:
                out = {}
                for width in (320, 390, 900, 1512):
                    pg = br.new_page(viewport={"width": width, "height": 900})
                    pg.goto(base + "/", wait_until="domcontentloaded")
                    pg.wait_for_timeout(1800)
                    pg.evaluate("switchView('cfg')")
                    pg.wait_for_timeout(1200)
                    # r1760：维度矩阵是数据驱动渲染的，没出来就测量会 null 崩
                    # （CI 实测 scrollLeft of null）。先等节点，再量。
                    try:
                        pg.wait_for_selector("#cfgDimMatrix .dimwrap",
                                             timeout=15000)
                        pg.wait_for_selector("#loginRows .lgnm",
                                             timeout=15000)
                    except Exception as e:
                        raise AssertionError(
                            "维度矩阵/登录行没渲染出来：%s" % str(e)[:120])
                    out[width] = pg.evaluate(MEASURE)
                    pg.close()

                for width in (320, 390):
                    d = out[width]
                    # 名称逐一完整：无省略（scrollWidth 不超过 clientWidth）
                    bad = [n for n in d["names"] if n["sw"] > n["cw"] + 1]
                    assert not bad, (width, bad)
                    assert len(d["names"]) == 10, (width, len(d["names"]))
                    # 矩阵真实溢出 → 提示显示，首列冻结在左侧
                    assert d["mx"]["sw"] > d["mx"]["cw"] + 2, (width, d["mx"])
                    assert d["hint"] != "none", (width, d["hint"])
                    assert d["mx"]["maxScroll"] > 0, (width, d["mx"])
                    assert d["mx"]["thL"] >= d["mx"]["wrapL"] - 1, (width, d["mx"])
                    assert d["mx"]["thR"] <= d["mx"]["wrapR"] + 1, (width, d["mx"])
                    assert d["pageOF"] <= 1, (width, d["pageOF"])

                # 320：行内要求与 App 真机标签让位给名称；390 起原样保留
                assert set(out[320]["req"]) == {"none"}, out[320]["req"]
                assert set(out[320]["appTags"]) == {"none"}, out[320]["appTags"]
                assert "block" in out[320]["webTags"], out[320]["webTags"]
                assert set(out[390]["req"]) == {"block"}, out[390]["req"]
                assert set(out[390]["appTags"]) == {"block"}, out[390]["appTags"]

                for width in (900, 1512):
                    d = out[width]
                    assert not [n for n in d["names"] if n["sw"] > n["cw"] + 1], (width, d["names"])
                    assert set(d["req"]) == {"block"}, (width, d["req"])
                    assert set(d["appTags"]) == {"block"}, (width, d["appTags"])
                    # 表格放得下时不得出现「左右滑动」假提示
                    assert d["mx"]["sw"] <= d["mx"]["cw"] + 2, (width, d["mx"])
                    assert d["hint"] == "none", (width, d["hint"])
                    assert d["pageOF"] <= 1, (width, d["pageOF"])
            finally:
                br.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=8)
        except Exception:
            srv.kill()
