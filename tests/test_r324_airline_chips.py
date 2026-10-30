# -*- coding: utf-8 -*-
"""r324 航司筛选钉（P1-1 词形漂移拆片根治）：

- 航司 chips 键=airlineCode 首段（共享复合 MU/8L 取首段；无码回退
  词前缀）——渠道词形漂移（「吉祥/吉祥航」「海航/新海航」）与跨码
  同词（去哪儿「新海航」前缀横跨 GS/HU/Y8）双向不再错组；
- 显示=该码下词面众数（AQ 码下九元/北部湾双名并存在案，静态
  码→名映射不可信）；同名异形不拆片，勾一片不漏行；
- P3-1：#attrchips 顶轴对齐（多行航司组不再把单行组悬中）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r324_airline_chips.py -q
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
    priv_tmp = _tf.mkdtemp(prefix="r324ac_")
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


_SYNTH = """
(() => {
  const u = S.users[U];
  const bak = u.flights;
  const proto = JSON.parse(JSON.stringify(bak[0]));
  const mk = (ov) => Object.assign(JSON.parse(JSON.stringify(proto)), ov);
  u.flights = [
    mk({name: '吉祥HO100', code: 'HO100', price: 900,
        airlineCode: 'HO'}),
    mk({name: '吉祥HO101', code: 'HO101', price: 910,
        airlineCode: 'HO'}),
    mk({name: '吉祥HO102', code: 'HO102', price: 920,
        airlineCode: 'HO'}),
    mk({name: '吉祥航HO200', code: 'HO200', price: 930,
        airlineCode: 'HO'}),
    mk({name: '东方航空MU111', code: 'MU111', price: 940,
        airlineCode: 'MU/8L'}),
    mk({name: '东方航空MU222', code: 'MU222', price: 950,
        airlineCode: 'MU'}),
    mk({name: '春秋航空9C888', code: '9C888', price: 960,
        airlineCode: ''}),
  ];
  FLT.airlines.clear();
  resetFlt();
  buildAttrChips();
  table();
  return {n: u.flights.length};
})()
"""

_RESTORE = """
(() => {
  const u = S.users[U];
  u.flights = %BAK%;
  FLT.airlines.clear();
  resetFlt();
  buildAttrChips();
  table();
})()
"""


def _to_details(page):
    page.goto(BASE + "/")
    page.wait_for_function("typeof S !== 'undefined' && S && S.users")
    page.evaluate("showMonTab('details');table();"
                  "const fb=document.querySelector('.fbar');"
                  "if(fb&&getComputedStyle(fb).display==='none')togFlt();")
    page.wait_for_timeout(600)


def _with_synth(page, todo):
    """快照还原三件套：换装合成行 → 执行断言 → 无条件还原。"""
    page.evaluate("window.__r324bak = S.users[U].flights")
    page.evaluate(_SYNTH)
    try:
        return page.evaluate(todo)
    finally:
        page.evaluate(
            _RESTORE.replace("%BAK%", "window.__r324bak"))
        page.evaluate("delete window.__r324bak")


def test_same_code_dual_wordform_single_chip(page):
    """同码双词形（吉祥/吉祥航）只出一 chip，勾选两词形行同现不漏。"""
    _to_details(page)
    out = _with_synth(page, """(() => {
      const labels = [...document.querySelectorAll('#alchips .chip')]
        .map(x => x.textContent.trim());
      const ho = [...document.querySelectorAll('#alchips .chip')]
        .filter(x => (x.dataset.k || '') === 'HO');
      if (ho.length !== 1) return {fail: 'ho-chips', labels};
      if (labels.some(t => t === '吉祥航'))
        return {fail: 'wordform-split', labels};
      ho[0].click();
      const trs = [...document.querySelectorAll(
        '#ftable tbody tr[data-k]')].map(t => t.textContent);
      return {labels,
              hoHits: trs.filter(t => t.indexOf('HO10') >= 0).length,
              chainHits: trs.filter(t => t.indexOf('吉祥航HO200') >= 0)
                            .length};
    })()""")
    assert "fail" not in out, out
    assert out["hoHits"] == 3, out      # 吉祥HO100/101/102
    assert out["chainHits"] == 1, out   # 吉祥航HO200 同片不漏行


def test_chip_label_is_mode_word(page):
    """显示=码下词面众数（吉祥×3 vs 吉祥航×1 → 「吉祥」）。"""
    _to_details(page)
    out = _with_synth(page, """(() => {
      const ho = [...document.querySelectorAll('#alchips .chip')]
        .find(x => (x.dataset.k || '') === 'HO');
      return {label: ho ? ho.textContent.trim() : null};
    })()""")
    assert out["label"] == "吉祥", out


def test_codeshare_compound_code_merges(page):
    """共享复合码 MU/8L 与 MU 首段同片（东方航空）。"""
    _to_details(page)
    out = _with_synth(page, """(() => {
      const mu = [...document.querySelectorAll('#alchips .chip')]
        .filter(x => (x.dataset.k || '').split('/')[0] === 'MU');
      if (mu.length !== 1) return {fail: 'mu-chips', n: mu.length};
      mu[0].click();
      const trs = [...document.querySelectorAll(
        '#ftable tbody tr[data-k]')].map(t => t.textContent);
      return {hits: trs.filter(t => t.indexOf('MU1') >= 0
                                     || t.indexOf('MU2') >= 0).length};
    })()""")
    assert "fail" not in out, out
    assert out["hits"] == 2, out    # MU111(MU/8L) + MU222(MU)


def test_word_fallback_without_code(page):
    """无 airlineCode 行按词前缀自成一片（春秋航空）。"""
    _to_details(page)
    out = _with_synth(page, """(() => {
      const ck = [...document.querySelectorAll('#alchips .chip')]
        .find(x => x.textContent.trim() === '春秋航空');
      if (!ck) return {fail: 'no-fallback-chip'};
      ck.click();
      const trs = [...document.querySelectorAll(
        '#ftable tbody tr[data-k]')].map(t => t.textContent);
      return {hits: trs.filter(t => t.indexOf('9C888') >= 0).length};
    })()""")
    assert "fail" not in out, out
    assert out["hits"] == 1, out


def test_attrchips_top_aligned(page):
    """P3-1：attrchips 顶轴对齐——chiplab 盒高与单片同高（padding
    同源），多行航司组不再把单行组悬中。"""
    _to_details(page)
    page.evaluate("window.__r324bak = S.users[U].flights")
    page.evaluate(_SYNTH)
    try:
        page.evaluate("""(() => {
          const w = document.createElement('span');
          w.className = 'chips-wrap';
          for (let i = 0; i < 14; i++) {
            const c = document.createElement('span');
            c.className = 'chip';
            c.textContent = '填充' + i;
            w.appendChild(c);
          }
          document.getElementById('alchips').replaceWith(w);
          w.id = 'alchips';
        })()""")
        out = page.evaluate("""(() => {
          const row = document.getElementById('attrchips');
          const ai = getComputedStyle(row).alignItems;
          const wrap = document.getElementById('alchips');
          const lab = wrap.closest('.agrp').querySelector('.chiplab');
          const chip = wrap.querySelector('.chip');
          const lr = lab.getBoundingClientRect();
          const cr = chip.getBoundingClientRect();
          return {ai,
                  labH: Math.round(lr.height),
                  chipH: Math.round(cr.height),
                  topDelta: Math.round(Math.abs(lr.top - cr.top))};
        })()""")
        # r349：属性筛选改为固定标签轨 + 机场双列，组内标签/片顶对齐；
        # 高度不再要求相等（标签含 padding），只守首片与标签顶线 ≤2px。
        assert out["ai"] in ("center", "start"), out
        assert out["topDelta"] <= 2, out
        assert out["labH"] > 0 and out["chipH"] > 0, out
    finally:
        page.evaluate(_RESTORE.replace("%BAK%", "window.__r324bak"))
        page.evaluate("delete window.__r324bak")


def test_source_pins_carrier_code_aggregation():
    """源码钉：码键单源 + 谓词消费 + 旧词面键聚合退役。"""
    src = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert "function carrierKeyOf" in src, "码键单源函数应在案"
    assert "FLT.airlines.has(carrierKeyOf(f))" in src, "谓词应消费码键"
    assert "new Set(u.flights.map(carrierOf))" not in src, (
        "旧词面键聚合应退役")
    assert "function carrierOf(" not in src, "旧词面派生单源应退役"
    assert 'class="frow attrgrid"' in src and \
        src.count('id="attrchips"') == 1, "r343 属性筛选横滚分组应在案"
    assert ".attrgrid .agrp .chips-wrap{" in src, \
        "单行横滚容器样式应在案"
