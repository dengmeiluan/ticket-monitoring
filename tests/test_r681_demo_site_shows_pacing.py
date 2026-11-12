# -*- coding: utf-8 -*-
r"""r681：公开演示站必须能打开节流面板（烘焙层不许漏接口）。

实测：`docs/demo_build.py` 的 shim 没有拦截 `/api/pacing`，演示站健康页的
节流区直接渲染「读取失败：在线演示为静态烘焙页」。而这个面板正是产品的
主观测面（渠道成功率、干预、溯源），公开演示站看不到等于把核心能力藏了。

判据（真浏览器 + 真烘焙产物）：
① 演示站健康页 `#paceBox` 里出现渠道行，且 ≥ 全部浏览器渠道数；
② 不出现「读取失败」；
③ 登录卡 ≥ 渠道数 + App 渠道数；
④ 页面零 pageerror。

前置：`docs/site/index.html` 必须是当前代码烘焙的（否则无法判定）。
负控：删掉 shim 的 /api/pacing 分支 → ①② 红。
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SITE = Path(ROOT) / "docs" / "site" / "index.html"


def _need_site():
    if not SITE.exists() or SITE.stat().st_size < 10000:
        pytest.skip("docs/site/index.html 未烘焙（先跑 docs/demo_build.py）")


def test_bake_covers_pacing_endpoint():
    """源码层：shim 必须拦截 /api/pacing，且烘焙字典带 pacing 载荷。"""
    src = (Path(ROOT) / "docs" / "demo_build.py").read_text(
        encoding="utf-8", errors="replace")
    assert "u.indexOf('/api/pacing')===0" in src, \
        "shim 未拦截 /api/pacing——演示站节流面板会渲染「读取失败」"
    assert '"pacing": webui._demo_pacing_payload()' in src, \
        "烘焙字典没有 pacing 载荷（单源复用 _demo_pacing_payload）"


def test_demo_site_renders_pacing_rows():
    """行为层：真浏览器打开烘焙站，节流面板确实有行、无「读取失败」。"""
    _need_site()
    from core.channels import APP_CHANNELS, BROWSER_CHANNELS
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip("Chromium 二进制未安装")
        b = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto("file:///" + str(SITE).replace("\\", "/"))
        pg.wait_for_timeout(2500)
        pg.evaluate("() => { try{switchView('mon')}catch(e){} }")
        pg.wait_for_timeout(500)
        pg.evaluate("() => { try{showMonTab('health')}catch(e){} }")
        try:
            pg.wait_for_function(
                "() => document.querySelectorAll('#paceBox .pace-row').length>0",
                timeout=15000)
        except Exception:
            pass
        rows = pg.evaluate(
            "() => document.querySelectorAll('#paceBox .pace-row').length")
        text = pg.evaluate(
            "() => {const e=document.getElementById('paceBox');"
            "return e?e.innerText:''}")
        pg.evaluate("() => { try{switchView('cfg')}catch(e){} }")
        pg.evaluate("() => { try{showCfgPanel('login')}catch(e){} }")
        pg.wait_for_timeout(1200)
        cards = pg.evaluate("() => document.querySelectorAll('.lgcard').length")
        b.close()
    assert rows >= len(BROWSER_CHANNELS), (
        "演示站节流面板只有 %d 行（至少应有 %d 个浏览器渠道）：%r"
        % (rows, len(BROWSER_CHANNELS), text[:120]))
    assert "读取失败" not in text, "演示站节流面板仍在报读取失败：%r" % text[:160]
    assert cards >= len(BROWSER_CHANNELS) + len(APP_CHANNELS), (
        "演示站登录卡只有 %d 张，少于渠道总数" % cards)
    assert not errors, "演示站页面报错：%s" % errors[:3]
