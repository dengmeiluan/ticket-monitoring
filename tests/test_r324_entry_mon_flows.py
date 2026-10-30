# -*- coding: utf-8 -*-
"""r324 入场监控行为钉 · 概览/走势入口：kpisum 链、mchip 跳转、KPI 外链窗、ovAlert，走势航线片/范围/模式/图例/十字线/日历。

r490 从 test_r324_entry_mon.py 按主题拆出：只为让 xdist 按文件并行，
用例、断言与安全纪律（demo 只读门、不点生产写钮）原样保留。
"""
import pytest  # noqa: F401

from entry_mon_harness import (  # noqa: F401  fixtures 经模块属性注册
    page, srv, _goto, _mtab, _details, _toasts, _toast_last,
    _fcnt, _flt, _restore, _SNAP_UI, _RESTORE_UI)

def test_ov01_kpisum_details_link(page):
    """概览卡「查看明细 ▸」：真实点击 → 明细子栏 pane 显示。
    r419 起动作从 kpisum 句尾移到卡头 .uact2（动作贴着对象），
    断言仍钉「同一个入口真的能跳过去」，只改定位点。"""
    _goto(page)
    link = page.locator("#users .ucard .uact2 a", has_text="查看明细").first
    assert link.count() >= 1
    link.click()
    page.wait_for_timeout(400)
    assert page.evaluate("MONTAB") == "details"
    assert page.is_visible("#montab-details")
    assert page.evaluate("location.hash").startswith("#details")

def test_ov02_kpisum_trend_link(page):
    """概览卡「走势 ▸」：真实点击 → 走势子栏（jumpRowTrend('') 空路由
    =当前视图，不写 st.i——chartTitle 保持首航线）。"""
    _goto(page)
    t0 = page.evaluate("document.getElementById('chartTitle').textContent")
    link = page.locator("#users .ucard .uact2 a", has_text="走势").first
    link.click()
    page.wait_for_timeout(600)
    assert page.evaluate("MONTAB") == "trend"
    assert page.is_visible("#chartcard")
    t1 = page.evaluate("document.getElementById('chartTitle').textContent")
    assert t0.split("·")[0] == t1.split("·")[0], (t0, t1)   # 航线不换

def test_ov03_mchip_jump_details_prefilter(page):
    """渠道片 mchip：真实点击 → 明细子栏 + FLT.plats 预置该渠道 +
    platchips 亮片 + 结果集收缩 + 教学 toast（含重置告知）。"""
    _goto(page)
    name = page.evaluate(
        "document.querySelector('.mchip').textContent.trim().split(/\\s+/)[0]")
    page.locator(".mchip").first.click()
    page.wait_for_timeout(400)
    assert page.evaluate("MONTAB") == "details"
    flt = _flt(page)
    assert flt["plats"] == [name], flt
    on = page.evaluate(
        "[...document.querySelectorAll('#platchips .chip')]"
        ".filter(c=>c.classList.contains('on')).map(c=>c.dataset.p)")
    assert on == [name], on
    shown, total = _fcnt(page)
    assert 0 < shown < total, (shown, total)
    assert ("仅看 %s 明细" % name) in _toast_last(page), _toasts(page)

def test_ov04_kpi_numlink_popup_blocked(page, ):
    """KPI numlink：真实点击 → 新窗（外链 route 拦截下 popup 仍真实
    创建）；锚 target=_blank + rel=noopener + href=data-href 一致。"""
    _goto(page)
    ctx = page.context
    ctx.route("**/*", lambda r: r.abort()
              if r.request.url.startswith("http")
              and "127.0.0.1" not in r.request.url else r.continue_())
    a = page.locator("a.numlink").first
    href = a.get_attribute("href")
    data_href = page.evaluate(
        "document.querySelector('a.numlink').closest('.kpi').dataset.href")
    assert href == data_href   # 卡 href 与整卡 data-href 同一目标
    assert a.get_attribute("target") == "_blank"
    assert "noopener" in (a.get_attribute("rel") or "")
    with page.expect_popup(timeout=5000) as pop:
        a.click()
    pp = pop.value
    assert pp != page   # 真实新开一窗（外站被拦截故停在错误页）
    pp.close()
    ctx.unroute("**/*")

def test_ov05_kpi_card_click_popup(page):
    """KPI 整卡（.kpi.clk）：真实点击卡面非锚区 → window.open(data-href)
    真实弹窗；无链接卡不带 clk（不可点卡零假 affordance）。"""
    _goto(page)
    n_clk = page.evaluate("document.querySelectorAll('.kpi.clk').length")
    n_kpi = page.evaluate("document.querySelectorAll('#users .kpi').length")
    assert n_clk >= 1
    assert n_clk <= n_kpi
    ctx = page.context
    ctx.route("**/*", lambda r: r.abort()
              if r.request.url.startswith("http")
              and "127.0.0.1" not in r.request.url else r.continue_())
    card = page.locator(".kpi.clk").first
    want = card.get_attribute("data-href")
    with page.expect_popup(timeout=5000) as pop:
        card.locator(".lab").click()   # 非锚区（锚点自带跳过守卫）
    pp = pop.value
    assert pp != page
    pp.close()
    ctx.unroute("**/*")

def test_ov06_ovalert_sentinel_state(page):
    """ovAlert 哨：demo 推送连败在场 → 红帽可见 + aria/title 词面
    （哨是显隐投影件无点击动作——audit W27 双源合成）。"""
    _goto(page)
    assert page.evaluate(
        "document.getElementById('ovAlert').style.display") == ""
    assert page.get_attribute("#ovAlert", "aria-label") == \
        "采集或推送通道有异常，详情见渠道健康"
    assert "渠道健康" in page.get_attribute("#ovAlert", "title")

def test_tr01_chart_chip_switch_route(page):
    """走势航线片 togChart：真实点击第 2 片 → CHR.i 写入 + 片高亮 +
    chartTitle 与 calTitle 同拍同航线（F1 劈叉回归面）+ 日历格在场。"""
    _goto(page)
    _mtab(page, "trend")
    page.wait_for_timeout(400)
    chips = page.locator("#chartRoutes .chip")
    assert chips.count() >= 2
    want = chips.nth(1).text_content().strip()
    chips.nth(1).click()
    page.wait_for_timeout(500)
    chr_st = page.evaluate("JSON.stringify(CHR)")
    assert '"i":1' in chr_st, chr_st
    on_idx = page.evaluate(
        "[...document.querySelectorAll('#chartRoutes .chip')]"
        ".findIndex(c=>c.classList.contains('on'))")
    assert on_idx == 1, on_idx
    title = page.evaluate("document.getElementById('chartTitle').textContent")
    cal = page.evaluate("document.getElementById('calTitle').textContent")
    assert want in title, (want, title)
    assert cal == title.split("·", 1)[1].strip(), (cal, title)   # F1：日历随拍
    assert page.evaluate(
        "document.querySelectorAll('#calgrid .calcell').length") > 0

def test_tr02_range_chip(page):
    """范围片 setRange：真实点击 7 天 → CHR.r + 片高亮 + 标题 7 天 +
    aria-pressed 播报（r257 P3-2）。"""
    _goto(page)
    _mtab(page, "trend")
    page.locator("#rng7d").click()
    page.wait_for_timeout(600)
    assert page.evaluate("JSON.stringify(CHR)").find('"r":"7d"') >= 0
    assert page.evaluate("document.getElementById('rng7d').classList"
                         ".contains('on')")
    assert "7天" in page.evaluate(
        "document.getElementById('chartTitle').textContent")
    assert page.get_attribute("#rng7d", "aria-pressed") == "true"

def test_tr03_mode_chip_kline_legend(page):
    """模式片 setMode：K线 → CHR.m + 折线色票隐藏（图例-数据一致）+
    ringNote K线专有词面；切回折线恢复。"""
    _goto(page)
    _mtab(page, "trend")
    page.locator("#mdK").click()
    page.wait_for_timeout(500)
    assert page.evaluate("JSON.stringify(CHR)").find('"m":"kline"') >= 0
    assert page.evaluate(
        "document.getElementById('mdK').classList.contains('on')")
    assert page.evaluate(
        "document.getElementById('lgDirect').style.display") == "none"
    assert "K线" in page.evaluate(
        "document.getElementById('ringNote').textContent")
    page.locator("#mdLine").click()
    page.wait_for_timeout(400)
    assert page.evaluate(
        "document.getElementById('lgDirect').style.display") == ""

def test_tr04_canvas_hover_crosshair(page):
    """canvas hover 十字线（真实鼠标路径）：HPTS 读数状态写入（DOM 快照
    看不到的 canvas 交互，状态面+无错双断言）。"""
    _goto(page)
    _mtab(page, "trend")
    page.wait_for_timeout(400)
    box = page.locator("#chart").bounding_box()
    page.mouse.move(box["x"] + box["width"] * 0.5,
                    box["y"] + box["height"] * 0.5)
    page.wait_for_timeout(300)
    assert page.evaluate("!!HPTS")

def test_tr05_canvas_click_jump_details_lock_date(page):
    """canvas 点击 → 该轮明细（jumpTrendDetail→jumpCalDate 全链）：
    MONTAB 切明细 + FLT.dates/routes 双锁 + 重置告知 toast +
    焦点交接明细 tab。"""
    _goto(page)
    _mtab(page, "trend")
    page.wait_for_timeout(400)
    want_date = page.evaluate("curRoute().r.date")
    want_route = page.evaluate(
        "(curRoute().r.label||'').replace(/\\s+\\d{2}\\/\\d{2}\\s*$/,'')")
    box = page.locator("#chart").bounding_box()
    page.mouse.click(box["x"] + box["width"] * 0.5,
                     box["y"] + box["height"] * 0.5)
    page.wait_for_timeout(500)
    assert page.evaluate("MONTAB") == "details"
    flt = _flt(page)
    assert flt["dates"] == [want_date], (flt["dates"], want_date)
    assert flt["routes"] == [want_route], (flt["routes"], want_route)
    assert "已重置现有筛选，仅看该日期明细" in _toasts(page)
    assert page.evaluate(
        "document.activeElement && document.activeElement.dataset.t") == \
        "details"

def test_tr06_calendar_projection(page):
    """价格日历投影：calTitle 与走势航线一致 + 7 天洞察统计词面 +
    格数 14-15（demo 双周窗）；日历格纯展示（audit 撤案 #5 在案，
    无假 affordance——无 role=button）。"""
    _goto(page)
    _mtab(page, "trend")
    page.wait_for_timeout(400)
    title = page.evaluate("document.getElementById('chartTitle').textContent")
    cal = page.evaluate("document.getElementById('calTitle').textContent")
    assert cal and cal in title, (cal, title)
    stats = page.evaluate("document.getElementById('calStats').textContent")
    assert "近7天最低" in stats and "日均" in stats, stats
    n = page.evaluate("document.querySelectorAll('#calgrid .calcell').length")
    assert n in (14, 15), n
    assert page.evaluate(
        "!!document.querySelector('#calgrid .calcell[role=\\'button\\']')") \
        is False
