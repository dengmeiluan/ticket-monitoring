# -*- coding: utf-8 -*-
"""r1505：配置页左缘文字轨统一门禁 + 负控。

背景：r1503 为策略控制补的 `.subsec{padding-left:22px}` 是全局规则，
把「用户与航线」卡里已在 16px 内衬中的分区小标题又推深 22px（实测
345 vs 字段 329）；统计条/范围工具条也分别停在 320/307。用户读作
「同一张卡里三条左边线」。

本门禁只测真实渲染：
1. 用户卡：卡头文字 / 统计条首字 / 范围工具条首字 / 分区小标题 /
   设置行标签，5 档（1440/1024/768/390/320）同 x，极差 ≤1px。
2. 全局参数：所有可见分区小标题（含嵌套「设备身份」）与参数标签同 x。
3. 登录卡：10 行渠道图标与卡头图标同 x；窄档同理。
4. 渠道入口：列头「渠道」与行首图标同 x（桌面）。
5. 负控：注入旧 r1503 的 22px 小标题 / 13px 统计条，必须使用户卡
   左缘判据失败；注入 12px 登录行 / 2px 列头，必须使图形轨判据失败。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

pytest.importorskip("playwright", reason="渲染门禁依赖 playwright")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None

MEASURE = r"""
() => {
  const tx = (el) => {
    if (!el) return null;
    const n = el.firstChild;
    if (!n || n.nodeType !== 3) return null;
    const r = document.createRange();
    r.setStart(n, 0);
    r.setEnd(n, Math.min(1, n.length));
    return +r.getBoundingClientRect().x.toFixed(1);
  };
  const bx = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return +r.x.toFixed(1);
  };
  const out = {};
  out.zh = tx(document.querySelector('#sec-users .uhead .zh'));
  out.stat = tx(document.querySelector('#cfgOverview .cfgstat .sl'));
  out.tool = tx(document.querySelector('#cfgform .cfgtoolbar .cb-lab'));
  out.sub = tx(document.querySelector('#cfgform .ucbody .subsec'));
  out.slab = tx(document.querySelector('#cfgform .ucbody .srow .slab b'));
  out.docDx = document.documentElement.scrollWidth - document.documentElement.clientWidth;
  return out;
}
"""

GLOBALS = r"""
() => {
  const tx = (el) => {
    if (!el) return null;
    const n = el.firstChild;
    if (!n || n.nodeType !== 3) return null;
    const r = document.createRange();
    r.setStart(n, 0);
    r.setEnd(n, Math.min(1, n.length));
    return +r.getBoundingClientRect().x.toFixed(1);
  };
  const visible = (el) => el && el.getBoundingClientRect().width > 0;
  const subs = [...document.querySelectorAll('#cfgglobals .subsec')]
    .filter(visible).map(el => ({t: (el.textContent || '').trim().slice(0, 16), x: tx(el)}));
  const lab = document.querySelector('#cfgglobals .glab');
  return {subs, lab: tx(lab), docDx: document.documentElement.scrollWidth - document.documentElement.clientWidth};
}
"""

LOGIN = r"""
() => {
  const tx = (el) => {
    if (!el) return null;
    const n = el.firstChild;
    if (!n || n.nodeType !== 3) return null;
    const r = document.createRange();
    r.setStart(n, 0);
    r.setEnd(n, Math.min(1, n.length));
    return +r.getBoundingClientRect().x.toFixed(1);
  };
  const bx = (el) => el ? +el.getBoundingClientRect().x.toFixed(1) : null;
  const rows = [...document.querySelectorAll('#loginRows .lgcard')];
  return {
    headIcon: bx(document.querySelector('#sec-login .uhead .secicon')),
    rowIcons: rows.map(r => bx(r.querySelector('.bic'))),
    rowBoxes: rows.map(r => bx(r)),
    chHead: tx(document.querySelector('#cfgChannelLinksBox .chboard-head span')),
    chHeadVisible: !!document.querySelector('#cfgChannelLinksBox .chboard-head span') &&
      document.querySelector('#cfgChannelLinksBox .chboard-head span').getBoundingClientRect().width > 0,
    chIcon: bx(document.querySelector('#cfgChannelLinksBox .chband .chband-name .bic')),
    docDx: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  };
}
"""


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def srv():
    global BASE
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失")
    port = free_port()
    BASE = "http://127.0.0.1:%d" % port
    proc = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(port)],
                            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(100):
        try:
            op.open(BASE + "/api/state", timeout=2)
            break
        except Exception:
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.fail("demo 未启动")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


@pytest.fixture
def browser(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def open_cfg(browser, width):
    ctx = browser.new_context(viewport={"width": width, "height": 1000})
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="networkidle")
    page.evaluate("() => switchView('cfg')")
    page.wait_for_function("() => document.querySelector('#cfgOverview .cfgstat')")
    page.wait_for_timeout(500)
    return ctx, page


@pytest.mark.parametrize("width", [1440, 1024, 768, 390, 320])
def test_users_card_one_text_rail(browser, width):
    ctx, page = open_cfg(browser, width)
    page.evaluate("() => showCfgPanel('users')")
    page.wait_for_timeout(500)
    m = page.evaluate(MEASURE)
    page.close()
    ctx.close()

    vals = [m["zh"], m["stat"], m["tool"], m["sub"], m["slab"]]
    assert all(v is not None for v in vals), (width, m)
    assert max(vals) - min(vals) <= 1, (width, m)
    assert m["docDx"] <= 0, (width, m)


@pytest.mark.parametrize("width", [1440, 390])
def test_globals_subsecs_one_text_rail(browser, width):
    ctx, page = open_cfg(browser, width)
    page.evaluate("() => showCfgPanel('globals')")
    page.wait_for_timeout(600)
    m = page.evaluate(GLOBALS)
    page.close()
    ctx.close()

    assert m["subs"], (width, m)
    xs = [s["x"] for s in m["subs"] if s["x"] is not None]
    assert xs and max(xs) - min(xs) <= 1, (width, m)
    assert abs(m["lab"] - xs[0]) <= 1, (width, m)
    assert m["docDx"] <= 0, (width, m)


@pytest.mark.parametrize("width", [1440, 390])
def test_login_and_channel_rows_graphic_rail(browser, width):
    ctx, page = open_cfg(browser, width)
    page.evaluate("() => showCfgPanel('login')")
    page.wait_for_timeout(700)
    page.wait_for_selector("#loginRows .lgcard")
    m = page.evaluate(LOGIN)
    page.close()
    ctx.close()

    assert m["rowIcons"], (width, m)
    assert all(abs(icon - box) <= 1 for icon, box in zip(m["rowIcons"], m["rowBoxes"])), (width, m)
    assert abs(m["rowIcons"][0] - m["headIcon"]) <= 1, (width, m)
    if m["chHeadVisible"]:
        assert abs(m["chHead"] - m["chIcon"]) <= 1, (width, m)
    assert m["docDx"] <= 0, (width, m)


def test_negative_controls(browser):
    ctx, page = open_cfg(browser, 1440)
    page.evaluate("() => showCfgPanel('users')")
    page.wait_for_timeout(500)
    page.add_style_tag(content=(
        "#cfgview .ucbody .subsec{padding-left:22px!important}"
        "#cfgview #cfgOverview>.cfgstat:nth-child(odd){padding-left:13px!important}"
    ))
    page.wait_for_timeout(150)
    bad = page.evaluate(MEASURE)
    vals = [bad["zh"], bad["stat"], bad["tool"], bad["sub"], bad["slab"]]
    assert max(vals) - min(vals) >= 10, bad

    page.evaluate("() => showCfgPanel('login')")
    page.wait_for_timeout(700)
    page.add_style_tag(content=(
        "#cfgview #loginRows .lgcard{padding-left:12px!important}"
        "#cfgview #cfgChannelLinksBox .chboard-head>span:first-child{padding-left:2px!important}"
    ))
    page.wait_for_timeout(150)
    login_bad = page.evaluate(LOGIN)
    first_gap = abs(login_bad["rowIcons"][0] - login_bad["headIcon"])
    assert first_gap >= 8, login_bad
    assert abs(login_bad["chHead"] - login_bad["chIcon"]) >= 8, login_bad
    page.close()
    ctx.close()
