# -*- coding: utf-8 -*-
"""r711 渠道计数分母必须等于真正渲染出来的渠道数。

用户实测：两家 App 接进来后，配置页「监控渠道」分区实际渲染 7 个 chip，
卡头却还写着「N / 5 渠道」；关注台的「渠道覆盖」KPI 同样写死 /5，而同一
张卡里每条关注自己的脚注写的是「3/7 渠道有价」。同一屏两种分母，读数既
超界（7/5）又自相矛盾。

三条判据，都必须真渲染：
1. 配置页 B 分区：分母 == 该分区内 .pch 个数（5 浏览器 + 2 App = 7）；
2. 勾选 App 渠道后：分子真的 +1，分母不变，不出现「7 / 5」这种超界读数；
3. 关注台渠道覆盖：分母来自关注自身的 channels（与脚注同源），不是常量 5。

判据取 rendered DOM，不取源码字符串——写死 5 的源码在替换成函数后
`/ 5` 仍会出现在注释与文档里，字符串扫描必然误判。
"""
import os
import sys

import pytest

pytest.importorskip("playwright",
                    reason="行为钉依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def srv():
    import subprocess
    import tempfile
    import time
    import urllib.request
    from playwright.sync_api import sync_playwright

    global BASE
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    logf = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    priv = tempfile.mkdtemp(prefix="r711_")
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
        try:
            proc.kill()
        except Exception:
            pass
        pytest.fail("demo 启动失败（两次新端口重试后）")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    logf.close()


@pytest.fixture(scope="module")
def page(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        pg.goto(BASE + "/", wait_until="load")
        pg.wait_for_timeout(1500)
        yield pg
        b.close()


def _to_cfg(pg):
    pg.evaluate("()=>{try{go('cfg')}catch(e){location.hash='#cfg'}}")
    pg.wait_for_timeout(1200)


def test_config_bhead_denominator_matches_rendered_chips(page):
    """分母 == 该分区真正渲染的 chip 数（不是常量 5）。"""
    _to_cfg(page)
    out = page.evaluate("""(() => {
      const sec = document.querySelector('#cfgform .grouplab[data-sec="B"]');
      const sum = sec ? sec.querySelector('.gsum').textContent.trim() : '';
      const chips = document.querySelectorAll('#cfgform .pch').length;
      const appChips = document.querySelectorAll(
        '#cfgform .pch[class*="p-app_"]').length;
      return {sum, chips, appChips};
    })()""")
    assert out["chips"] >= 7, out
    assert out["appChips"] >= 2, (
        "两家 App 渠道没有渲染成 chip：配置页根本勾不到它们", out)
    assert out["sum"].endswith("/ %d 渠道" % out["chips"]), (
        "B 分区卡头分母没跟渲染出的 chip 数对齐（出现「N / 5」超界读数）：%r"
        % out["sum"], out)


def test_toggling_app_chip_increments_numerator_only(page):
    """勾选一家 App：分子 +1、分母不变，绝不出现分子 > 分母。"""
    _to_cfg(page)
    out = page.evaluate("""(() => {
      const sum = () => document.querySelector(
        '#cfgform .grouplab[data-sec="B"] .gsum').textContent.trim();
      const chips = document.querySelectorAll('#cfgform .pch').length;
      const chip = document.querySelector('#cfgform .pch.p-app_zhixing')
                 || document.querySelector('#cfgform .pch[class*="p-app_"]');
      const before = sum(), on0 = chip.classList.contains('on');
      chip.click();
      const mid = sum();
      chip.click();
      return {chips, before, on0, mid, after: sum(),
              n: (typeof CFG !== 'undefined' && CFG[0].platforms || []).length};
    })()""")
    total = out["chips"]
    before_n = int(out["before"].split("/")[0].strip())
    mid_n = int(out["mid"].split("/")[0].strip())
    assert out["mid"].endswith("/ %d 渠道" % total), out
    if not out["on0"]:
        assert mid_n == before_n + 1, (
            "勾上 App 渠道后分子没动，说明这个 chip 没接进 platforms 模型", out)
    else:
        assert mid_n == before_n - 1, out
    assert mid_n <= total, ("分子超界：分母仍是写死的旧值", out)
    assert out["after"] == out["before"], ("再点一次没回到原值（非幂等）", out)


def test_watch_coverage_denominator_from_watch_channels(page):
    """关注台「渠道覆盖」分母来自关注自身 channels，与脚注同源。"""
    page.evaluate("switchView('mon');showMonTab('watch')")
    page.wait_for_timeout(900)
    out = page.evaluate("""(() => {
      const kpis = [...document.querySelectorAll('#wsKpis .ws-kpi')];
      const k = kpis.find(e => (e.querySelector('.k')||{}).textContent === '渠道覆盖');
      const foots = [...document.querySelectorAll('.monwatch-foot span')]
        .map(e => (e.textContent||'').trim())
        .filter(t => /渠道有价/.test(t));
      const dens = foots.map(t => {
        const m = t.match(/(\\d+)\\s*\\/\\s*(\\d+)\\s*渠道有价/);
        return m ? Number(m[2]) : null;
      }).filter(v => v != null);
      return {unit: k ? k.querySelector('.v span').textContent.trim() : null,
              dens, foots: foots.slice(0, 3)};
    })()""")
    if not out["dens"]:
        pytest.skip("演示态无关注航班，脚注分母无从取（不判失败）")
    expect = "/%d" % max(out["dens"])
    assert out["unit"] == expect, (
        "KPI 分母与每条关注脚注分母不同源（README：同行数字须同源）：%r vs %r"
        % (out["unit"], out["foots"]))
