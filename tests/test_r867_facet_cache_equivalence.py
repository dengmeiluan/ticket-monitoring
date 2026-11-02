# -*- coding: utf-8 -*-
"""r867 门禁：筛选面板的分面计数缓存，必须与被它替代的全量扫描逐组等值。

背景：面板展开时 `srxRenderFacets(true)` 每轮要跑 8 次 `srxFacetRows`，
万行下实测约 59ms，是「点开有点卡顿」的主因。改为按（数据源引用 + 筛选签名）
缓存，并在本组无选中项时八组共用一次扫描。

缓存只有在「计数完全不变」时才安全，因此本门禁不看耗时，而是把缓存结果与
未缓存的原始扫描逐组对比：
  · 每种筛选状态下，八个分面的行集合（长度 + 逐元素同一）必须相等；
  · 本组没有选中项时，缓存确实复用了共用结果（同一个数组引用）；
  · 本组有选中项时，缓存必须为该组单独算（不能拿共用结果冒充）。
最后再做一次真实的渲染对账：界面上的「全部航司」计数必须等于该组分面的行数，
「命中 x / y」必须等于当前筛选后的行数。
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

JS = r"""() => {
  const states = [
    {name: 'default', f: {}},
    {name: 'airline', f: {airlines: ['CA']}},
    {name: 'bag', f: {bag: true}},
    {name: 'stopOnly', f: {stopMode: 'only'}},
    {name: 'depAs', f: {depAs: ['SHA']}},
  ];
  const out = [];
  for (const st of states) {
    SRX.f = Object.assign({}, SRX_DEFAULT_F,
                          {airlines: [], depAs: [], arrAs: [], cabins: [], pss: []}, st.f);
    const sig = srxFacetSig();
    SRX_FACET_CACHE = {sig: '', src: [], rows: {}};
    const rows = {};
    let shared = null;
    for (const k of SRX_FACET_KEYS) {
      const cached = srxFacetRowsCached(k, sig);
      const direct = srxFacetRows(k);
      rows[k] = {
        cl: cached.length,
        dl: direct.length,
        lenOk: cached.length === direct.length,
        same: cached.length === direct.length && cached.every((r, i) => r === direct[i]),
        dirty: srxFacetDirty(k),
        isShared: !!SRX_FACET_CACHE.rows['*'] && cached === SRX_FACET_CACHE.rows['*'],
      };
      if (rows[k].isShared) shared = cached;
    }
    // 二次取用必须命中缓存（不得重算）
    let stable = true;
    for (const k of SRX_FACET_KEYS) {
      const again = srxFacetRowsCached(k, sig);
      if (again !== srxFacetRowsCached(k, sig)) stable = false;
    }
    // 数据原地变长（同引用 push）必须让缓存失效，不能拿旧计数冒充当轮。
    // 用一条「确在作用域内」的行来复制，否则计数不变是过滤器正确的结果。
    const u0 = srxU();
    let grew = null;
    const scopeRows = srxBase();
    if (st.name === 'default' && u0 && Array.isArray(u0.flights) && scopeRows.length) {
      const before = srxFacetRowsCached('airline', sig).length;
      u0.flights.push(Object.assign({}, scopeRows[0]));
      const after = srxFacetRowsCached('airline', sig).length;
      u0.flights.pop();
      grew = {before, after};
    }
    out.push({state: st.name, rows, stable, hasShared: !!shared, grew});
  }

  /* 渲染对账：换成 bag=true 后重写面板，界面数字必须来自同一份分面数据。 */
  SRX.f = Object.assign({}, SRX_DEFAULT_F,
                        {airlines: [], depAs: [], arrAs: [], cabins: [], pss: []}, {bag: true});
  SRX.more = true;
  SRX_FACET_CACHE = {sig: '', src: [], rows: {}};
  srxRenderFacets(true);
  const firstAir = document.querySelector('#srfAirChips .srf-opt');
  const airNum = firstAir ? Number((firstAir.querySelector('i') || {}).textContent) : null;
  const expectAir = srxFacetRows('airline').length;
  const hit = (document.querySelector('[data-srf-hit]') || {}).textContent || '';
  const m = hit.match(/命中\s*(\d+)\s*\/\s*(\d+)/);
  return {
    states: out,
    rendered: {
      airNum, expectAir, hit,
      hitShown: m ? Number(m[1]) : null,
      hitTotal: m ? Number(m[2]) : null,
      filtered: srxFiltered().length,
      panelHtml: (document.getElementById('srxFmore') || {}).innerHTML.length || 0,
    },
  };
}"""


@pytest.fixture(scope="module")
def data():
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
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            pg = br.new_page(viewport={"width": 1512, "height": 1000})
            pg.goto(BASE + "/", wait_until="domcontentloaded")
            pg.wait_for_timeout(2600)
            pg.evaluate("switchView('search')")
            pg.wait_for_timeout(1200)
            res = pg.evaluate(JS)
            br.close()
        yield res
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()


def test_cached_facet_rows_equal_direct_scan(data):
    bad = []
    for st in data["states"]:
        for k, r in st["rows"].items():
            if not r["same"]:
                bad.append((st["state"], k, r["cl"], r["dl"]))
    assert not bad, "缓存分面与原始扫描不一致（状态, 组, 缓存行数, 原行数）：%s" % bad


def test_cache_reuses_shared_scan_only_when_group_clean(data):
    bad = []
    for st in data["states"]:
        for k, r in st["rows"].items():
            if r["dirty"] and r["isShared"]:
                bad.append((st["state"], k, "组有选中项却复用了共用结果"))
            if not r["dirty"] and not r["isShared"]:
                bad.append((st["state"], k, "组无选中项却没复用共用结果"))
    assert not bad, "分面缓存的复用判据错了：%s" % bad
    assert all(st["stable"] for st in data["states"]), "同签名二次取用不稳定"


def test_cache_invalidates_when_rows_grow_in_place(data):
    grew = [st["grew"] for st in data["states"] if st["grew"]]
    assert grew, "没量到原地变长（demo 无行数据？）"
    bad = [g for g in grew if g["after"] <= g["before"]]
    assert not bad, (
        "往 flights 原地 push 后分面计数没变，缓存把旧计数当成了新数据：%s" % bad)


def test_rendered_counts_come_from_cached_facets(data):
    r = data["rendered"]
    assert r["panelHtml"] > 1000, "筛选面板没渲染出来：%r" % r
    assert r["airNum"] == r["expectAir"], (
        "界面「全部航司」计数 %r 与本组分面行数 %r 不一致" % (r["airNum"], r["expectAir"]))
    assert r["hitShown"] == r["filtered"], (
        "「命中」显示 %r，实际筛选后 %r 行" % (r["hitShown"], r["filtered"]))
