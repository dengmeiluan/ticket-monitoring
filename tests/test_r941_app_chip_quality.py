# -*- coding: utf-8 -*-
"""r941/r942：App 渠道 chip 的质感是门禁，不是一次性截图。

2026-11-04 用户两次点名「检索页这排 App 图标太劣质」：
  · 第一次：16px 官方标塞在无字胶囊里，五个渠道读作一排匿名色点；
  · 第二次（PC 截图）：22px 方片被 flex 压到 22.8px 宽，APP 角标盖住
    图标，仍是一排看不清的色块。根因是 chip 没锁固有尺寸（flex-shrink:1）。

修法见 ``webui.py`` 的 ``.srx-pchip-ic``：
  · 所有 chip ``flex:0 0 auto``，先保住固有尺寸；窄档由行内滚动承接；
  · PC 档 = 官方标 + 可见 ``APP`` 小字胶囊，和浏览器 chip 同一套边框/选中；
  · ≤760 档 = 36×30 图标方片 + APP 角标（省宽）。

这里把**看得见的判据**钉住：图标尺寸、APP 标的可见形态、选中勾与阴影、
PC 不被压缩、390 只让 chip 行自己横向滚动。
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
      const lr=l.getBoundingClientRect();
      const lab=l.querySelector('.srx-applab');
      l.click();
      const cs=getComputedStyle(l);
      return {w:r.width,h:r.height,chipW:lr.width,
              after:getComputedStyle(l,'::after').content,
              before:getComputedStyle(l,'::before').content,
              bg:cs.backgroundColor,
              lab:lab?{text:lab.textContent.trim(),
                       display:getComputedStyle(lab).display}:null,
              shadow:cs.boxShadow,
              checked:!!l.querySelector('input').checked};
    }""")
    assert st and st["checked"], st
    assert st["w"] >= 20 and st["h"] >= 20, ("App 图标仍是小图", st)
    # PC 档必须有「看得见的 APP 标」：文字标签，或（窄档）角标
    lab_visible = bool(st["lab"] and st["lab"]["display"] != "none"
                       and "APP" in st["lab"]["text"])
    assert "APP" in (st["after"] or "") or lab_visible, (
        "缺 App 标（PC 应有可见 APP 小字，窄档应有角标）", st)
    # 扁平化契约：选中只靠软品牌底 + 描边，不回到「勾 / 光环 / 渐变」
    assert "✓" not in (st["before"] or ""), ("选中态又加了勾符号", st)
    assert st["shadow"] in ("none", ""), ("选中态又加了投影/光环", st)
    assert st["bg"] not in ("rgba(0, 0, 0, 0)", "transparent"), (
        "选中态没有软品牌底", st)
    # 1440 档（紧凑排）也不能被 flex 压扁：胶囊宽度必须容得下 20px 图标 + APP 字
    assert st["chipW"] >= 44, ("PC App chip 被压缩，读作色块", st)


def test_app_chip_row_does_not_overflow_page_at_390(page):
    page.set_viewport_size({"width": 390, "height": 900})
    _open_search(page)
    st = page.evaluate("""()=>{
      const d=document.documentElement;
      const pick=document.getElementById('srxPlatPick');
      const l=document.querySelector(
        '#srxPlatPick .srx-pchip-ic[data-p="app_zhixing"]');
      const lab=l.querySelector('.srx-applab');
      return {doc:d.scrollWidth-d.clientWidth,
              pick:pick.scrollWidth-pick.clientWidth,
              chipW:l.getBoundingClientRect().width,
              after:getComputedStyle(l,'::after').content,
              lab:lab?getComputedStyle(lab).display:null};
    }""")
    assert st["doc"] <= 1, ("App chip 把整页撑出横向滚动", st)
    assert st["chipW"] >= 34, ("390 档 App chip 被压扁（应保留 36px 方片）", st)
    assert "APP" in (st["after"] or ""), ("390 档缺 APP 角标", st)
    assert st["lab"] == "none", ("390 档文字标签应隐藏，给内容省宽", st)
    assert st["pick"] > 0, ("窄档应由 chip 行自己横向滚动，而不是压扁 chip", st)
