# -*- coding: utf-8 -*-
"""r1101：渠道图标全表面普查。

用户实报「有的地方渠道图标都给我搞没了」。此前矩阵卡 r999 把 img.bic
整颗隐藏；本测试按「可见叶子文本 == 渠道名」逐视图扫描，要求 5 层祖先内
存在可见的官方 `img.bic[data-plat]` 且 naturalWidth>0。
覆盖：监控六个页签、检索台、配置页；390 与 1512 两档。
屏读专用表（.sr-only）不算可见表面。
"""
import os
import sys

import pytest

pytest.importorskip("playwright",
                    reason="渠道图标普查依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None
WIDTHS = [390, 1512]
NAMES = ["携程", "去哪儿", "飞猪", "同程", "途牛",
         "智行 App", "去哪儿 App", "飞猪 App", "携程 App", "同程 App",
         "智行", "携程App", "去哪儿App", "飞猪App", "同程App"]

CENSUS = """(names)=>{
  const vis=e=>{const r=e.getBoundingClientRect();const c=getComputedStyle(e);
    return r.width>1&&r.height>1&&c.visibility!=='hidden'&&c.display!=='none'};
  const leaf=[...document.querySelectorAll('body *')].filter(e=>
    e.children.length===0&&e.textContent&&names.includes(e.textContent.trim())
    &&vis(e)&&!e.closest('.sr-only')
    &&e.getBoundingClientRect().left<innerWidth);
  const out=[];
  for(const e of leaf){
    let a=e, icon=null;
    for(let i=0;i<5&&a;i++){
      const im=a.querySelector&&a.querySelector('img.bic[data-plat]');
      if(im){icon=im;break}
      a=a.parentElement;
    }
    if(!icon || icon.naturalWidth===0 || !vis(icon)){
      let anc=e,ch=[];
      for(let i=0;i<4&&anc;i++){
        ch.push(anc.tagName+'.'+String(anc.className||'')
          .split(' ').slice(0,2).join('.'));
        anc=anc.parentElement;
      }
      out.push({txt:e.textContent.trim(),anc:ch.join(' > ')});
    }
  }
  return out;
}"""


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
    priv = tempfile.mkdtemp(prefix="r1101_")
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


def test_all_visible_channel_names_have_icons(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        bad = []
        for w in WIDTHS:
            pg = b.new_page(viewport={"width": w, "height": 1000},
                            is_mobile=(w <= 600), has_touch=(w <= 600))
            pg.goto(BASE + "/", wait_until="load")
            pg.wait_for_function("typeof S!=='undefined'&&S&&S.users",
                                 timeout=25000)
            pg.wait_for_timeout(1400)
            for tab in ("overview", "specials", "trend", "watch",
                        "details", "health"):
                pg.evaluate("(t)=>{switchView('mon');showMonTab(t)}", tab)
                pg.wait_for_timeout(450)
                miss = pg.evaluate(CENSUS, NAMES)
                if miss:
                    bad.append("%d mon:%s %s" % (w, tab, miss[:4]))
            pg.evaluate("()=>switchView('search')")
            pg.wait_for_timeout(900)
            miss = pg.evaluate(CENSUS, NAMES)
            if miss:
                bad.append("%d search %s" % (w, miss[:4]))
            pg.evaluate("()=>switchView('cfg')")
            pg.wait_for_timeout(1800)
            miss = pg.evaluate(CENSUS, NAMES)
            if miss:
                bad.append("%d cfg %s" % (w, miss[:4]))
            pg.close()
        b.close()
    assert not bad, "渠道图标缺失: " + "；".join(bad)
