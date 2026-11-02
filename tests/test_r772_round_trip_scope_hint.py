# -*- coding: utf-8 -*-
"""r772：往返 chip 的提示必须覆盖「只在一端可用」的渠道（真浏览器）。

背景：矩阵的 `round_trip` 只有一格，但实际能力是分端面的——
  * 飞猪只在**国际**低价日历取到往返总价，国内只有单程；
  * 途牛只在**国内**接口取到往返总价（r769），国际仍是 unsupported。
用户在国内航线上勾了往返、只看到飞猪空结果，会把「口径不适用」读成
「功能坏了」。所以 chip 的 title 除了列「谁没有」，还要说清「可用范围」。

判据（渲染层，全部走真浏览器）：
  1. chip title 含「暂无往返数据」；国内航线只剩飞猪不覆盖，携程/同程/
     去哪儿不得再出现在「暂无」名单；
  2. chip title 含「可用范围」，点名「携程」「飞猪仅国际」「途牛仅国内」
     「同程仅国内」「去哪儿仅国内」；
  3. 无 pageerror。

时序说明：`loadChannelDims()` 末尾必须重绘一次表单（实测：去掉那一行，
本用例读到的 title 里两段都没有）。用例先加载数据、再清空并切页、
最后重新加载——这样首轮 buildForm 一定发生在「没有数据」时，只有靠
末尾重绘才可能读到提示；把它去掉则本用例变红（已做负控）。
"""
import io
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
READ_TITLES = """() => Array.from(document.querySelectorAll(
  '[onclick*=toggleRT]')).map(e=>{
    const rk = e.closest('.rline') ? e.closest('.rline').dataset.rk : '';
    let intl = false;
    try {
      const ij = (rk||'').split(':').map(Number);
      const r = (typeof CFG!=='undefined' && CFG[ij[0]]
        && CFG[ij[0]].routes) ? CFG[ij[0]].routes[ij[1]] : null;
      intl = !!(r && typeof isIntlCode==='function'
        && isIntlCode(r.to || ''));
    } catch(_){}
    return {title:e.getAttribute('title')||'', intl:intl};
  })"""


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _start():
    priv = tempfile.mkdtemp(prefix="r772_")
    env = dict(os.environ, TEMP=priv, TMP=priv, TMPDIR=priv,
               PYTHONIOENCODING="utf-8")
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
         "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env=env)
    base = "http://127.0.0.1:%d" % port
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(80):
        try:
            op.open(base + "/api/state", timeout=2)
            break
        except Exception:
            time.sleep(0.5)
    return proc, base


@pytest.fixture(scope="module")
def titles():
    sync_playwright = pytest.importorskip(
        "playwright.sync_api").sync_playwright
    proc, base = _start()
    try:
        with sync_playwright() as p:
            br = p.chromium.launch(headless=True, args=["--no-sandbox"])
            pg = br.new_page(viewport={"width": 1440, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/", wait_until="load")
            pg.wait_for_function(
                "typeof switchView==='function'", timeout=20000)
            for _ in range(60):
                if pg.evaluate("() => !!DIMS_DATA"):
                    break
                pg.wait_for_timeout(250)
            pg.evaluate("() => { DIMS_DATA=null; }")
            pg.evaluate("() => switchView('cfg')")
            pg.evaluate("() => loadChannelDims()")
            for _ in range(60):
                if pg.evaluate("() => !!DIMS_DATA"):
                    break
                pg.wait_for_timeout(250)
            pg.wait_for_timeout(1500)
            out = pg.evaluate(READ_TITLES)
            br.close()
            return {"titles": out, "errs": errs}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


def test_chip_lists_channels_without_round_trip(titles):
    all_titles = [x["title"] for x in titles["titles"]]
    j = "\n".join(all_titles)
    assert all_titles, "找不到可点击的往返 chip"
    assert "暂无往返数据" in j, "chip 没说明哪些渠道没有往返"
    assert "飞猪" in j, "国内航线上飞猪只覆盖国际，应在「暂无」名单里"
    # 国际航线上「同程/去哪儿/途牛仅国内」本来就该出现在「暂无」名单；
    # 本判据只针对国内航线。
    for item in titles["titles"]:
        if item["intl"]:
            continue
        head = item["title"].split("可用范围")[0]
        if "暂无往返数据" not in head:
            continue
        part = head.split("暂无往返数据", 1)[1].split("｜")[0].lstrip("：")
        names = {x.strip() for x in part.split("、") if x.strip()}
        for name in ("携程", "同程", "去哪儿"):
            assert name not in names, (
                "%s 国内往返已接通，不得再出现在「暂无」名单：%s"
                % (name, names))


def test_chip_states_the_scope_of_each_supported_channel(titles):
    """只在单端可用的渠道必须写清范围，否则空结果会被读成功能坏了。"""
    j = "\n".join(x["title"] for x in titles["titles"])
    assert "可用范围" in j, "chip 没说清往返的可用范围"
    assert "携程" in j, "携程国内/国际往返已接通，应出现在可用范围"
    assert "飞猪仅国际" in j, "没说明飞猪的往返只在 international"
    assert "途牛仅国内" not in j, (
        "途牛国际往返 2026-11-03 已接通，不应再写「途牛仅国内」")
    assert "同程" in j, "同程国内/国际往返均已接通，应出现在可用范围"
    assert "同程仅国内" not in j, (
        "同程国际往返 2026-11-03 已接通，不应再写「同程仅国内」")
    assert "去哪儿仅国内" in j, "没说明去哪儿网页的往返只在国内"


def test_no_page_error(titles):
    assert not titles["errs"], titles["errs"][:3]
