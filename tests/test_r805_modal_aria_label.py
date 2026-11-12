# -*- coding: utf-8 -*-
"""r805g：共用 #lgModal 的可读名称必须由开窗方写，且随渠道切换。

用户原话：「问题内嵌画面切换app的时候没有正确切换」。画面/标题的切换
r803 已修（data-kind 归属 + 整窗重建），但 **aria-label** 漏了：
静态 HTML 写死「飞猪双端登录」，`appLoginOpen` 整窗重建 innerHTML 却
不动属性，于是从携程卡片切到智行 App 后，屏幕阅读器把智行的画面念成
飞猪。这类缺陷用肉眼截图看不出来，只能在属性层判。

判据：
  1. 源码里 `appLoginOpen` 与 `lgOpenFliggy` 都必须写 aria-label；
  2. 真渲染：连开两个 App 渠道，可读名称要跟着渠道名走（不是飞猪）。
"""
import io
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fn_body(src, name):
    i = src.index("function %s(" % name)
    j = src.index("\nfunction ", i + 1)
    return src[i:j]


def test_every_modal_opener_sets_aria_label():
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    # r1063 T195：双端开窗已泛化为 lgOpenDual(plat)，aria-label 写在它里面；
    # 老入口 lgOpenFliggy 必须仍转发过来（否则有两条开窗路径、只改一条就漏）。
    body = _fn_body(src, "lgOpenDual")
    assert re.search(r"setAttribute\(\s*'aria-label'", body), (
        "lgOpenDual 没写 aria-label：共用容器的可读名称会停在上一个开窗方")
    assert "LG_DUAL" in body, (
        "lgOpenDual 的 aria-label 必须按渠道取（写死一家=切渠道后念错）")
    assert "lgOpenDual('fliggy')" in _fn_body(src, "lgOpenFliggy"), (
        "lgOpenFliggy 应转发到 lgOpenDual，避免两条开窗路径")
    app = _fn_body(src, "appLoginOpen")
    assert re.search(r"setAttribute\(\s*'aria-label'", app), (
        "appLoginOpen 没写 aria-label")
    # App 侧必须是「跟着渠道名」，不能写死一家
    app = _fn_body(src, "appLoginOpen")
    m = re.search(r"setAttribute\(\s*'aria-label'\s*,\s*([^\n;]+)\)", app)
    assert m, "appLoginOpen 没有写 aria-label 的 setAttribute 语句"
    assert "appPlatName(plat)" in m.group(1), (
        "appLoginOpen 的 aria-label 没跟着渠道名走（写死一家=切 App 后念错）：%s"
        % m.group(1).strip())


def test_modal_label_follows_channel_on_render():
    """真渲染：连开两个 App，可读名称要变。"""
    from playwright.sync_api import sync_playwright

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    srv = subprocess.Popen(
        [sys.executable, "webui.py", "--demo", "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, env=env)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = "http://127.0.0.1:%d" % port
    try:
        for _ in range(160):
            try:
                op.open(base + "/api/state", timeout=1)
                break
            except Exception:
                time.sleep(0.25)
        else:
            pytest.skip("演示服务未在期限内起来")
        with sync_playwright() as pw:
            if not os.path.exists(pw.chromium.executable_path):
                pytest.skip("chromium 二进制缺失")
            b = pw.chromium.launch()
            try:
                pg = b.new_page(viewport={"width": 1440, "height": 1100})
                pg.set_default_timeout(25000)
                pg.goto(base)
                pg.wait_for_function(
                    "()=>typeof S!=='undefined'&&S&&S.users", timeout=30000)
                pg.evaluate("""async()=>{
                  switchView('cfg');await new Promise(r=>setTimeout(r,800));
                  showCfgPanel('login');
                  await new Promise(r=>setTimeout(r,2500));
                }""")
                labels = pg.evaluate("""()=>{
                  const out={};
                  const cards=[...document.querySelectorAll(
                    '#panel-login .lgcard')];
                  for(const p of ['app_zhixing','app_qunar']){
                    const c=cards.find(x=>new RegExp(
                      p==='app_zhixing'?'智行':'去哪儿 App').test(x.innerText||''));
                    if(!c){out[p]='NO-CARD';continue}
                    const btn=[...c.querySelectorAll('button')][0];
                    if(!btn){out[p]='NO-BTN';continue}
                    btn.click();
                    const m=document.getElementById('lgModal');
                    /* 标题与 aria-label 都必须在**这次**点击之后读，
                       不能循环完了再读（读到的是最后开的那家） */
                    const h=(m.querySelector('.lgmodal-h b')
                             ||{innerText:''}).innerText;
                    out[p]={open:m.classList.contains('open'),
                            kind:m.dataset.kind||'',
                            aria:m.getAttribute('aria-label')||'',
                            head:h};
                  }
                  return out;
                }""")
                assert labels["app_zhixing"]["open"], "智行卡点了没开窗"
                assert "智行" in labels["app_zhixing"]["aria"], (
                    "打开智行后可读名称仍是 %r（屏幕阅读器念错渠道）"
                    % labels["app_zhixing"]["aria"])
                assert "智行" in labels["app_zhixing"]["head"], (
                    "标题没跟着切到智行：%r" % labels["app_zhixing"]["head"])
                assert "去哪儿" in labels["app_qunar"]["aria"], (
                    "从智行切到去哪儿后，可读名称仍是 %r"
                    % labels["app_qunar"]["aria"])
                assert "去哪儿" in labels["app_qunar"]["head"], (
                    "切到去哪儿后标题仍是 %r" % labels["app_qunar"]["head"])
                assert labels["app_qunar"]["kind"] == "app"
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()
