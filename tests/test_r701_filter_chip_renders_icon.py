# -*- coding: utf-8 -*-
r"""#12：明细台「生效筛选」的分类标签必须渲染成图标，而不是 SVG 源码。

现象（issue #12 + 线上演示站）：选中「直飞 / 中转·达标 / 仅达标 / 直挂」后，
生效筛选摘要栏里的 chip 显示成 `&lt;svg ...&gt;` 文本。根因是分类标签由
`_fltCatLabel()` 产出**含内嵌图标**的 HTML，而拼接处对整串做了 `esc()`。

判据（真渲染，不匹配字符串）：
① 选中分类后，chip 内确有 `<svg>` 元素，且页面文本里不出现 `<svg`；
② 同一 chip 的 title 是**纯文本**（可读的中文分类名），不含标签尖括号；
③ 其它筛选（如搜索词）仍按纯文本转义——不能为了修图标把注入面打开。

负控：把拼接改回 `esc(g.label)` → ① 红；把分类也按纯文本塞进 title → ② 红。
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture(scope="module")
def page():
    import webui
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip("Chromium 二进制未安装")
        b = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.add_init_script("window.setInterval = () => 1;")
        html = webui._page_html("ui-test")
        pg.set_content(html, wait_until="domcontentloaded")
        yield pg, errors
        ctx.close()
        b.close()


def test_category_chip_renders_icon_not_source(page):
    pg, errors = page
    out = pg.evaluate("""() => {
      // 直接驱动渲染函数：选中「直飞」分类，并加一个搜索词（验证仍转义）
      F = 'd';
      FLT.q = '<b>x</b>';
      try { renderFltSum(); } catch(e) { return {err: String(e)}; }
      const box = document.getElementById('fltsum');
      const chips = Array.from(box.querySelectorAll('.fs-chip'));
      const cat = chips.find(c => c.textContent.indexOf('直飞') >= 0);
      return {
        boxText: box.textContent,
        chipCount: chips.length,
        hasSvgEl: !!(cat && cat.querySelector('svg')),
        svgSourceInText: box.textContent.indexOf('<svg') >= 0,
        catTitle: cat ? (cat.getAttribute('title') || '') : '',
        qChipText: (chips.find(c => c.textContent.indexOf('搜索') >= 0) || {}).textContent || '',
        qHasEl: !!(chips.find(c => c.textContent.indexOf('搜索') >= 0) || {querySelector: null})?.querySelector?.('b'),
      };
    }""")
    assert "err" not in out, out
    assert out["chipCount"] >= 2, out
    assert out["hasSvgEl"], "分类 chip 里没有图标元素——SVG 又被当文本了：%r" % out
    assert not out["svgSourceInText"], "页面文本里出现 <svg 源码：%r" % out["boxText"][:120]
    assert "<" not in out["catTitle"] and "直飞" in out["catTitle"], (
        "分类 chip 的 title 应是纯文本分类名，实际 %r" % out["catTitle"])
    # 搜索词仍按文本渲染：不产生 <b> 元素，且保留原文
    assert out["qHasEl"] is False, "搜索词被当成 HTML 渲染了（注入面被打开）"
    assert "<b>" in out["qChipText"], "搜索词原文应可见（转义后显示为文本）"
    assert not errors, "页面报错：%s" % errors[:3]
