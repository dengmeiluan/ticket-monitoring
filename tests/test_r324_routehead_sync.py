# -*- coding: utf-8 -*-
"""r324 航线卡头部随行刷新钉（用户实报 bug：选择航线渲染错误）：

- addRoute 种子头（SHA上海→HAK海口）与面板新选城市（北京/长沙）
  同卡劈叉——setRoute 只改模型从不触 UI，卡头航线身份停在新卡
  种子态；钉=城市输入 change（cityPanelPick 同链）后 rtcode/名/
  摘要三件随行，城市名精确命中 CITY 时码随名同步（与 saveCfg
  名归一+码映射同语义）；
- 阈值变更的头部摘要随行（同一劈叉族的 muted 行）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r324_routehead_sync.py -q
"""
import os
import sys

import pytest

pytest.importorskip("playwright",
                    reason="行为钉依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = None
BASE = None


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_up(proc):
    import time
    import urllib.request
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(40):
        if proc.poll() is not None:
            return False
        try:
            op.open(BASE + "/api/state", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


@pytest.fixture(scope="module")
def srv():
    global PORT, BASE
    import subprocess
    import tempfile
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    logf = tempfile.TemporaryFile(mode="w+", encoding="utf-8",
                                  errors="replace")
    import tempfile as _tf
    priv_tmp = _tf.mkdtemp(prefix="r324rh_")
    env = dict(os.environ, TEMP=priv_tmp, TMP=priv_tmp,
               TMPDIR=priv_tmp)
    proc = None
    for _attempt in (1, 2):
        PORT = _free_port()
        BASE = "http://127.0.0.1:%d" % PORT
        proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
             "--port", str(PORT)],
            cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT, env=env)
        if _wait_up(proc):
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


@pytest.fixture()
def page(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        pg = ctx.new_page()
        yield pg
        browser.close()


def _to_cfg(page):
    page.goto(BASE + "/")
    page.wait_for_function("typeof S !== 'undefined' && S && S.users")
    page.evaluate("switchView('cfg')")
    page.wait_for_function("typeof CFG !== 'undefined' && CFG && CFG.length")
    page.wait_for_timeout(400)


_ADD = """
(() => {
  addRoute(0);
  return CFG[0].routes.length - 1;   /* 新卡索引 J */
})()
"""

_EDIT = """
((J) => {
  const rl = document.querySelector('.rline[data-rk="0:' + J + '"]');
  const fin = rl.querySelector('input[onchange*="from_name"]');
  const tin = rl.querySelector('input[onchange*="to_name"]');
  fin.value = '北京'; fin.dispatchEvent(new Event('change', {bubbles: true}));
  tin.value = '长沙'; tin.dispatchEvent(new Event('change', {bubbles: true}));
  const head = rl.querySelector('.rhead');
  return {rtcode: head.querySelector('.rtcode').textContent,
          names: head.querySelector('b').textContent,
          modelFrom: CFG[0].routes[J].from,
          modelTo: CFG[0].routes[J].to};
}) """

_THRESH = """
((J) => {
  const rl = document.querySelector('.rline[data-rk="0:' + J + '"]');
  const inp = rl.querySelector('input[onchange*="alert_direct"]');
  inp.value = '1234';
  inp.dispatchEvent(new Event('change', {bubbles: true}));
  return document.querySelector(
    '.rline[data-rk="0:' + J + '"] .rhead .muted').textContent;
}) """

_CLEAN = """
((J) => { CFG[0].routes.splice(J, 1); buildForm(); }) """


def test_route_head_follows_city_edit(page):
    """城市编辑后卡头三件（码/名/身份）随行，不再停在新卡种子态。"""
    _to_cfg(page)
    J = page.evaluate(_ADD)
    try:
        seed = page.evaluate(
            """((J) => { const h = document.querySelector(
                 '.rline[data-rk="0:' + J + '"] .rhead');
               return {rtcode: h.querySelector('.rtcode').textContent,
                       names: h.querySelector('b').textContent}; }) """,
            J)
        assert seed["rtcode"] == "SHA→HAK" and \
            "上海" in seed["names"], seed   # 种子态基线（实现前提在场）
        out = page.evaluate(_EDIT, J)
        assert out["names"] == "北京 → 长沙", out
        assert out["rtcode"] == "BJS→CSX", out   # CITY['北京']='BJS'
        assert out["modelFrom"] == "BJS" and out["modelTo"] == "CSX", out
    finally:
        page.evaluate(_CLEAN, J)


def test_route_head_summary_follows_threshold(page):
    """阈值变更头部摘要随行（muted 行同族劈叉）。"""
    _to_cfg(page)
    J = page.evaluate(_ADD)
    try:
        head0 = page.evaluate(
            """((J) => document.querySelector(
                 '.rline[data-rk="0:' + J + '"] .rhead .muted')
               .textContent) """, J)
        assert "直飞≤￥1234" not in head0, head0
        out = page.evaluate(_THRESH, J)
        assert "直飞≤￥1234" in out, (head0, out)
    finally:
        page.evaluate(_CLEAN, J)


def test_source_pins_route_head_sync():
    """源码钉：syncRouteHead 单源 + setRoute 接线 + 摘要单源共用。"""
    src = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert "function syncRouteHead" in src, "头部随行刷新单源应在案"
    assert src.count("syncRouteHead(i,j)") >= 1, "setRoute 应接线"
    assert "_rsum(r)" in src, "头部摘要应走单源（模板与随行同源）"
