# -*- coding: utf-8 -*-
"""r324 入场监控行为钉 · 明细面入口（dt08–dt13 + 空态）：更多筛选八维、自适应显隐、重置清机场、CSV、滚动切片、首列吸附。

r490 从 test_r324_entry_mon.py 按主题拆出：只为让 xdist 按文件并行，
用例、断言与安全纪律（demo 只读门、不点生产写钮）原样保留。
"""
import pytest  # noqa: F401

from entry_mon_harness import (  # noqa: F401  fixtures 经模块属性注册
    page, srv, _goto, _mtab, _details, _toasts, _toast_last,
    _fcnt, _flt, _restore, _SNAP_UI, _RESTORE_UI)

def test_dt08_switch_few_safe_adaptive_hidden(page):
    """余票紧张/隐藏限购开关（demo 在场维度）：check → FLT 写入 + 收缩；
    经停/共享组=自适应显隐（demo 零 stop/share 行 → 整组隐藏）。"""
    _goto(page)
    _details(page)
    snap = page.evaluate(_SNAP_UI)
    try:
        total = _fcnt(page)[0]
        page.locator("#ffew").check()
        page.wait_for_timeout(400)
        assert _flt(page)["few"] is True
        assert 0 < _fcnt(page)[0] < total
        page.locator("#ffew").uncheck()
        page.wait_for_timeout(300)
        page.locator("#fsafe").check()
        page.wait_for_timeout(400)
        assert _flt(page)["safe"] is True
        assert _fcnt(page)[0] < total
        page.locator("#fsafe").uncheck()
        page.wait_for_timeout(300)
        for grp in ("nostop", "noshare"):
            has = page.evaluate(
                "S.users[U].flights.some(f=>f.%s)" % ("stop" if grp == "nostop"
                                                      else "shareCarrier"))
            disp = page.evaluate(
                "(() => {const w = document.querySelector("
                "'#fltwrap [data-flt=\"%s\"]');"
                "return w ? w.style.display : 'missing';})()" % grp)
            if not has:
                assert disp == "none", (grp, disp)
    finally:
        _restore(page, snap)

def test_dt09_moreflt_eight_dims(page):
    """更多筛选八维：真实展开（aria+箭头词）→ 时长上限/准点率/机龄三
    数值框 fill + 托运/餐食/廉航三开关 check → FLT 写入 + 结果集随行 +
    morefltN 角标=生效数；经停/共享/跨天/儿童=自适应显隐（demo 零值）。"""
    _goto(page)
    _details(page)
    snap = page.evaluate(_SNAP_UI)
    try:
        total = _fcnt(page)[0]
        page.locator("#morefltBtn").click()
        page.wait_for_timeout(250)
        assert page.evaluate(
            "document.getElementById('moreflt').style.display") == ""
        assert page.get_attribute("#morefltBtn", "aria-expanded") == "true"
        page.locator("#fdurmax").fill("400")
        page.wait_for_timeout(600)
        assert _flt(page)["durmax"] == 400
        mid = _fcnt(page)[0]
        assert 0 < mid < total
        assert page.evaluate(
            "[...document.querySelectorAll('#ftable tbody tr[data-k] .tag')]"
            ".every(t=>t.textContent !== '中转')")
        page.locator("#fprate").fill("87")
        page.wait_for_timeout(600)
        assert _flt(page)["prate"] == 87
        prat = _fcnt(page)[0]
        assert 0 < prat < mid   # demo 仅 ctrip 首行 prate='87'
        page.locator("#fage").fill("7")
        page.wait_for_timeout(600)
        assert _flt(page)["age"] == 7
        assert 0 < _fcnt(page)[0] <= prat
        for cid, key in [("fbag", "bag"), ("fmeal", "meal"),
                         ("fnolcc", "nolcc")]:
            page.locator("#" + cid).check()
            page.wait_for_timeout(400)
            assert _flt(page)[key] is True
            page.locator("#" + cid).uncheck()
            page.wait_for_timeout(300)
        badge = page.evaluate(
            "(() => {const b = document.getElementById('morefltN');"
            "return [b.style.display, b.textContent];})()")
        assert badge[0] == "" and badge[1] == "3", badge   # 时长/准点/机龄
        for grp, probe in [("cross", "Number(f.crossDayN)>0"),
                           ("child", "f.childPrice!=null")]:
            has = page.evaluate("S.users[U].flights.some(f=>%s)" % probe)
            disp = page.evaluate(
                "(() => {const l = document.getElementById("
                "{'cross':'fcross','child':'fchild'}['%s']);"
                "return l ? l.closest('.flab').style.display : 'missing';"
                "})()" % grp)
            if not has:
                assert disp == "none", (grp, disp)
        page.locator("#fltwrap button[onclick*='resetFltUI']").click()
        page.wait_for_timeout(300)
        assert page.evaluate(
            "document.getElementById('morefltN').style.display") == "none"
    finally:
        _restore(page, snap)


# r324 DT-10 已修复转正（resetFlt 补 depA/arrA 复位 + updFltN 入册计数）：
# 原 RED-1 xfail(strict) 在修复落地当日 XPASS，摘标记转常态回归钉。

def test_dt10_red_reset_must_clear_airport_filters(page):
    """RED-1 钉：机场 chip 点亮 → 重置筛选与排序 → FLT.depA/arrA 必须清
    空 + 片熄灭 + 结果集复位。当前实现三面全劈叉。"""
    _goto(page)
    _details(page)
    page.locator("#depchips .chip").first.click()
    page.wait_for_timeout(300)
    assert _flt(page)["depA"], "前置：depA 已写"
    assert _fcnt(page)[0] < _fcnt(page)[1]
    page.locator("#fltwrap button[onclick*='resetFltUI']").click()
    page.wait_for_timeout(400)
    flt = _flt(page)
    assert flt["depA"] == [] and flt["arrA"] == [], flt
    assert page.evaluate(
        "document.querySelector('#depchips .chip')"
        ".classList.contains('on')") is False
    assert _fcnt(page)[0] == _fcnt(page)[1]

def test_dt11_csv_export_download(page):
    """CSV 导出：真实点击 → download 事件（文件名 flights_YYYYMMDD_HHMM
    .csv）+ 表头首列「价格」+ 成功 toast 行数与 fcnt 一致。"""
    import re
    _goto(page)
    _details(page)
    shown, _t = _fcnt(page)
    with page.expect_download(timeout=8000) as dl:
        page.locator("#fltwrap button[onclick*='expCsv']").click()
    d = dl.value
    assert re.match(r"flights_\d{8}_\d{4}\.csv$", d.suggested_filename), \
        d.suggested_filename
    path = d.path()
    with open(path, encoding="utf-8-sig") as fh:
        head = fh.readline().strip()
    assert head.startswith('"价格"'), head[:40]
    assert ("📤 已导出 %d 行 CSV" % shown) in _toasts(page), _toasts(page)

def test_dt12_scroll_chunk_integrity(page):
    """滚动续载完整性：真实滚轮滚底 → 续载补全至全量（DOM 行数=
    fcnt=_ROWS.length）、已渲片数覆盖全量（片数随数据面走——demo
    115 班单片形态已成 185 班两片，硬编码 NDRAW=1 在扩容当日即红），
    零错（完整性=不丢行不报错）。"""
    _goto(page)
    _details(page)
    shown, _t = _fcnt(page)
    page.locator("#tablecard .tw").hover()
    page.mouse.wheel(0, 20000)   # 真实滚轮路径滚到底
    page.wait_for_timeout(400)
    n = page.evaluate(
        "document.querySelectorAll('#ftable tbody tr[data-k]').length")
    assert n == shown == page.evaluate("_ROWS.length"), (n, shown)
    assert page.evaluate("_NDRAW * _CHUNK") >= page.evaluate(
        "_ROWS.length"), (page.evaluate("_NDRAW"),
                          page.evaluate("_ROWS.length"))

def test_dt13_sticky_first_column(page):
    """首列吸附：价格格/表头 position:sticky + left:0 + z-index 在场
    （投影面钉；1440 无横滚溢出，滚动路径由 390 档钉组覆盖）。"""
    _goto(page)
    _details(page)
    st = page.evaluate(
        "(() => {const th = document.querySelector('#ftable th');"
        "const td = document.querySelector('#ftable td');"
        "const a = getComputedStyle(th), b = getComputedStyle(td);"
        "return [a.position, a.left !== 'auto', a.zIndex !== 'auto',"
        "b.position];})()")
    assert st[0] == "sticky" and st[3] == "sticky", st
    assert st[1] and st[2], st
