# -*- coding: utf-8 -*-
"""r324 入场监控行为钉 · 明细面入口（dt01–dt07）：表头排序、类别 tabs、行展开、改期胶囊、chips 族。

r490 从 test_r324_entry_mon.py 按主题拆出：只为让 xdist 按文件并行，
用例、断言与安全纪律（demo 只读门、不点生产写钮）原样保留。
"""
import pytest  # noqa: F401

from entry_mon_harness import (  # noqa: F401  fixtures 经模块属性注册
    page, srv, _goto, _mtab, _details, _toasts, _toast_last,
    _fcnt, _flt, _restore, _SNAP_UI, _RESTORE_UI)

def test_dt01_sort_header_three_face(page):
    """排序表头：真实点击价格表头 → SORT.dir 翻转 + aria-sort + 箭头
    + 行序真变（数据面）；日期表头 → srtchip 三件套同拍（r247 W2）。"""
    _goto(page)
    _details(page)
    first0 = page.evaluate(
        "document.querySelector('#ftable tbody tr[data-k] td')"
        ".textContent.replace(/[^0-9]/g,'')")
    page.locator("th.srt[data-k='price']").click()
    page.wait_for_timeout(300)
    assert page.evaluate("JSON.stringify(SORT)") == '{"k":"price","dir":-1}'
    th = page.locator("th.srt[data-k='price']")
    assert th.get_attribute("aria-sort") == "descending"
    assert "▼" in th.text_content()
    first1 = page.evaluate(
        "document.querySelector('#ftable tbody tr[data-k] td')"
        ".textContent.replace(/[^0-9]/g,'')")
    assert int(first1) >= int(first0), (first0, first1)   # 行序真翻
    page.locator("th.srt[data-k='date']").click()
    page.wait_for_timeout(300)
    assert page.evaluate("SORT.k") == "date"
    chip = page.evaluate(
        "(() => {const c = document.querySelector('.srtchip');"
        "return [c.classList.contains('on'), c.getAttribute('aria-pressed'),"
        "c.dataset.dir];})()")
    assert chip == [True, "true", "asc"], chip
    page.locator("#fltwrap button[onclick*='resetFltUI']").click()
    page.wait_for_timeout(300)
    assert page.evaluate("JSON.stringify(SORT)") == '{"k":"price","dir":1}'
    assert "已恢复默认排序" in _toasts(page)

def test_dt02_category_tabs(page):
    """类别 tabs（#tabs 委托点击）：仅达标 → F='q' + 高亮 + aria-pressed
    + 结果集全达标（🔥 行数=行数）；全部回位。"""
    _goto(page)
    _details(page)
    page.locator("#tabs span[data-f='q']").click()
    page.wait_for_timeout(300)
    assert page.evaluate("F") == "q"
    assert page.evaluate(
        "document.querySelector('#tabs span[data-f=\\'q\\']')"
        ".classList.contains('on')")
    assert page.get_attribute("#tabs span[data-f='q']", "aria-pressed") == \
        "true"
    rows, fires = page.evaluate(
        "[document.querySelectorAll('#ftable tbody tr[data-k]').length,"
        "document.querySelectorAll('#ftable tbody tr[data-k] .fire').length]")
    assert rows > 0 and rows == fires, (rows, fires)
    page.locator("#tabs span[data-f='all']").click()
    page.wait_for_timeout(200)
    assert page.evaluate("F") == "all"

def test_dt03_row_expand_compare_chain(page):
    """行展开 togRow：点击行价格格（避开行内 stopPropagation 子件）→
    EXP 写入 + 同班比价 xrow 显示（跳过夹层 tgrow 找真身）+ aria；
    再点收起 EXP 回 null。"""
    _goto(page)
    _details(page)
    row = page.locator("#ftable tbody tr[data-k]").first
    row.locator("td.price").click()
    page.wait_for_timeout(250)
    assert page.evaluate("EXP !== null && EXP !== undefined")
    xr = page.evaluate(
        "(() => {const r = document.querySelector("
        "'#ftable tr[aria-expanded=\\'true\\']');"
        "let n = r && r.nextElementSibling;"
        "while (n && n.classList.contains('tgrow')) n = n.nextElementSibling;"
        "return n && n.classList.contains('xrow') ? "
        "{shown: n.style.display !== 'none',"
        "head: n.textContent.slice(0, 12)} : null;})()")
    assert xr and xr["shown"], xr
    assert "同班比价" in xr["head"]
    assert page.get_attribute("#ftable tr[aria-expanded='true']",
                              "aria-expanded") == "true"
    row.locator("td.price").click()
    page.wait_for_timeout(250)
    assert page.evaluate("JSON.stringify(EXP)") == "null"

def test_dt04_tg_capsule_and_mutex(page):
    """改期胶囊 togGo：点击 → TGOPEN 写入 + tgrow 微图（15 柱+轴(出发)）
    + 胶囊 aria；与比价互斥（开比价收改期）；Esc 收比价。"""
    _goto(page)
    _details(page)
    row = page.locator("#ftable tbody tr[data-k]:has(.tg)").first
    assert row.count() == 1   # demo 每航线唯一改期胶囊行，首片恰在场
    row.locator(".tg").click()
    page.wait_for_timeout(250)
    assert page.evaluate("TGOPEN !== null && TGOPEN !== undefined")
    tg = page.evaluate(
        "(() => {const cap = document.querySelector('#ftable .tg');"
        "const n = cap.closest('tr').nextElementSibling;"
        "return n.classList.contains('tgrow') ? "
        "{shown: n.style.display !== 'none',"
        "bars: n.querySelectorAll('.tgb').length,"
        "axis: n.querySelector('.tgaxis').textContent} : null;})()")
    assert tg and tg["shown"] and tg["bars"] == 15, tg
    assert "(出发)" in tg["axis"], tg
    assert page.get_attribute("#ftable .tg", "aria-expanded") == "true"
    row.locator("td.price").click()   # 开比价 → 互斥收改期
    page.wait_for_timeout(250)
    assert page.evaluate("EXP !== null")
    assert page.evaluate("JSON.stringify(TGOPEN)") == "null"
    page.keyboard.press("Escape")
    page.wait_for_timeout(250)
    assert page.evaluate("JSON.stringify(EXP)") == "null"

def test_dt05_chip_families_date_route_plat(page):
    """日期/航线/渠道三片族：真实点击 → FLT 集合写入 + 片高亮 + fcnt
    收缩 + fltN 角标亮 1；重置回位（角标隐藏）。"""
    _goto(page)
    _details(page)
    snap = page.evaluate(_SNAP_UI)
    try:
        total = _fcnt(page)[1]
        for sel, key in [("#datechips .chip[data-d]", "dates"),
                         ("#routechips .chip[data-r]", "routes"),
                         ("#platchips .chip[data-p]", "plats")]:
            loc = page.locator(sel).first
            loc.click()
            page.wait_for_timeout(300)
            flt = _flt(page)
            assert len(flt[key]) == 1, (key, flt)
            assert loc.get_attribute("aria-pressed") == "true"
            shown, _t = _fcnt(page)
            assert 0 < shown < total, (key, shown, total)
            assert page.evaluate(
                "document.getElementById('fltN').style.display") == ""
            assert page.inner_text("#fltN") == "1"
            loc.click()   # 再点取消（空集=全部）
            page.wait_for_timeout(250)
        page.locator("#fltwrap button[onclick*='resetFltUI']").click()
        page.wait_for_timeout(300)
        assert page.evaluate(
            "document.getElementById('fltN').style.display") == "none"
    finally:
        _restore(page, snap)

def test_dt06_window_price_search_nostale(page):
    """时段窗/价格上下限/搜索/补位开关：wdep 上午片 → FLT.dep 分钟窗 +
    行出发全落窗内；fpmax fill → FLT.pmax + 收缩；fq fill → FLT.q +
    行名全含关键词；fnostale check → FLT.no（demo 零补位行，计数不变）。"""
    _goto(page)
    _details(page)
    snap = page.evaluate(_SNAP_UI)
    try:
        page.locator("#wdep .schip[data-w='06:00|12:00']").click()
        page.wait_for_timeout(300)
        assert _flt(page)["dep"] == ["06:00", "12:00"]
        deps = page.evaluate(
            "[...document.querySelectorAll('#ftable tbody tr[data-k]')]"
            ".map(r=>r.querySelectorAll('td')[4].textContent)")
        assert deps and all("06:00" <= d < "12:00" for d in deps), deps
        page.locator("#wdep .schip[data-w='']").click()   # 回「不限」
        page.wait_for_timeout(250)
        total = _fcnt(page)[0]
        page.locator("#fpmax").fill("1600")
        page.wait_for_timeout(600)
        assert _flt(page)["pmax"] == 1600
        shown, _t = _fcnt(page)
        assert 0 < shown < total, (shown, total)   # 中转低价档在场、直飞高价档出局
        page.locator("#fpmax").fill("")
        page.wait_for_timeout(500)
        page.locator("#fq").fill("CZ")
        page.wait_for_timeout(600)
        assert _flt(page)["q"] == "CZ"
        names = page.evaluate(
            "[...document.querySelectorAll('#ftable tbody tr[data-k]')]"
            ".map(r=>r.querySelectorAll('td')[3].textContent)")
        assert names and all("CZ" in n for n in names), names[:5]
        page.locator("#fq").fill("")
        page.wait_for_timeout(500)
        before = _fcnt(page)[0]
        page.locator("#fnostale").check()
        page.wait_for_timeout(400)
        assert _flt(page)["no"] is True
        assert _fcnt(page)[0] == before   # demo 零补位行：计数不增不减
        page.locator("#fnostale").uncheck()
        page.wait_for_timeout(300)
    finally:
        _restore(page, snap)

def test_dt07_attr_chips_airline_cabin_airports(page):
    """属性片族 togSet：航司/舱位/出发机场/到达机场 chips → FLT 集合
    写入 + 片高亮 + 结果集随行；机型组=自适应显隐（demo planeSize 单值
    → 整组隐藏，r320 R2 克制律）。"""
    _goto(page)
    _details(page)
    snap = page.evaluate(_SNAP_UI)
    try:
        total = _fcnt(page)[0]
        for sel, key in [("#alchips .chip", "airlines"),
                         ("#cabchips .chip", "cabins"),
                         ("#depchips .chip", "depA"),
                         ("#archips .chip", "arrA")]:
            loc = page.locator(sel).first
            loc.click()
            page.wait_for_timeout(300)
            flt = _flt(page)
            assert len(flt[key]) == 1, (key, flt)
            assert "true" == loc.get_attribute("aria-pressed")
            assert _fcnt(page)[0] <= total
            loc.click()
            page.wait_for_timeout(250)
        ps_disp = page.evaluate(
            "(() => {const w = document.querySelector("
            "'#fltwrap [data-flt=\"ps\"]');"
            "return w ? w.style.display : 'missing';})()")
        ps_vals = page.evaluate(
            "[...new Set(S.users[U].flights.map(f=>f.planeSize).filter(Boolean))]")
        if len(ps_vals) < 2:
            assert ps_disp == "none", (ps_disp, ps_vals)
    finally:
        _restore(page, snap)
