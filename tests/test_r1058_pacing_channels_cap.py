# -*- coding: utf-8 -*-
"""r1058：渠道健康「逐渠道」窄档默认只露前 4 行。

用户反复否定「穷举默认铺开」。390 档 10 行渠道约 1100px，把本轮量尺/
干预推到首屏外。入口放小节头（内容在按钮下方，触发器不移动），
展开/收起同词同长：「展开全部渠道」↔「收起全部渠道」。
"""
import os
import sys

import pytest

pytest.importorskip("playwright",
                    reason="节流清单裁量依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def srv():
    import subprocess
    import tempfile
    import time
    import urllib.request

    global BASE
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    logf = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    priv = tempfile.mkdtemp(prefix="r1058_")
    env = dict(os.environ, TEMP=priv, TMP=priv, TMPDIR=priv,
               PYTHONIOENCODING="utf-8")
    proc = None
    for _ in (1, 2):
        port = _free_port()
        BASE = "http://127.0.0.1:%d" % port
        proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
             "--port", str(port)],
            cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT, env=env)
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        up = False
        for _ in range(60):
            if proc.poll() is not None:
                break
            try:
                op.open(BASE + "/api/state", timeout=2)
                up = True
                break
            except Exception:
                time.sleep(0.5)
        if up:
            break
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
    else:
        pytest.fail("demo 启动失败（两次新端口重试后）")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    logf.close()


SNAP = """(() => {
  const box=document.getElementById('paceBox');
  if(!box) return {exists:false};
  const list=box.querySelector('.pace-ch');
  const rows=list?[...list.querySelectorAll('.pace-row')]:[];
  const btn=box.querySelector('.pace-morebtn');
  const r=btn?btn.getBoundingClientRect():null;
  return {exists:true, n:rows.length,
    visible:rows.filter(x=>x.getBoundingClientRect().height>1).length,
    btnDisp:btn?getComputedStyle(btn).display:'none',
    txt:btn?(btn.textContent||'').trim():'',
    aria:btn?btn.getAttribute('aria-expanded'):null,
    box:r?[Math.round(r.left),Math.round(r.top+window.scrollY),Math.round(r.width)]:null,
    over:document.documentElement.scrollWidth>innerWidth+1};
})()"""


def _open(pg):
    pg.goto(BASE + "/", wait_until="load")
    pg.wait_for_function("typeof S!=='undefined'&&S&&S.users", timeout=25000)
    pg.wait_for_timeout(1500)
    pg.evaluate("()=>{switchView('mon');showMonTab('health');"
                "const f=document.getElementById('hpaceFold');"
                "if(f)f.open=true;}")
    pg.wait_for_timeout(2600)
    # 节流面板的 10 行是异步二次渲染；固定等待在 xdist 并发下会量到 0 行。
    # r1460：同一模块里前一条用例（390 档）先跑完后，这一条在慢/负载高时
    # 12s 内等不到 10 行（本机实测「单跑绿、连跑红」）。等不到就自己驱动一次
    # loadPacing()（= 用户点刷新），再等；判据不变。
    COND = "()=>document.querySelectorAll('#paceBox .pace-row').length>=10"
    try:
        pg.wait_for_function(COND, timeout=12000)
    except Exception:
        pg.evaluate("()=>{try{loadPacing()}catch(e){}}")
        pg.wait_for_function(COND, timeout=20000)
    # 并行负载下「行已入 DOM」早于切换动画/面板可见；不等到真实高度会把
    # 桌面误读成 0 行。仍不可见则照常判红。
    pg.wait_for_function(
        "()=>{const r=document.querySelector('#paceBox .pace-ch .pace-row');"
        "return r&&r.getBoundingClientRect().height>1}", timeout=12000)


def _assert_box_stable(a, b, stage):
    """按钮自身不得位移；允许 ±2px 的亚像素/滚动条凑整抖动，
    但宽度必须一致（文案切换不能改按钮盒）。"""
    assert a is not None and b is not None, "%s时按钮丢失：%s -> %s" % (stage, a, b)
    assert a[2] == b[2], "%s时按钮宽度变了：%s -> %s" % (stage, a, b)
    assert abs(a[0] - b[0]) <= 2 and abs(a[1] - b[1]) <= 2, \
        "%s时按钮位置跳了：%s -> %s" % (stage, a, b)


def test_pacing_channel_list_cap_and_toggle_on_phone(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        _open(pg)
        a = pg.evaluate(SNAP)
        assert a.get("exists"), "节流面板未渲染"
        assert a["n"] == 10, a
        # master v2.0：节流默认 10 行（行高 ≤64）；「收起全部渠道」只是可选折叠。
        assert a["visible"] == 10, "390 默认应显示 10 个渠道：%s" % a
        assert a["btnDisp"] != "none", "收起全部渠道按钮不可见：%s" % a
        assert a["txt"] == "收起全部渠道" and a["aria"] == "true", a
        pg.click("#paceBox .pace-morebtn")
        pg.wait_for_timeout(1200)
        b2 = pg.evaluate(SNAP)
        assert b2["visible"] == 4, "收起后应只露前 4 个渠道：%s" % b2
        assert b2["txt"] == "展开全部渠道" and b2["aria"] == "false", b2
        _assert_box_stable(a["box"], b2["box"], "收起")

        pg.click("#paceBox .pace-morebtn")
        pg.wait_for_timeout(1200)
        c = pg.evaluate(SNAP)
        assert c["visible"] == 10 and c["txt"] == "收起全部渠道" and c["aria"] == "true", c
        _assert_box_stable(a["box"], c["box"], "展开")
        assert not c["over"], c
        b.close()


def test_pacing_channel_list_uncapped_on_desktop(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1512, "height": 950})
        _open(pg)
        a = pg.evaluate(SNAP)
        assert a["visible"] == 10, "桌面不应裁渠道行：%s" % a
        assert a["btnDisp"] == "none", "桌面不该出现窄档展开钮：%s" % a
        assert not a["over"], a
        b.close()
