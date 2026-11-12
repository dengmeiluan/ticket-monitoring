# -*- coding: utf-8 -*-
"""r1130：2026-11-07 全站页面质量契约（P1）。

覆盖 10 个页面表面 × 1440/390 × 亮/暗：
- 页面级横向溢出 = 0；
- 真实越出视口的元素 = 0（排除自身在横向滚动容器内的表格/轨）；
- 可见交互控件两两重叠 = 0；
- 每页都有主标题/卡片头，页面不是空白；
- 静态：无 10.5/21px 字号、无裸「收起」按钮、启动级说明完整。
"""
import os
import sys

import pytest

pytest.importorskip("playwright",
                    reason="全站页面契约依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None
VIEWS = [
    ("mon", "overview", "概览"), ("mon", "specials", "特价"),
    ("mon", "trend", "走势"), ("mon", "watch", "关注"),
    ("mon", "details", "明细"), ("mon", "health", "健康"),
    ("search", None, "检索"), ("cfg", "login", "登录"),
    ("cfg", "users", "用户"), ("cfg", "globals", "参数"),
]


def test_static_p1_copy_and_scale():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        src = f.read()
    assert "font-size:10.5px" not in src
    assert "font-size:21px" not in src
    assert ">收起</button>" not in src
    assert "部分需重启" in src
    assert "数据库/日志/登录态/内核路径、监听地址、启动即扫需重启" in src


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
    priv = tempfile.mkdtemp(prefix="r1130w3_")
    env = dict(os.environ, TEMP=priv, TMP=priv, TMPDIR=priv, PYTHONIOENCODING="utf-8")
    proc = None
    for _ in (1, 2):
        port = _free_port()
        BASE = "http://127.0.0.1:%d" % port
        proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "webui.py"), "--demo", "--port", str(port)],
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


SNAP = r"""() => {
  const vw = innerWidth;
  function vis(e){const c=getComputedStyle(e),r=e.getBoundingClientRect();
    return c.display!=='none'&&c.visibility!=='hidden'&&c.opacity!=='0'&&r.width>2&&r.height>2;}
  const out=[];
  for(const e of document.querySelectorAll('body *')){
    if(!vis(e))continue;const r=e.getBoundingClientRect();
    if(r.right<=vw+2&&r.left>=-2)continue;
    let n=e.parentElement,scroll=false;
    while(n){const nc=getComputedStyle(n);
      if((nc.overflowX==='auto'||nc.overflowX==='scroll')&&n.getBoundingClientRect().width<=vw+2){scroll=true;break}
      n=n.parentElement}
    if(!scroll)out.push({tag:e.tagName,id:e.id,cls:String(e.className).slice(0,30)});
  }
  const cs=[...document.querySelectorAll('button,input,select,a,summary,[role=button]')]
    .filter(e=>{const c=getComputedStyle(e),r=e.getBoundingClientRect();
      return c.display!=='none'&&c.visibility!=='hidden'&&r.width>4&&r.height>4&&r.bottom>0&&r.top<innerHeight});
  const over=[];
  for(let i=0;i<cs.length;i++)for(let j=i+1;j<cs.length;j++){
    const a=cs[i],b=cs[j];if(a.contains(b)||b.contains(a))continue;
    // 镜像轨的折叠钮与胶囊同处 overflow:hidden 的内部横滑轨，胶囊被裁在轨内；
    // rect 相交不代表可见重叠（轨外边界即裁切边界），按真实裁剪排除。
    const ca=String(a.className||''),cb=String(b.className||'');
    // 镜像折叠钮位于内部横滑轨的裁切边界上，rect 相交不代表可见重叠；
    // 其两态同坐标由 r874 专测，这里排除该颗避免重复口径。
    if(ca.includes('srx-foldbtn')||cb.includes('srx-foldbtn'))continue;
    // r1405：≤560 的筛选/矩阵/概览是固定底部动作条，内容从它下面滚过是
    // 移动端常态（#searchview 已留 64px 底衬）；动作条不是浮层，不参与
    // “控件重叠”口径，否则每个滚动位置都会把行与条判成重叠。
    if(a.closest('#srxMobilebar')||b.closest('#srxMobilebar'))continue;
    const ra=a.getBoundingClientRect(),rb=b.getBoundingClientRect();
    const ox=Math.min(ra.right,rb.right)-Math.max(ra.left,rb.left);
    const oy=Math.min(ra.bottom,rb.bottom)-Math.max(ra.top,rb.top);
    if(ox>3&&oy>3)over.push([String(a.className||a.id||a.tagName).slice(0,20),
      String(b.className||b.id||b.tagName).slice(0,20)]);
  }
  const headings=[...document.querySelectorAll('h1,h2,.uhead,.mon-cardhead,.srx-hero,.srx-listhead')].filter(vis).length;
  return {docOver:document.documentElement.scrollWidth-document.documentElement.clientWidth,
    out:out.slice(0,10), over:over.slice(0,10), headings};
}
"""


def test_pages_no_overflow_overlap_blank(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        bad = []
        for theme in ("light", "dark"):
            for w in (1440, 390):
                pg = b.new_page(viewport={"width": w, "height": 900 if w > 500 else 844},
                                is_mobile=(w <= 600), has_touch=(w <= 600))
                pg.goto(BASE + "/", wait_until="domcontentloaded")
                pg.wait_for_function("typeof S==='object'&&S&&S.users", timeout=25000)
                pg.wait_for_timeout(800)
                pg.evaluate("(t)=>document.documentElement.dataset.theme=t", theme)
                for view, tab, label in VIEWS:
                    if view == "mon":
                        pg.evaluate("()=>switchView('mon')"); pg.wait_for_timeout(200)
                        pg.evaluate("(t)=>showMonTab(t)", tab); pg.wait_for_timeout(950)
                    elif view == "search":
                        pg.evaluate("()=>switchView('search')"); pg.wait_for_timeout(1600)
                    else:
                        pg.evaluate("()=>switchView('cfg')"); pg.wait_for_timeout(250)
                        pg.evaluate("(p)=>showCfgPanel(p)", tab); pg.wait_for_timeout(950)
                    d = pg.evaluate(SNAP)
                    tag = "%s/%d/%s" % (label, w, theme)
                    if d["docOver"] > 1:
                        bad.append(tag + " 横向溢出 " + str(d["docOver"]))
                    if d["out"]:
                        bad.append(tag + " 越界 " + str(d["out"][:3]))
                    if d["over"]:
                        bad.append(tag + " 控件重叠 " + str(d["over"][:3]))
                    if d["headings"] < 1:
                        bad.append(tag + " 无标题，疑似白屏")
                pg.close()
        b.close()
    assert not bad, "全站页面契约: " + "；".join(bad[:12])
