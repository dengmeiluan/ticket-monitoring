# -*- coding: utf-8 -*-
"""r1147：桌面筛选/渠道入口必须是贴按钮 popover，不是底部弹层/居中大窗。

1440/1024/900/768：筛选 1280×≤78vh、右缘或左缘与触发按钮对齐、gap 8、
14px 圆角、桌面无遮罩/不锁 body；渠道入口 480×≤70vh 同规则。
390：两者降级为满宽底部抽屉（80vh）+ 遮罩 + 锁 body。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

pytest.importorskip("playwright", reason="渲染门禁依赖 playwright")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None
DESKTOP = [1440, 1024, 900, 768]


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def srv():
    global BASE
    import tempfile
    logf = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    priv = tempfile.mkdtemp(prefix="r1147_")
    env = dict(os.environ, TEMP=priv, TMP=priv, TMPDIR=priv,
               PYTHONIOENCODING="utf-8")
    proc = None
    for attempt in range(3):
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
                body = op.open(BASE + "/", timeout=2).read().decode("utf-8", "replace")
                if "placeAnchoredPopover" in body:
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
        pytest.fail("demo 启动失败或服务是旧构建（页面缺 placeAnchoredPopover）")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    logf.close()


SNAP = """([sel,btnSel]) => {
  const d=document.querySelector(sel);
  const b=document.querySelector(btnSel);
  if(!d) return null;
  const r=d.getBoundingClientRect(), rb=b?b.getBoundingClientRect():null;
  const cs=getComputedStyle(d);
  const mask=document.getElementById(sel==='#srxCtxFly'?'srxCtxMask':'srxChLinksMask');
  return {rect:{l:r.left,r:r.right,t:r.top,b:r.bottom,w:r.width,h:r.height},
    btn:rb?{l:rb.left,r:rb.right,t:rb.top,b:rb.bottom,w:rb.width}:null,
    radius:cs.borderRadius, maxh:cs.maxHeight, position:cs.position,
    maskHidden:mask?mask.hidden:null, bodyOverflow:document.body.style.overflow,
    ariaModal:d.getAttribute('aria-modal'),
    vw:document.documentElement.clientWidth, vh:innerHeight,
    scrollW:document.documentElement.scrollWidth};
}"""


def _open_search(page):
    page.goto(BASE + "/#search", wait_until="networkidle")
    page.wait_for_timeout(1500)


def _trigger(page, kind):
    if kind == "filter":
        box = page.query_selector("#srxFilterBtn")
        if box and box.is_visible():
            return "#srxFilterBtn"
        return "#srxMobilebar [data-mobile='filters']"
    return "#srxChLinksBtn"


def _live_trigger(page, kind):
    """开合后按钮会变：≤1100 档点「筛选」后，动作条把入口换成右侧
    「收起筛选」按钮（同一 #srxFilterBtn 被移到右缘）。门禁必须按
    产品实际使用的那个触发器量对齐，否则会拿旧入口坐标误判。"""
    if kind != "filter":
        return _trigger(page, kind)
    return page.evaluate("""()=>{
      const b=document.getElementById('srxFilterBtn');
      if(b&&b.getBoundingClientRect().width>2&&innerWidth>600)return '#srxFilterBtn';
      const m=document.querySelector('#srxMobilebar [data-mobile="filters"]');
      if(m&&m.getBoundingClientRect().width>2)return '#srxMobilebar [data-mobile="filters"]';
      return '#srxFilterBtn';
    }""")


def _check(d, kind):
    bad = []
    if not d:
        return ["面板不存在"]
    vw, vh, r = d["vw"], d["vh"], d["rect"]
    if d["position"] != "fixed":
        bad.append("position=%s" % d["position"])
    if vw > 600:
        # r1352：筛选弹层尽量宽（上限 1280），但始终贴触发按钮的同侧边缘
        # 且保留 12px 内衬；宽度让位，不把面板推出视口。
        if kind == "filter":
            btn = d["btn"]
            if (btn["l"] + btn["w"] / 2) <= vw / 2:
                want = min(1280, vw - 24, vw - 12 - round(btn["l"]))
            else:
                want = min(1280, vw - 24, round(btn["r"]) - 12)
        else:
            want = min(480, vw - 24)
        if abs(r["w"] - want) > 2:
            bad.append("宽 %.1f（应 %s）" % (r["w"], want))
        if abs(r["t"] - (d["btn"]["b"] + 8)) > 2:
            bad.append("未贴按钮下方 8px: top=%.1f btnBottom=%.1f"
                       % (r["t"], d["btn"]["b"]))
        end_ok = abs(r["r"] - d["btn"]["r"]) <= 2
        start_left = min(max(12, d["btn"]["l"]), vw - 12 - r["w"])
        start_ok = abs(r["l"] - start_left) <= 2
        if not (end_ok or start_ok):
            bad.append("未同侧对齐: panel=[%.1f,%.1f] btn=[%.1f,%.1f]"
                       % (r["l"], r["r"], d["btn"]["l"], d["btn"]["r"]))
        if r["l"] < 12 or r["r"] > vw - 12:
            bad.append("越出 12px 内衬")
        if r["h"] > vh * (0.78 if kind == "filter" else 0.70) + 2:
            bad.append("高度 %.1f 超过上限" % r["h"])
        if "14px" not in (d["radius"] or ""):
            bad.append("圆角 %s（应 14px）" % d["radius"])
        if d["maskHidden"] is False:
            bad.append("桌面不应出现遮罩")
        if d["bodyOverflow"]:
            bad.append("桌面不应锁 body: %r" % d["bodyOverflow"])
        if d["ariaModal"] != "false":
            bad.append("桌面 aria-modal=%r（应 false）" % d["ariaModal"])
    else:
        if abs(r["b"] - vh) > 2 or abs(r["r"] - vw) > 12:
            bad.append("移动端不是满宽底部抽屉")
        if d["maskHidden"] is not False:
            bad.append("移动端缺遮罩")
        if d["bodyOverflow"] != "hidden":
            bad.append("移动端未锁 body")
        if d["ariaModal"] != "true":
            bad.append("移动端 aria-modal=%r（应 true）" % d["ariaModal"])
    if d["scrollW"] - vw > 1:
        bad.append("页面横向溢出 %s" % (d["scrollW"] - vw))
    return bad


def test_filter_popover_anchored(srv):
    from playwright.sync_api import sync_playwright
    bad = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        for w in DESKTOP + [390]:
            pg = b.new_page(viewport={"width": w, "height": 900})
            _open_search(pg)
            trig=_trigger(pg, "filter");pg.click(trig)
            pg.wait_for_timeout(800)
            trig=_live_trigger(pg, "filter")
            d = pg.evaluate(SNAP, ["#srxCtxFly", trig])
            bad += ["%d filter: %s" % (w, x) for x in _check(d, "filter")]
            if w > 600:
                # 负控：把面板改回贴底居中 560，门禁必须报红
                pg.evaluate("""()=>{const f=document.getElementById('srxCtxFly');
                  f.style.setProperty('--pop-top','auto','important');
                  f.style.setProperty('--pop-left','50%','important');
                  f.style.setProperty('width','560px','important');
                  f.style.setProperty('max-height','80vh','important');
                  f.style.setProperty('transform','translateX(-50%)','important');
                  f.style.setProperty('bottom','0','important')}""")
                pg.wait_for_timeout(150)
                neg = _check(pg.evaluate(SNAP, ["#srxCtxFly", trig]), "filter")
                if not neg:
                    bad.append("%d filter 负控：贴底居中 560 未被拦" % w)
            pg.close()
        b.close()
    assert not bad, "筛选 popover: " + "；".join(bad)


def test_channel_popover_anchored(srv):
    from playwright.sync_api import sync_playwright
    bad = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        for w in DESKTOP + [390]:
            pg = b.new_page(viewport={"width": w, "height": 900})
            _open_search(pg)
            trig="#srxChLinksBtn";pg.click(trig)
            pg.wait_for_timeout(900)
            d = pg.evaluate(SNAP, ["#srxChLinksDrawer", trig])
            bad += ["%d channel: %s" % (w, x) for x in _check(d, "channel")]
            if w > 600:
                pg.evaluate("""()=>{const f=document.getElementById('srxChLinksDrawer');
                  f.style.setProperty('--pop-top','auto','important');
                  f.style.setProperty('--pop-left','50%','important');
                  f.style.setProperty('width','560px','important');
                  f.style.setProperty('max-height','80vh','important');
                  f.style.setProperty('transform','translateX(-50%)','important');
                  f.style.setProperty('bottom','0','important')}""")
                pg.wait_for_timeout(150)
                neg = _check(pg.evaluate(SNAP, ["#srxChLinksDrawer", trig]), "channel")
                if not neg:
                    bad.append("%d channel 负控：贴底居中 560 未被拦" % w)
            pg.close()
        b.close()
    assert not bad, "渠道入口 popover: " + "；".join(bad)
