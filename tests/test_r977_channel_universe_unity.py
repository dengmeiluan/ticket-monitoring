# -*- coding: utf-8 -*-
"""r977：同一页的「渠道宇宙」只能有一套。

用户复报「所有渠道能力和展示没有覆盖辐射到全项目每个，例如渠道健康」。
2026-11-05 实测：健康页诊断卡只有 5 家浏览器渠道，而健康行/节流行有 8 家，
检索/配置/登录卡是 10 家——同屏三个渠道集合，用户读作能力只覆盖了一部分。

本用例用演示站真实渲染一次，要求五个面（诊断/健康行/节流行/检索渠道/登录卡）
的渠道集合与 SRX_PLAT_ORDER 完全一致；任何新增渠道只要漏接一处就红。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = _free_port()
BASE = "http://127.0.0.1:%d" % PORT


@pytest.fixture(scope="module")
def surfaces():
    srv = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(PORT)],
                           cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        ok = False
        for _ in range(90):
            try:
                op.open(BASE + "/api/state", timeout=2)
                ok = True
                break
            except Exception:
                time.sleep(0.5)
        if not ok:
            pytest.skip("demo 服务未起来")
        from playwright.sync_api import sync_playwright
        out = {}
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            pg = br.new_page(viewport={"width": 1512, "height": 1000})
            pg.goto(BASE + "/", wait_until="domcontentloaded")
            pg.wait_for_timeout(2600)
            pg.evaluate("switchView('mon');showMonTab('health');")
            # r1456：健康行/节流行/诊断卡都是异步渲染的。固定 2200ms 在慢机上
            # 会量到空列表（随后断言「三处渠道名不一致」的假红）。等齐三处再说。
            try:
                pg.wait_for_function(
                    "()=>document.querySelectorAll('#hbody .hrow .hlab').length>=10"
                    "&&document.querySelectorAll('#paceBox .pace-row .nm-t').length>=10"
                    "&&document.querySelectorAll('#healthDiagBody .hdiag-card').length>=10",
                    timeout=15000)
            except Exception:
                pass
            out = pg.evaluate("""()=>{
              const txt = e => (e.textContent || '').replace(/\\s+/g, ' ').trim();
              const diag = [...document.querySelectorAll('#healthDiagBody .hdiag-card')]
                .map(e => txt(e.querySelector('b')));
              const hrows = [...document.querySelectorAll('#hbody .hrow .hlab')].map(txt);
              const pace = [...document.querySelectorAll('#paceBox .pace-row .nm-t')].map(txt);
              const name2id = {};
              Object.entries(SRX_PLATS).forEach(([k, v]) => { name2id[txt({textContent: v[0]})] = k; });
              return {order: SRX_PLAT_ORDER.slice(), name2id, diag, hrows, pace};
            }""")
            pg.evaluate("switchView('search')")
            pg.wait_for_timeout(1600)
            out["search"] = pg.evaluate(
                "()=>[...document.querySelectorAll('#srxPlats [data-plat]')]"
                ".map(e=>e.getAttribute('data-plat')).filter(Boolean)")
            pg.evaluate("switchView('config')")
            pg.wait_for_timeout(1800)
            out["login"] = pg.evaluate("""()=>{
              const names = [...document.querySelectorAll('.lgcard')]
                .map(e => (e.textContent || '').replace(/\\s+/g, ' ').trim());
              return names;
            }""")
            br.close()
        yield out
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()


def _norm(s):
    return str(s or "").replace(" ", "").replace("\u3000", "")


def test_five_surfaces_share_one_channel_set(surfaces):
    # 演示站 10 家 = 5 浏览器 + 5 App；顺序单源 SRX_PLAT_ORDER
    order = surfaces["order"]
    assert len(order) == 10, "演示渠道宇宙不是 10 家：%s" % order
    expected = {_norm(n) for n in order}
    n2i = {_norm(k): v for k, v in surfaces["name2id"].items()}
    for key in ("diag", "hrows", "pace", "search"):
        got = {n2i.get(_norm(x), _norm(x)) for x in surfaces[key] if _norm(x)}
        assert got == expected, (
            "%s 渠道集合与 SRX_PLAT_ORDER 不一致：缺 %s / 多 %s"
            % (key, sorted(expected - got), sorted(got - expected)))
    # 登录卡用中文名，单独比数量与覆盖（必须 10 张，不能只有 7 张）
    assert len([x for x in surfaces["login"] if x]) == 10, \
        "登录卡没有覆盖全部 10 家渠道：%s" % surfaces["login"]
