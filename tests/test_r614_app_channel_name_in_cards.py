# -*- coding: utf-8 -*-
"""r614：App 渠道在两处渠道名表里都要有中文名。

`APP_PLAT_NAME` 早就存在（登录卡在用），但健康卡与节流面板各有一张自己的
`CN` 表，只列了 5 家浏览器渠道。实测智行 App 在健康卡里被渲染成
**`aapp_zhixing`**——「首字兜底」的 `a` 拼上原始 id，用户完全读不懂。

修法：两张表都以 `Object.assign({…5 家…}, APP_PLAT_NAME)` 生成，
名字回到单一事实源。这样将来再加 App 渠道只改 `APP_PLAT_NAME` 一处。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_both_cn_tables_merge_app_plat_name():
    w = _w()
    assert w.count("Object.assign({") >= 2
    assert "'qunar':'去哪儿','fliggy':'飞猪','ctrip':'携程'" in w
    # 两张表都必须并入 APP_PLAT_NAME（只并一张，另一张仍显示原始 id）
    # 至少 2 处（健康卡 + 节流面板）。r615 又并了第三张（PCN），
    # 所以这里写 >= 而非 ==（写死数量会在新增名表时假红）。
    assert w.count("(typeof APP_PLAT_NAME!=='undefined')?APP_PLAT_NAME:{}") >= 2, (
        "健康卡与节流面板的名字表没有都并入 APP_PLAT_NAME（实际 %d 处）"
        % w.count("(typeof APP_PLAT_NAME!=='undefined')?APP_PLAT_NAME:{}"))


def test_app_plat_name_is_the_single_source():
    w = _w()
    i = w.index("const APP_PLAT_NAME=")
    seg = w[i:i + 120]
    assert "app_zhixing" in seg and "智行" in seg, seg


def test_health_card_shows_app_chinese_name():
    """真渲染：健康卡里的 app_zhixing 不能露出原始 id。"""
    import json
    import socket
    import subprocess
    import sys
    import time
    import urllib.request

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
    try:
        t0 = time.time()
        while time.time() - t0 < 60:
            try:
                op.open(base + "/api/state", timeout=2)
                break
            except Exception:
                time.sleep(0.3)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            import os as _os
            if not _os.path.exists(p.chromium.executable_path):
                import pytest
                pytest.skip("chromium 二进制缺失")
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1400, "height": 900})
            pg.goto(base)
            pg.wait_for_function("typeof S!=='undefined'&&S&&S.users",
                                 timeout=25000)
            got = pg.evaluate("""()=>{
              const j={rounds:[{ts:'12:00',plats:{
                  app_zhixing:{s:'ok',ok:2,tot:2,note:'',cal:0,detail:2}}}],
                last_seen_at:'2026-10-30 10:00',
                enabled_platforms:['app_zhixing'],
                stats:{app_zhixing:{ok:2,part:0,fail:0,rate:1.0,cal:0,
                  detail:2,detail_ok:2,cal_only:0,auth:0}},
                by_scope:{}, paths:{}};
              renderHealth(j);
              const r=document.querySelector('#healthcard .hlab');
              return {label:r?r.innerText.trim():null,
                      raw:(r?r.innerText:'').indexOf('app_zhixing')>=0}}""")
            b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()

    assert got["label"], "健康卡没有渲染出渠道行：%s" % got
    assert not got["raw"], "健康卡露出了原始渠道 id：%s" % got
    assert "智行" in got["label"], "健康卡没有显示中文名：%s" % got
