# -*- coding: utf-8 -*-
"""r320 机场筛选钉（明细筛选族机场维度补全）：

- chips 双组（出发/到达），按机场三字码聚合（渠道名形态漂移免疫）、
  显示归一短名（「虹桥国际机场」→「虹桥」）；
- 谓词空集=全部（chips 族同语义）；FLT 快照持久化随同排筛选族；
- 克制律显隐：维度在当前数据有区分度才现身。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r320_airportflt.py -q
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
    priv_tmp = _tf.mkdtemp(prefix="r320af_")
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


def _to_details(page):
    page.goto(BASE + "/")
    page.wait_for_function("typeof S !== 'undefined' && S && S.users")
    page.evaluate("showMonTab('details');table();")
    page.wait_for_timeout(600)


def test_airport_chips_render_and_filter(page):
    """chips 渲染（码聚合 ≥2 值）+ 点选过滤（只剩虹桥行）+ 取消恢复。"""
    _to_details(page)
    ndep = page.evaluate(
        "document.querySelectorAll('#depchips .chip').length")
    assert ndep >= 2, f"出发机场 chips 不足: {ndep}"
    narr = page.evaluate(
        "document.querySelectorAll('#archips .chip').length")
    assert narr >= 2, f"到达机场 chips 不足: {narr}"
    before = page.evaluate(
        "document.querySelectorAll('#ftable tbody tr[data-k]').length")
    page.evaluate("""(() => {
      const c = [...document.querySelectorAll('#depchips .chip')]
        .find(x => x.textContent.indexOf('虹桥') >= 0);
      c.click(); })()""")
    page.wait_for_timeout(300)
    rows = page.evaluate("""(() => {
      const trs = [...document.querySelectorAll(
        '#ftable tbody tr[data-k]')];
      return {n: trs.length,
              txt: trs.map(t => t.textContent).join(' ')}; })()""")
    assert rows["n"] < before, (before, rows["n"])
    assert rows["txt"].find("虹桥") >= 0 or rows["n"] == 0, rows["txt"][:200]
    # 取消恢复（再点同 chip）
    page.evaluate("""(() => {
      const c = [...document.querySelectorAll('#depchips .chip')]
        .find(x => x.classList.contains('on'));
      c.click(); })()""")
    page.wait_for_timeout(300)
    after = page.evaluate(
        "document.querySelectorAll('#ftable tbody tr[data-k]').length")
    assert after == before, (before, after)


def test_airport_name_normalized_chip_label(page):
    """chips 显示归一短名（「虹桥国际机场」→「虹桥」形态）——聚合按
    码去重，同名异形不翻倍。"""
    _to_details(page)
    labels = page.evaluate(
        "[...document.querySelectorAll('#depchips .chip')]"
        ".map(x => x.textContent)")
    assert labels, "depchips 空（chips 未渲染）"
    assert len(labels) == len(set(labels)), labels
    for lb in labels:
        assert "国际机场" not in lb, labels


def test_source_pins_airport_filters():
    """源码钉：双 chips 容器 + 码聚合 + 谓词 + 快照 + 克制律 vis。"""
    src = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert 'id="depchips"' in src and 'id="archips"' in src
    assert "FLT.depA.size" in src and "FLT.arrA.size" in src
    assert "depA:[...FLT.depA]" in src
    assert "depA:has(f=>f.depAirport||f.depAirportCode)" in src
