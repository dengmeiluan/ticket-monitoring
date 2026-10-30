# -*- coding: utf-8 -*-
"""r320 城市选择面板行为钉（全量城市化 + 搜索/热门/字母分组）：

- 数据面：cityx 下发（py/npy/hot）+ 面板全量渲染（≥200 城）；
- 交互面：点击弹面板、三通道搜索（中文/拼音/三字码）、选择回填+
  change 派发、Esc capture 收面板、空态教学行；
- 退役面：native datalist（citydl）零残留——289 城下原生联想不分
  组无热门，自定义面板全量替代。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r320_citypanel.py -q
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
    priv_tmp = _tf.mkdtemp(prefix="r320cp_")
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


def _open_cfg(page):
    """进配置视图、展开用户卡分区（城市输入在折叠分区内——先走真实
    展开路径）。CFG 属配置视图懒加载：先 switchView 触发拉取。"""
    page.goto(BASE + "/")
    page.evaluate("switchView('cfg')")
    page.wait_for_function("typeof CFG !== 'undefined' && CFG && CFG.length")
    page.evaluate("showCfgPanel('users')")
    page.wait_for_function(
        "document.querySelector('#panel-users')"
        " && document.querySelector('#panel-users').style.display!=='none'")
    page.evaluate("expandFolds()")
    page.wait_for_timeout(400)


def _city_inputs(page):
    return page.locator(
        '#cfgview input[onclick="cityPanelOpen(this)"]')


def test_api_cityx_payload(srv):
    """cityx 下发：py/npy/hot 三键在案 + 连云港通道样本。"""
    import urllib.request
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    import json
    j = json.load(op.open(BASE + "/api/config", timeout=5))
    cx = j.get("cityx") or {}
    assert cx.get("py", {}).get("连云港") == "L"
    assert cx.get("npy", {}).get("连云港") == "lianyungang"
    assert "北京" in (cx.get("hot") or [])
    assert len(j.get("city") or {}) >= 200


def test_panel_open_full_render_and_search(page):
    """打开全量渲染（≥200 城/热门组/字母节）；三通道搜索过滤。"""
    _open_cfg(page)
    inp = _city_inputs(page).first
    inp.click()
    page.wait_for_selector("#citypanel", state="visible")
    n = page.evaluate(
        "document.querySelectorAll('#cpbody .cp-city').length")
    assert n >= 200, f"面板全量渲染不足: {n}"
    assert "北京" in page.evaluate(
        "document.querySelector('.cp-hot').textContent")
    assert page.evaluate(
        "document.querySelectorAll('#cpbody .cp-sec').length") >= 10
    # 中文通道（取件限定字母节——热门组常驻不过滤是设计内）
    page.fill("#cpq", "连云")
    vis = page.evaluate("""(() => {
      const g = n => { const el = document.querySelector(
        `#cpbody .cp-sec .cp-city[data-n="${n}"]`);
        return !!el && el.style.display !== 'none'; };
      return {lyg: g('连云港'), bj: g('北京')}; })()""")
    assert vis["lyg"] and not vis["bj"], vis
    # 拼音通道
    page.fill("#cpq", "lianyungang")
    assert page.evaluate("""(() => { const el = document.querySelector(
      '#cpbody .cp-sec .cp-city[data-n="连云港"]');
      return el && el.style.display !== 'none'; })()""")
    # 三字码通道
    page.fill("#cpq", "LYG")
    assert page.evaluate("""(() => { const el = document.querySelector(
      '#cpbody .cp-sec .cp-city[data-n="连云港"]');
      return el && el.style.display !== 'none'; })()""")
    # 空态教学行
    page.fill("#cpq", "zzzz")
    assert page.evaluate(
        "document.getElementById('cpNone').style.display") == "block"


def test_pick_fills_input_and_closes(page):
    """选择回填：input 值=连云港 + 面板关闭（change 派发由内联链
    接管——CFG 模型经 setRoute 归一后 from=LYG，深链在保存侧验证）。"""
    _open_cfg(page)
    inp = _city_inputs(page).first
    inp.click()
    page.wait_for_selector("#citypanel", state="visible")
    page.fill("#cpq", "连云港")
    page.click('#cpbody .cp-city[data-n="连云港"]')
    assert page.evaluate(
        "document.getElementById('citypanel').style.display") == "none"
    assert inp.input_value() == "连云港"


def test_esc_closes_before_other_layers(page):
    """Esc 收面板（capture 链头）：面板开着按 Esc 关面板，不误收
    比价行等其他弹层状态。"""
    _open_cfg(page)
    inp = _city_inputs(page).first
    inp.click()
    page.wait_for_selector("#citypanel", state="visible")
    page.keyboard.press("Escape")
    assert page.evaluate(
        "document.getElementById('citypanel').style.display") == "none"


def test_source_pins_datalist_retired():
    """源码钉：cityx 下发两处 + _cityx 单源 + datalist（citydl）
    零残留 + 保焦点/Esc capture 交互在案。"""
    src = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert src.count('"cityx": _cityx()') == 2
    assert "def _cityx():" in src
    assert "citydl" not in src, "native datalist 残留（289 城改自定义面板）"
    assert "e.target.closest('.cp-city,.cp-x,.cp-abc'))e.preventDefault()" in src
    assert "cityPanelPick" in src and "cityPanelFilter" in src


def test_anchor_jump_keeps_section_head_visible(page):
    """字母锚点跳转：节头完整可见（sticky 导航条实高回退——用户实锤
    「点 B 看不到组头」：block:start 把节滚到容器顶被悬浮条盖住）。"""
    _open_cfg(page)
    inp = _city_inputs(page).first
    inp.click()
    page.wait_for_selector("#citypanel", state="visible")
    page.evaluate("cityPanelJump('B')")
    page.wait_for_timeout(600)
    r = page.evaluate("""(() => {
      const sec = document.querySelector('.cp-sec[data-l="B"]');
      const ab = document.querySelector('.cp-abc');
      const head = sec && sec.querySelector('.cp-lhead');
      if (!sec || !head || !ab) return null;
      const h = head.getBoundingClientRect();
      const a = ab.getBoundingClientRect();
      return {headTop: h.top, abBottom: a.bottom,
              inView: h.top >= a.bottom - 1}; })()""")
    assert r and r["inView"], r
