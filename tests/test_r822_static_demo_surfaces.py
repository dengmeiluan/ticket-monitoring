# -*- coding: utf-8 -*-
"""r822：离线演示站必须自带矩阵 / 健康 / 渠道入口 / 雷达入口数据。

缺陷背景（2026-11-02）：`docs/demo_build.py` 只烘了 16 个接口，
`/api/channel-dims`、`/api/health` 完整载荷、`/api/channel-links`
都没烘——公开站配置页显示「能力矩阵加载失败」、健康诊断 0 张卡、
渠道入口写「演示站未提供接口」、特价雷达入口 0 band。
本门禁直接开 file:// 真渲染，不只看源码字面。
"""
import json
import os
import re

import pytest

pytest.importorskip("playwright",
                    reason="静态站门禁依赖 playwright")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "docs", "site", "index.html")

from core.channels import (APP_CHANNELS, BROWSER_CHANNELS,  # noqa: E402
                           CHANNEL_DIMENSIONS, plat_cn)


def _baked():
    with open(SITE, encoding="utf-8") as f:
        src = f.read()
    m = re.search(r"window\.__BAKED__=(\{.*?\});\n", src, re.S)
    assert m, "找不到 window.__BAKED__"
    return json.loads(m.group(1))


def _open():
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    b = pw.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1512, "height": 1100})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto("file:///" + SITE.replace("\\", "/") + "#health",
            wait_until="domcontentloaded", timeout=30000)
    pg.wait_for_timeout(2800)
    return pw, b, pg, errs


def test_static_bake_contains_matrix_health_and_links():
    baked = _baked()
    plats = {c["plat"] for c in baked["dims"]["channels"]}
    assert plats == set(BROWSER_CHANNELS) | set(APP_CHANNELS), plats

    h = baked["health"]
    diag = {c.get("plat") for c in (h.get("diag") or [])}
    assert diag == plats, diag
    assert h.get("demo") is True
    assert all(str(c.get("label") or "").startswith("演示")
               for c in h.get("diag") or []), h.get("diag")
    # 公开站不能把本机真实登录态烘进 HTML
    assert not any(c.get("slots") for c in h.get("diag") or []), (
        "静态站烘焙了真实登录槽位")
    assert h.get("paths"), "静态站健康载荷没有分通路账"

    links = baked.get("channelLinks") or {}
    assert links.get("ok") is True
    assert {c["plat"] for c in links.get("channels") or []} >= set(
        APP_CHANNELS)
    assert links.get("specials"), "静态站没有官方特价频道入口"

    assert baked.get("pulse", {}).get("rounds"), "静态站没有运行脉冲"
    paths = baked.get("paths") or {}
    assert paths.get("demo") is True, paths
    assert set(paths.get("platforms") or {}) >= set(APP_CHANNELS), paths


def test_static_renders_health_links_and_radar():
    n_plats = len(BROWSER_CHANNELS) + len(APP_CHANNELS)
    pw, b, pg, errs = _open()
    try:
        cards = pg.evaluate(
            "()=>document.querySelectorAll('.hdiag-card').length")
        assert cards == n_plats, cards
        text = pg.evaluate("()=>{const w=document.querySelector('.hdiag');"
                           "return w?w.innerText:'NO'}")
        assert "诊断数据未到" not in text, text[:200]
        assert pg.evaluate(
            "()=>document.querySelectorAll('#pulsebars .pbar').length") > 0
        assert pg.evaluate(
            "()=>document.querySelectorAll('.hpath').length") == n_plats
        empty = pg.evaluate("""async()=>{
          const a=await (await fetch('/api/specials')).json();
          const b=await (await fetch('/api/trace?platform=ctrip')).json();
          return {a,b};
        }""")
        assert empty["a"].get("ok") is True and empty["a"].get("demo") is True
        assert empty["b"].get("ok") is True and empty["b"].get("demo") is True

        pg.evaluate("()=>{switchView('cfg');showCfgPanel('users')}")
        pg.wait_for_timeout(2200)
        links = pg.evaluate(
            "()=>{const w=document.getElementById('cfgChannelLinksBox');"
            "return w?w.innerText:'NO'}")
        assert "未提供渠道页面接口" not in links, links[:200]
        assert "携程" in links and "去哪儿" in links, links[:200]

        pg.evaluate("()=>{switchView('cfg');showCfgPanel('login')}")
        pg.wait_for_timeout(1200)
        note = pg.evaluate(
            "()=>{const n=document.querySelector('#sec-dims .secnote');"
            "return n?n.textContent:''}")
        assert "7 家" not in note and "全部渠道" in note, note

        pg.evaluate("()=>{switchView('mon');showMonTab('specials')}")
        pg.wait_for_timeout(2800)
        out = pg.evaluate("""()=>({
          bands: document.querySelectorAll('#spentryboard .chband').length,
          names: [...document.querySelectorAll(
            '#spentryboard .chband-name b')].map(x=>x.textContent.trim())
        })""")
        assert out["bands"] == n_plats, out
        for p in APP_CHANNELS:
            assert plat_cn(p) in out["names"], (p, out["names"])
        assert not errs, errs[:3]
    finally:
        b.close()
        pw.stop()
