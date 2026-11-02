# -*- coding: utf-8 -*-
"""r604：已勾选但本轮零扫描的渠道，健康卡不能让它「整行消失」。

用户要求「可观测性、可识别」。健康卡的行来自日志里**出现过**的渠道
（`core/health.py` 的 `_flush` 只遍历本轮 events）。于是「配了但没跑」的
渠道在卡片上完全不存在——用户勾了它，翻遍健康卡也找不到，读作
「这个渠道不存在」，而不是「它这轮没被扫」。

真实账本里这是常态：`max_concurrency` 限制同轮并发，一轮里往往只有
2–3 家被扫到；没被扫的那几家就这样静默消失了。

修法：后端 `/api/health` 下发 `enabled_platforms`（配置里勾过的并集），
前端在格带下方补一行「未扫描：…（已勾选，但近 24h 无扫描记录）」。
**不能用前端 CFG**：健康页不加载配置表单，`CFG` 此时是 null（实测）。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_backend_ships_enabled_platforms():
    w = _w()
    assert "def _enabled_platforms" in w, "缺少已勾选渠道的收集函数"
    i = w.index("def _enabled_platforms")
    seg = w[i:i + 700]
    assert 'u.get("platforms")' in seg, "没有从 users[].platforms 取并集"
    # 两个分支（demo / 真实）都要下发，只给一边会让另一种跑法缺这条
    assert w.count('["enabled_platforms"] = _enabled_platforms()') == 2, (
        "demo 与真实分支没有都下发 enabled_platforms（实际 %d 处）"
        % w.count('["enabled_platforms"] = _enabled_platforms()'))


def test_frontend_reads_payload_not_cfg():
    """健康页的 CFG 是 null——读它等于这段永不出现（已实证）。"""
    w = _w()
    i = w.index("const _miss=_cfgP.filter")
    seg = w[i - 700:i + 300]
    assert "j.enabled_platforms" in seg, "前端没有读后端下发的清单"
    assert "(CFG||[]).forEach" not in seg, "前端又去读 CFG 了（健康页为 null）"


def test_render_shows_unscanned_channels():
    """真渲染：只扫了 2 家时，另外 3 家必须以「未扫描」出现在卡上。"""
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
                  ctrip:{s:'ok',ok:2,tot:2,note:'',cal:0,detail:2},
                  tuniu:{s:'ok',ok:1,tot:1,note:'',cal:0,detail:1}}}],
                last_seen_at:'2026-10-29 11:40',
                enabled_platforms:['ctrip','tuniu','fliggy','qunar','tongcheng'],
                stats:{ctrip:{ok:2,part:0,fail:0,rate:1.0,cal:0,detail:2,
                  detail_ok:2,cal_only:0,auth:0},
                  tuniu:{ok:1,part:0,fail:0,rate:1.0,cal:0,detail:1,
                  detail_ok:1,cal_only:0,auth:0}},
                by_scope:{}, paths:{}};
              renderHealth(j);
              const e=document.querySelector('#healthcard .hmiss');
              /* 判据用 hbody 的实际内容：健康面板在未激活的 mon 子标签下
                 整块 display:none，量宽度/查祖先只能测出「视图没切过去」，
                 测不到「提示有没有渲染」。渲染产物在 hbody 里就是可见性
                 的证据（面板一显示就带着它）。 */
              const body=document.getElementById('hbody');
              return {n:document.querySelectorAll('#healthcard .hrow').length,
                      miss:e?e.textContent:null,
                      inBody:!!body&&body.innerHTML.indexOf('未扫描')>=0,
                      bodyLen:body?body.innerHTML.length:0}}""")
            b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()

    assert got["n"] == 2, "行数不对（只应渲染出现过的 2 家）：%s" % got
    assert got["miss"], "未扫描的渠道完全没有提示：%s" % got
    for name in ("去哪儿", "飞猪", "同程"):
        assert name in got["miss"], "%s 没出现在未扫描清单：%s" % (name, got)
    assert "已勾选" in got["miss"], "没有说明这些是「已勾选」的渠道"
    assert got["inBody"], "提示没有进入健康面板的渲染产物：%s" % got


def test_render_omits_notice_when_all_channels_scanned():
    """全部渠道都被扫过时不得出现这条提示（避免噪声）。"""
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
                  ctrip:{s:'ok',ok:2,tot:2,note:'',cal:0,detail:2}}}],
                last_seen_at:'2026-10-29 11:40',
                enabled_platforms:['ctrip'],
                stats:{ctrip:{ok:2,part:0,fail:0,rate:1.0,cal:0,detail:2,
                  detail_ok:2,cal_only:0,auth:0}},
                by_scope:{}, paths:{}};
              renderHealth(j);
              return {has:!!document.querySelector('#healthcard .hmiss')}}""")
            b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()
    assert not got["has"], "全部扫描过时仍显示了未扫描提示"
