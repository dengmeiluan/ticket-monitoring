# -*- coding: utf-8 -*-
"""r707 全站常驻门禁：不得出现「被拉伸的 flex 列卡里内容贴顶、卡底空一片」。

r697/r698 修的是筛选面板两排；这条把同一缺陷形态做成全站普查，
避免下一个页面再长出「半张卡悬在上面 + 底下一大块空」的廉价观感。

判据（渲染几何）：flex column 容器、高≥90、宽≥120、可见、≥2 个子块，
最后一个子块的底边距容器底边 > 40px 即命中。
负控（见 _scratch/_r708_negctl_tail.py）：注入一张 300px 高、内容 60px 的
同类卡，命中报告 tail=222；基线 6 视图命中 0。
"""
import os
import subprocess
import sys
import threading
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

JS = r"""() => {
  const out=[];
  document.querySelectorAll('body *').forEach(e=>{
    const s=getComputedStyle(e);
    if(s.display!=='flex'||s.flexDirection!=='column')return;
    if(s.visibility==='hidden'||e.offsetHeight<90||e.offsetWidth<120)return;
    const r=e.getBoundingClientRect();
    const kids=[...e.children].filter(k=>k.getBoundingClientRect().height>1);
    if(kids.length<2)return;
    const last=kids[kids.length-1].getBoundingClientRect();
    const tail=r.bottom-last.bottom;
    if(tail<=40)return;
    out.push(((e.id?'#'+e.id:'')+'.'+(e.className||'').toString().split(/\s+/)[0])
             +' h='+Math.round(r.height)+' tail='+Math.round(tail));
  });
  return out;
}"""


def test_no_stretched_card_keeps_its_content_pinned_to_the_top():
    from playwright.sync_api import sync_playwright
    port = 8991
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
            pytest.skip("demo 服务未起来，本门禁无检查对象")
        hits = {}
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            pg = br.new_page(viewport={"width": 1512, "height": 1200})
            pg.goto("http://127.0.0.1:%d/" % port, wait_until="domcontentloaded")
            pg.wait_for_timeout(1600)
            for view, tab in (("mon", "overview"), ("mon", "watch"),
                              ("mon", "specials"), ("mon", "health"),
                              ("search", None), ("cfg", None)):
                pg.evaluate("v=>switchView(v)", view)
                pg.wait_for_timeout(450)
                if tab:
                    pg.evaluate("t=>gotoMonTab(t)", tab)
                    pg.wait_for_timeout(1100)
                rows = pg.evaluate(JS)
                if rows:
                    hits["%s/%s" % (view, tab or "-")] = rows[:5]
            br.close()
        assert not hits, "这些卡被拉伸后内容仍贴顶（底部空一片）：%r" % hits
    finally:
        srv.terminate()
