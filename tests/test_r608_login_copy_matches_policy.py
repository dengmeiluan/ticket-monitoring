# -*- coding: utf-8 -*-
"""r608：登录页的说明文案必须与「全渠道必须登录」政策一致。

用户在 r414 明确要求「抛弃建议登录策略，统一要求各个厂商+渠道都登录」，
`LOGIN_REQ` 表已全部改成「必须登录」。但同一页顶部的常驻说明还写着：

    携程、去哪儿必须登录 · 同程/途牛建议 · 飞猪需淘宝登录（PC/H5 分别登录）

同一屏两种说法：上面说「同程/途牛建议」，下面每个槽位却都标「必须登录」。
用户读到的第一句就是过时策略，直接违背这次的核心要求。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_login_header_says_all_required():
    w = _w()
    assert "同程/途牛建议" not in w, "登录页头部仍写着「同程/途牛建议」（已全改必须登录）"
    # r644 起登录分区补了智行 App，头部改写成「五个浏览器渠道 + 智行 App
    # 都必须登录」——意图（全部必须登录）不变，只是数量跟着真实卡片走。
    assert "都必须登录" in w, "登录页头部没有声明「都必须登录」"
    assert "智行 App" in w, "头部没提到智行 App（统一登录要求漏了一家）"


def test_login_req_table_is_all_required():
    """单一事实源：每个槽位都必须是「必须登录」。"""
    w = _w()
    i = w.index("const reqs={ctrip:")
    seg = w[i:i + 300]
    assert seg.count("'必须登录'") == 6, (
        "LOGIN_REQ 不是 6 个槽位全「必须登录」：%s" % seg[:160])
    for bad in ("建议登录", "可匿名"):
        assert bad not in seg, "LOGIN_REQ 里仍有旧档位：%s" % bad


def test_header_mentions_split_sessions():
    """飞猪 PC/H5 是两套独立会话——这句必须保留，否则用户只登一边。"""
    w = _w()
    # 锚点用头部那句的固定前半（数量与 App 描述会随渠道增减而变）
    i = w.index("都必须登录（入口页可匿名浏览")
    seg = w[i:i + 360]
    assert "PC" in seg and "H5" in seg and "分别登录" in seg, (
        "头部没有说明飞猪两端要分别登录：%s" % seg)


def test_rendered_login_page_has_no_suggestion_wording():
    """真渲染：登录页正文里不得再出现「建议登录/建议重登」这类旧档位词。"""
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
            pg.evaluate("()=>{switchView('cfg')}")
            pg.wait_for_timeout(900)
            pg.evaluate("""()=>{const c=document.querySelector(
              '#cfgnav .cnav[data-p="login"]');if(c)c.click()}""")
            pg.wait_for_timeout(1200)
            got = pg.evaluate("""()=>{
              const panel=document.getElementById('panel-login');
              const txt=panel?panel.innerText.replace(/\s+/g,' '):'';
              /* 要求写在卡片头 .lgreq（半格 145px 放不下逐格重复，
                 见 r608b）；这里判「每张卡都写了必须登录」。 */
              const cards=[...document.querySelectorAll('#loginRows .lgcard')];
              return {n:cards.length,
                      allRequired:cards.every(c=>c.innerText.indexOf('必须登录')>=0),
                      hasReq:cards.every(c=>!!c.querySelector('.lgreq')),
                      suggest:/建议/.test(txt),
                      head:txt.slice(0,60)}}""")
            b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()

    # 卡片数 = REGISTRY 里的采集渠道数（r644 补了智行 App 后是 6 张）。
    # 不写死数字：再加渠道时这条不该红。
    from crawlers import REGISTRY
    assert got["n"] == len(REGISTRY), (
        "卡片数 %s ≠ 采集渠道数 %d" % (got["n"], len(REGISTRY)))
    assert got["hasReq"], "有卡片缺 .lgreq 标记：%s" % got
    assert got["allRequired"], "有卡片没写「必须登录」：%s" % got
    assert not got["suggest"], "登录页仍出现「建议」类旧档位词：%s" % got


def test_dual_slot_reuses_the_shared_slot_body():
    """飞猪双端不得自带一套 DOM——那套曾把「必须登录」漏掉（r608）。

    实测：同一页四家写「必须登录」，飞猪两端只有「PC 未登录 / H5 未登录」，
    读者会以为飞猪不需要登录。要求是两端各调一次 `slotBody`。
    """
    w = _w()
    i = w.index("const inner=dual")
    seg = w[i:i + 900]
    # 半格走同一份 slotBody 的紧凑模式：仍复用同一函数（不会再次丢掉
    # requirement），只是省掉重复的账号段以保住五行等高（r608b）。
    assert "[pc,h5].filter(Boolean).map(s=>slotBody(s,1))" in seg, (
        "双端分支没有复用 slotBody（会再次丢掉 requirement）")
    assert "lgShortStatus(pc)" not in seg, (
        "双端分支仍在用自带的状态渲染（不走统一口径）")


def test_rendered_fliggy_slots_say_required():
    """真渲染：六个槽位（含飞猪 PC/H5）都必须出现「必须登录」。"""
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
            pg.evaluate("()=>{switchView('cfg')}")
            pg.wait_for_timeout(900)
            pg.evaluate("""()=>{const c=document.querySelector(
              '#cfgnav .cnav[data-p="login"]');if(c)c.click()}""")
            pg.wait_for_timeout(1200)
            got = pg.evaluate("""()=>{
              /* 要求写在**卡片头**（.lgreq），不在每个格子里：
                 半格只有 145px，逐格重复会把卡撑高（r608b 实测 69 vs 52）。
                 所以判据是「每张卡都写了必须登录」。 */
              const cards=[...document.querySelectorAll('#loginRows .lgcard')];
              const txt=cards.map(c=>c.innerText.replace(/\s+/g,' '));
              return {n:cards.length, slots:txt,
                missing:txt.filter(s=>s.indexOf('必须登录')<0)}}""")
            b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()

    from crawlers import REGISTRY
    assert got["n"] == len(REGISTRY), (
        "卡片数 %s ≠ 采集渠道数 %d（飞猪内含 PC/H5 两格）"
        % (got["n"], len(REGISTRY)))
    assert not got["missing"], "这些槽位没有标「必须登录」：%s" % got["missing"]
