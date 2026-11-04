# -*- coding: utf-8 -*-
"""r941：App 渠道 chip 的质感是门禁，不是一次性截图。

2026-11-04 用户点名「检索页这排 App 图标太劣质」：当时是 16px 官方标
塞在无字胶囊里，五个渠道读作一排匿名色点。修法见 ``webui.py`` 的
``.srx-pchip-ic``：22px 官方标 + APP 角标 + 选中品牌光环/勾。

这里把**看得见的判据**钉住：图标尺寸、角标内容、选中勾与阴影；
再验 390 窄档只让 chip 行自己横向滚动，不把整页撑出横向滚动条。
"""
from entry_mon_harness import page, srv, _goto  # noqa: F401


def _open_search(page):
    _goto(page, "#search")
    page.evaluate(
        "()=>{const p=document.getElementById('srxProbe');"
        "if(p)p.classList.add('open')}")
    page.wait_for_selector(
        '#srxPlatPick .srx-pchip-ic[data-p="app_zhixing"] img.bic',
        timeout=15000)
    page.wait_for_timeout(300)


def test_app_chip_has_large_official_icon_badge_and_check(page):
    _open_search(page)
    st = page.evaluate("""()=>{
      const l=document.querySelector(
        '#srxPlatPick .srx-pchip-ic[data-p="app_zhixing"]');
      if(!l)return null;
      const im=l.querySelector('.bic');
      const r=im.getBoundingClientRect();
      l.click();
      const cs=getComputedStyle(l);
      return {w:r.width,h:r.height,
              after:getComputedStyle(l,'::after').content,
              before:getComputedStyle(l,'::before').content,
              shadow:cs.boxShadow,
              checked:!!l.querySelector('input').checked};
    }""")
    assert st and st["checked"], st
    assert st["w"] >= 20 and st["h"] >= 20, ("App 图标仍是小图", st)
    assert "APP" in st["after"], ("缺 App 角标", st)
    assert "✓" in st["before"], ("选中态缺勾", st)
    assert st["shadow"] not in ("none", ""), ("选中态缺品牌光环", st)


def test_app_chip_row_does_not_overflow_page_at_390(page):
    page.set_viewport_size({"width": 390, "height": 900})
    _open_search(page)
    st = page.evaluate("""()=>{
      const d=document.documentElement;
      const pick=document.getElementById('srxPlatPick');
      return {doc:d.scrollWidth-d.clientWidth,
              pick:pick.scrollWidth-pick.clientWidth};
    }""")
    assert st["doc"] <= 1, ("App chip 把整页撑出横向滚动", st)
    assert st["pick"] >= 0, st
