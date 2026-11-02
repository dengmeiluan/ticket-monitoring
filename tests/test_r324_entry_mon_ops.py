# -*- coding: utf-8 -*-
"""r324 入场监控行为钉 · 弹层与运维入口：推送预览、推送记录、立即扫描/R 双拍 403、登录卡面板开合。

r490 从 test_r324_entry_mon.py 按主题拆出：只为让 xdist 按文件并行，
用例、断言与安全纪律（demo 只读门、不点生产写钮）原样保留。
"""
import pytest  # noqa: F401

from entry_mon_harness import (  # noqa: F401  fixtures 经模块属性注册
    page, srv, _goto, _mtab, _details, _toasts, _toast_last,
    _fcnt, _flt, _restore, _SNAP_UI, _RESTORE_UI)

def test_pv01_preview_open_esc_focus_return(page):
    """推送预览（demo /api/preview 豁免门=真 POST 全链）：真实点击 →
    🚨 标题 + 正文链接 + aria-label/底注随入口；Esc 关闭 + 焦点归还
    开启者 + 滚动锁解除。"""
    _goto(page)
    with page.expect_response(lambda r: "/api/preview" in r.url,
                              timeout=30000):
        page.locator("#pvBtn").click()
    page.wait_for_timeout(400)
    assert page.inner_text("#pvTitle").startswith("🚨")
    assert page.evaluate(
        "document.querySelectorAll('#pvBody a').length") > 0
    assert page.get_attribute("#pvMask .pvcard", "aria-label") == "钉钉推送预览"
    assert "近似渲染" in page.inner_text("#pvFoot")
    assert page.evaluate("document.body.style.overflow") == "hidden"
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert page.evaluate(
        "!document.getElementById('pvMask').classList.contains('on')")
    assert page.evaluate("document.activeElement && "
                         "document.activeElement.id") == "pvBtn"
    assert page.evaluate("document.body.style.overflow") == ""

def test_pv02_preview_tab_focus_trap(page):
    """弹层 Tab 焦点圈闭：关闭钮 Shift+Tab → 尾焦点件；再 Tab → 首件
    （不逃逸背景页）。"""
    _goto(page)
    with page.expect_response(lambda r: "/api/preview" in r.url,
                              timeout=30000):
        page.locator("#pvBtn").click()
    page.wait_for_timeout(400)
    page.locator("#pvClose").focus()
    page.keyboard.press("Shift+Tab")
    page.wait_for_timeout(150)
    last_tag = page.evaluate(
        "document.activeElement.tagName + '|' + document.activeElement.className")
    assert last_tag.split("|")[0] == "A", last_tag   # 尾=正文链接
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)

def test_pv03_pushlog_open_expand(page):
    """推送记录弹层：真实点击 → 📨 标题 + 条目在场 + aria-label/底注随
    入口；点击条目展开全文（display 切换零插拔）；Esc 关闭。"""
    _goto(page)
    page.locator("button[onclick*='pushLog']").click()
    page.wait_for_timeout(800)
    assert "推送记录" in page.inner_text("#pvTitle")
    assert page.get_attribute("#pvMask .pvcard", "aria-label") == "推送记录"
    assert "合成推送记录回放" in page.inner_text("#pvFoot")   # demo 底注词面
    n = page.evaluate("document.querySelectorAll('.plitem').length")
    assert n >= 1
    page.locator(".plitem").first.click()
    page.wait_for_timeout(200)
    assert page.evaluate(
        "document.querySelector('.pldesp').style.display") == ""
    page.keyboard.press("Escape")
    page.wait_for_timeout(250)
    assert page.evaluate(
        "!document.getElementById('pvMask').classList.contains('on')")

def test_ops01_run_button_arming_then_403(page):
    """立即扫描（api 双拍确认机制完整走通）：一拍=arming 态词面锁定；
    二拍=真 POST /api/run → demo 只读门 403 → 失败 toast 词面钉 +
    按钮复原（真实失败分支，无任何真实副作用）。"""
    _goto(page)
    btn = page.locator("#opscard button").first
    btn.click()
    page.wait_for_timeout(200)
    assert page.evaluate(
        "document.querySelector('#opscard button').dataset.arming") == "1"
    assert page.inner_text("#opscard button") == "⚠ 再点一次确认"
    btn.click()
    page.wait_for_timeout(1200)
    assert "❌ 失败: 演示模式只读——下载源码或 zip 即可真跑" in _toasts(page), \
        _toasts(page)
    assert page.inner_text("#opscard button") == "立即扫描一轮"
    assert page.evaluate(
        "document.querySelector('#opscard button').dataset.arming") is None

def test_ops02_hotkey_r_two_step_403(page):
    """R 快捷键立即扫描（keyRun 两段确认）：一按=警告 toast；三秒内
    二按=真 POST → 403 失败 toast 词面钉。"""
    _goto(page)
    page.evaluate("document.activeElement && document.activeElement.blur()")
    page.keyboard.press("r")
    page.wait_for_timeout(250)
    assert "⚠ 再按一次 R 确认立即扫描全部航线" in _toasts(page)
    page.keyboard.press("r")
    page.wait_for_timeout(1200)
    assert "❌ 失败: 演示模式只读——下载源码或 zip 即可真跑" in _toasts(page), \
        _toasts(page)

def test_login_panel_open_and_leave(page):
    """配置页登录卡面板：cnav 真实点击打开 → 5 渠道卡 + 「弹窗登录」
    词面在场（绝不点击——loginStart 生产态弹真窗）；切走=取消语义
    （面板隐藏、无任何 POST）。"""
    _goto(page)
    page.locator("#navCfg").click()
    page.wait_for_timeout(1500)
    page.locator("#cfgnav .cnav[data-p='login']").click()
    page.wait_for_timeout(800)
    assert page.is_visible("#panel-login")
    assert page.evaluate(
        "document.querySelectorAll('#loginRows .lgcard').length"
        ) == len(__import__("crawlers").REGISTRY)
    assert "弹窗登录" in page.inner_text("#loginRows")
    page.locator("#navMon").click()
    page.wait_for_timeout(400)
    assert page.evaluate("VIEW") == "mon"
    assert not page.is_visible("#cfgview")

def test_empty01_all_suspended_hero(page):
    """停用全部航线空态（route 拦截 /api/state 构造 suspended 载荷=
    load→render 网络入口全链，不 POST、不改服务端）：hero ⏸️ 词面 +
    停用清单 + pill「已全停用」+ montabs/opscard/图表/脉冲全回收 +
    前往配置启用按钮。"""
    import json
    import urllib.request
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    st = json.loads(op.open(page._r324_base + "/api/state", timeout=3)
                    .read().decode("utf-8"))
    u0 = st["users"][0]
    emp = dict(st)
    emp["users"] = []
    emp["suspended"] = [{"name": u0["name"], "n": len(u0["routesArr"]),
                         "routesTxt": u0["routesTxt"]}]

    def _route(route, request):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(emp, ensure_ascii=False))
    page.route("**/api/state", _route)
    try:
        page.goto(page._r324_base + "/", wait_until="domcontentloaded")
        page.wait_for_timeout(900)
        hero = page.evaluate(
            "(() => {const h = document.querySelector('#users .hero');"
            "return h ? h.textContent : '';})()")
        assert "航线已全部停用" in hero, hero[:80]
        assert u0["name"] in hero   # 停用清单词面（与「从未配置」分立）
        assert page.inner_text("#pill") == "已全停用"
        assert page.evaluate(
            "document.getElementById('montabs').style.display") == "none"
        assert page.evaluate(
            "document.getElementById('opscard').style.display") == "none"
        assert page.evaluate(
            "document.getElementById('chartcard').style.display") == "none"
        assert page.evaluate(
            "document.getElementById('pulsecard').style.display") == "none"
        assert page.evaluate(
            "(() => {const b = [...document.querySelectorAll('#users button')]"
            ".find(b => b.textContent.indexOf('前往配置启用') >= 0);"
            "return !!b;})()")
    finally:
        page.unroute("**/api/state")
