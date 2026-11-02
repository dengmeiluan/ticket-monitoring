# -*- coding: utf-8 -*-
"""r324 入场监控行为钉 · 健康/全局入口：健康格与推送行、脉冲柱，主题三态、快捷键、深链与用户 pills、页脚。

r490 从 test_r324_entry_mon.py 按主题拆出：只为让 xdist 按文件并行，
用例、断言与安全纪律（demo 只读门、不点生产写钮）原样保留。
"""
import pytest  # noqa: F401

from entry_mon_harness import (  # noqa: F401  fixtures 经模块属性注册
    page, srv, _goto, _mtab, _details, _toasts, _toast_last,
    _fcnt, _flt, _restore, _SNAP_UI, _RESTORE_UI)

def test_hl01_cell_click_round_log(page):
    """健康格点击 → 渠道轮日志弹层（GET /api/logtail 真链）：pvTitle
    渠道｜轮次 + logpre 在场 + aria-label 随入口 + demo 底注词面；
    Esc 关闭。"""
    _goto(page)
    _mtab(page, "health")
    page.wait_for_timeout(600)
    assert page.evaluate(
        "document.querySelectorAll('#hbody .hrow').length") >= 5
    page.locator("#hbody .hc:not(.none)").first.click()
    page.wait_for_timeout(900)
    assert page.evaluate(
        "document.getElementById('pvMask').classList.contains('on')")
    title = page.inner_text("#pvTitle")
    # 图标从 emoji 收编为内联 SVG（深色下 emoji 自带彩色底，破坏扁平语言），
    # 所以首字符不再是 📄；改为断言「图标 + 渠道名 + 轮日志」三件。
    assert "轮日志" in title, title
    assert any(k in title for k in ("携程", "去哪儿", "飞猪", "同程", "途牛")), title
    assert page.evaluate(
        "!!document.querySelector('#pvTitle svg use[href=\\\"#i-file\\\"]')"), \
        "标题缺少文件图标"
    assert page.evaluate(
        "!!document.querySelector('#pvMask .logpre')")
    assert page.get_attribute("#pvMask .pvcard", "aria-label") == "渠道轮日志"
    assert "演示模式 · 合成轮日志回放" in page.inner_text("#pvFoot")
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert page.evaluate(
        "!document.getElementById('pvMask').classList.contains('on')")

def test_hl02_push_channels_render(page):
    """推送通道行（renderPushChannels 投影）：demo 钉钉连败在场 →
    「连败 N」红态 + 通道行 ≥1 + 近 24h 词面。"""
    _goto(page)
    _mtab(page, "health")
    page.wait_for_timeout(600)
    body = page.inner_text("#pushhl")
    assert "推送通道 · 近 24h" in body, body[:60]
    rows = page.evaluate(
        "document.querySelectorAll('#pushhl .hrow').length")
    assert rows >= 1
    assert "连败" in body   # demo 钉钉 fail_streak>0

def test_hl03_pulse_bar_jump_health_flash(page):
    """脉冲柱点击 → gotoPulseHealth：切健康子栏 + 失败渠道行辉光
    （hflash 双行）——状态落地非「跳到区域」。"""
    _goto(page)
    _mtab(page, "overview")
    page.wait_for_function(
        "document.querySelectorAll('#pulsebars .pbar').length > 0")
    idx = page.evaluate(
        "[...document.querySelectorAll('#pulsebars .pbar')]"
        ".findIndex(p=>p.dataset.bad)")
    assert idx >= 0   # demo 有失败轮
    page.locator("#pulsebars .pbar").nth(idx).click()
    page.wait_for_timeout(500)
    assert page.evaluate("MONTAB") == "health"
    assert page.evaluate(
        "document.querySelectorAll('#hbody .hflash').length") >= 1

def test_gl01_theme_three_state_cycle(page):
    """主题三态：真实点击 themeBtn 循环 auto→light→dark：localStorage
    jptheme + html data-theme + 按钮 data-mode + aria-label 态名四面同拍。"""
    _goto(page)
    theme0 = page.evaluate("localStorage.getItem('jptheme')")
    assert theme0 in (None, "auto", "light", "dark")
    page.locator("#themeBtn").click()
    page.wait_for_timeout(250)
    assert page.evaluate("localStorage.getItem('jptheme')") == "light"
    assert page.evaluate(
        "document.documentElement.dataset.theme") == "light"
    assert page.get_attribute("#themeBtn", "data-mode") == "light"
    assert "亮色" in page.get_attribute("#themeBtn", "aria-label")
    page.locator("#themeBtn").click()
    page.wait_for_timeout(250)
    assert page.evaluate("localStorage.getItem('jptheme')") == "dark"
    assert page.evaluate(
        "document.documentElement.dataset.theme") == "dark"
    assert page.get_attribute("#themeBtn", "data-mode") == "dark"
    assert "暗色" in page.get_attribute("#themeBtn", "aria-label")

def test_gl02_theme_reload_persist(page):
    """主题持久：dark 落 localStorage → 真实重载 → 暗色保持（html
    data-theme + 按钮 data-mode=dark）；auto 档重载后跟随系统（headless=light）。"""
    _goto(page)
    page.locator("#themeBtn").click()   # →light
    page.locator("#themeBtn").click()   # →dark
    page.wait_for_timeout(250)
    page.reload(wait_until="domcontentloaded")
    page.wait_for_function("typeof S !== 'undefined' && S && S.users")
    page.wait_for_timeout(400)
    assert page.evaluate("localStorage.getItem('jptheme')") == "dark"
    assert page.evaluate(
        "document.documentElement.dataset.theme") == "dark"
    assert page.get_attribute("#themeBtn", "data-mode") == "dark"

def test_gl03_hotkey_views_and_tabs(page):
    """快捷键 1/2 视图 + 3-6 分栏（含配置视图直达——gotoMonTab 收口
    路径）：keyboard.press 真按，逐面断言 VIEW/MONTAB/pane。"""
    _goto(page)
    page.evaluate("document.activeElement && document.activeElement.blur()")
    page.keyboard.press("2")
    page.wait_for_timeout(400)
    assert page.evaluate("VIEW") == "cfg"
    assert page.is_visible("#cfgview")
    page.keyboard.press("5")
    page.wait_for_timeout(500)
    assert page.evaluate("VIEW") == "mon"
    assert page.evaluate("MONTAB") == "details"
    page.keyboard.press("4")
    page.wait_for_timeout(400)
    assert page.evaluate("MONTAB") == "trend"
    page.keyboard.press("3")
    page.wait_for_timeout(400)
    assert page.evaluate("MONTAB") == "overview"
    page.keyboard.press("6")
    page.wait_for_timeout(400)
    assert page.evaluate("MONTAB") == "health"
    page.keyboard.press("1")
    page.wait_for_timeout(300)
    assert page.evaluate("VIEW") == "mon"
    assert page.is_visible("#monview")

def test_gl04_hotkey_slash_focus_search(page):
    """/ 快捷键：真按 → 切明细 + #fq 聚焦选中；接续真实键入 → FLT.q
    写入 + 结果集随行（完整输入管线）。"""
    _goto(page)
    page.evaluate("document.activeElement && document.activeElement.blur()")
    page.keyboard.press("/")
    page.wait_for_timeout(500)
    assert page.evaluate("MONTAB") == "details"
    assert page.evaluate(
        "document.activeElement && document.activeElement.id") == "fq"
    page.keyboard.type("CZ")
    page.wait_for_timeout(700)
    assert page.evaluate("JSON.stringify(FLT.q)") == '"CZ"'
    names = page.evaluate(
        "[...document.querySelectorAll('#ftable tbody tr[data-k]')]"
        ".map(r=>r.querySelectorAll('td')[3].textContent)")
    assert names and all("CZ" in n for n in names), names[:5]

def test_gl05_esc_cascade_drawer(page):
    """Esc 级联（抽屉支路，≤760 真实抽屉语境）：视口收窄至 390 →
    fltBtn 现身（宽档 fbar 常驻无此钮）→ 真实点击开抽屉（.open+aria）
    → Esc 关闭 + aria 回写 false + 焦点归还 fltBtn（setFltOpen 单源，
    旁路曾绕过）。"""
    _goto(page)
    _details(page)
    page.set_viewport_size({"width": 390, "height": 800})
    page.wait_for_timeout(400)
    # _details opened the desktop filter row; close it so this test starts
    # from the real mobile drawer state before clicking fltBtn.
    page.evaluate("()=>{const fb=document.querySelector('.fbar');"
                  "if(fb&&fb.classList.contains('open'))setFltOpen(false);}")
    page.wait_for_timeout(200)
    assert page.is_visible("#fltBtn")   # ≤760 抽屉唯一入口
    page.locator("#fltBtn").click()
    page.wait_for_timeout(400)
    assert "open" in (page.get_attribute(".fbar", "class") or "")
    assert page.get_attribute("#fltBtn", "aria-expanded") == "true"
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert "open" not in (page.get_attribute(".fbar", "class") or "")
    assert page.get_attribute("#fltBtn", "aria-expanded") == "false"
    assert page.evaluate(
        "document.activeElement && document.activeElement.id") == "fltBtn"
    page.set_viewport_size({"width": 1440, "height": 900})

def test_gl06_deeplink_startup(page):
    """URL 深链启动恢复：/#details 与 /#trend/u0（双段）直达对应子栏 +
    hash 保持；/#cfg 直达配置视图。"""
    page.goto(page._r324_base + "/#details", wait_until="domcontentloaded")
    page.wait_for_function("typeof S !== 'undefined' && S && S.users")
    page.wait_for_timeout(400)
    assert page.evaluate("MONTAB") == "details"
    assert page.evaluate("location.hash") == "#details"
    page.goto(page._r324_base + "/#trend/u0", wait_until="domcontentloaded")
    page.wait_for_function("typeof S !== 'undefined' && S && S.users")
    page.wait_for_timeout(400)
    assert page.evaluate("MONTAB") == "trend"
    assert page.evaluate("VIEW") == "mon"
    assert page.evaluate("location.hash") == "#trend/u0"
    page.goto(page._r324_base + "/#cfg", wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    assert page.evaluate("VIEW") == "cfg"
    assert page.is_visible("#cfgview")

def test_gl07_hashchange_live_and_guard(page):
    """活页 hashchange 消费：手改 hash → 子栏跟随 + 用户段回写；
    越界 /u9 守卫忽略（U 不变；hash 段保留=W30 在案备案）。"""
    _goto(page)
    page.evaluate("location.hash='#health'")
    page.wait_for_timeout(400)
    assert page.evaluate("MONTAB") == "health"
    assert page.evaluate("location.hash") == "#health/u0"
    page.evaluate("location.hash='#details/u9'")
    page.wait_for_timeout(400)
    assert page.evaluate("U") == 0
    assert page.evaluate("MONTAB") == "details"

def test_gl08_user_pills_single_user(page):
    """用户 pills/吸顶 chip：r368 起单用户也常显当前用户范围（监控视图
    按用户过滤的口径可见；越界深链守卫见 gl07）。"""
    _goto(page)
    assert page.evaluate("(S.users||[]).length") == 1
    assert not page.is_visible("#userPills")
    assert page.is_visible("#mtabUser")
    assert "👤" in page.inner_text("#mtabUser")

def test_gl09_footer_github_and_kbd(page):
    """页脚：GitHub 链接 target=_blank + rel=noopener（真实点击会离站，
    只钉属性面）+ 快捷键教学词面在场。"""
    _goto(page)
    assert page.get_attribute("#foot a", "target") == "_blank"
    assert "noopener" in (page.get_attribute("#foot a", "rel") or "")
    assert page.evaluate("document.querySelectorAll('#foot .kbd').length") >= 4
