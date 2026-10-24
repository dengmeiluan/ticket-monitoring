# -*- coding: utf-8 -*-
"""真实浏览器脚本回归；全部请求在虚构域名截获，不启动或访问采集服务。"""
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

import pytest


PLATFORMS = ("qunar", "ctrip", "tongcheng", "tuniu", "fliggy")
HISTORY = {
    "rounds": [{"ts": "2026-10-22 09:00", "plats": {
        "qunar": {"s": "fail", "ok": 0, "tot": 1, "cal": 0, "detail": 0,
                  "need_login": True, "note": "需登录 · 会话失效"},
    }}],
    "stats": {"qunar": {"ok": 0, "part": 0, "fail": 1, "maint": 0,
                         "rate": 0, "cal": 0, "detail": 0, "auth": 1}},
    "push": {"channels": {}},
}


def _payload(status="saved"):
    def channel(value):
        return {
            "status": value, "needs_login": value == "login_required",
            "saved": True, "active": value == "active", "saving": value == "saving",
            "pending": value == "pending", "saved_at": 1792638000,
            "error": "会话保存失败" if value == "save_error" else "",
            "scopes": {}, "stale": False, "health_need_login": False,
        }

    return {"ok": True, "plats": {
        p: channel(status if p == "qunar" else "saved") for p in PLATFORMS
    }}


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as driver:
        if not Path(driver.chromium.executable_path).exists():
            pytest.skip("Chromium 二进制未安装")
        browser = driver.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def ui(browser):
    import webui

    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    page.set_default_timeout(3000)
    # 每个用例显式驱动刷新；阻止全局周期轮询打乱请求先后顺序。
    page.add_init_script("window.setInterval = () => 1;")
    calls = Counter()
    errors = []
    writes = []
    state = {"login": _payload(), "login_code": 200, "state_code": 200}
    page.on("pageerror", lambda error: errors.append(str(error)))

    def route(request):
        path = urlsplit(request.request.url).path
        calls[path] += 1
        if request.request.method != "GET":
            writes.append((request.request.method, path))
            request.fulfill(status=405, json={"ok": False})
        elif path == "/":
            request.fulfill(content_type="text/html; charset=utf-8",
                            body=webui._page_html("ui-test"))
        elif path == "/api/state":
            if state["state_code"] == 304:
                request.fulfill(status=304, headers={"ETag": '"unchanged"'})
            else:
                request.fulfill(json={"users": [], "demo": False, "version": "ui-test"},
                                headers={"ETag": '"unchanged"'})
        elif path == "/api/login-state":
            request.fulfill(status=state["login_code"], json=state["login"])
        elif path == "/api/health":
            request.fulfill(json={"rounds": [], "stats": {}, "push": {"channels": {}}})
        elif path == "/api/pulse":
            request.fulfill(json={"rounds": []})
        elif path == "/api/config":
            request.fulfill(json={"users": [], "city": {}, "cityx": {},
                                  "intl": {"map": {}, "hot": [], "mainland": []}})
        else:
            request.fulfill(json={"ok": True, "items": [], "rows": []})

    page.route("**/*", route)
    page.goto("http://channel-ui.test/", wait_until="networkidle")
    page.evaluate("""() => {
        SRX.probe = {rows: [{from:'SHA', to:'NRT', date:'2026-11-16',
          intl:true, platKey:'tuniu', code:'MU523', depTime:'09:05', arrTime:'13:15',
          price:719, isStale:false, isCal:false}], channels:{}};
        SRX.pair = 'SHA|NRT'; SRX.date = '2026-11-16';
    }""")
    yield page, state, calls
    context.close()
    assert not writes, f"页面不应发起写入请求：{writes}"
    assert not errors, f"页面 JavaScript 错误：{errors}"


def _require_shared_loader(page):
    assert page.evaluate("typeof loadChannelState") == "function", (
        "当前认证状态缺少跨页面共享加载入口")


def _render_faces(page):
    page.evaluate("""async history => {
        await loadLogin(null, true);
        await srcAccessState(true);
        renderHealth(history);
        srxRenderCapbar();
    }""", HISTORY)
    return page.evaluate("""() => {
        const card = [...document.querySelectorAll('.lgcard')].find(
          x => x.querySelector('.lgnm')?.textContent === '去哪儿');
        return {auth:channelAuthView('qunar'), config:card?.textContent || '',
          source:document.querySelector('#scQState').textContent,
          search:document.querySelector('#srxCapbar')?.textContent || '',
          actionHidden:document.querySelector('#hauthact').hidden,
          actionPlatform:document.querySelector('#hauthact').dataset.p,
          historyTitle:document.querySelector('#hbody .hc')?.title || ''};
    }""")


def test_state_304_still_refreshes_independent_health_and_pulse(ui):
    page, state, calls = ui
    before = {path: calls[path] for path in ("/api/health", "/api/pulse")}
    state["state_code"] = 304
    # load() 的 finally 启动独立异步刷新；等待新响应，不能复用导航时
    # 已达成的 networkidle 状态后立刻读取计数。
    with page.expect_response("**/api/health"), page.expect_response("**/api/pulse"):
        page.evaluate("async () => { await load(); }")
    assert calls["/api/health"] > before["/api/health"]
    assert calls["/api/pulse"] > before["/api/pulse"]


@pytest.mark.parametrize("international", [True, False])
def test_empty_business_channel_does_not_invent_relogin_advice(ui, international):
    page, _, _ = ui
    page.evaluate("value => { SRX.probe.rows[0].intl = value; }", international)
    page.evaluate("srxRenderCapbar()")
    text = page.locator("#srxCapbar").text_content()
    if international:
        assert "同程" in text
    else:
        # 国内不挂国际能力条；空结果仍不得反推重登。
        assert page.locator("#srxCapbar").evaluate("e=>e.hidden") is True
        assert "同程" not in page.locator("#srccap").text_content()
    assert "会话待重登" not in text
    assert "登录后明细" not in text
    assert "需重新登录" not in text


@pytest.mark.parametrize("status", ["active", "saving", "pending", "available", "saved", "save_error"])
def test_current_auth_state_is_consistent_across_pages_despite_old_failure(ui, status):
    page, state, _ = ui
    _require_shared_loader(page)
    state["login"] = _payload(status)
    faces = _render_faces(page)
    assert faces["auth"]["status"] == status
    assert faces["auth"]["needsLogin"] is False
    label = faces["auth"]["label"]
    assert label and label != "未登录"
    assert all(label in faces[key] for key in ("config", "source", "search")), faces
    assert faces["actionHidden"] is True
    assert "需登录" in faces["historyTitle"]  # 过去失败仍在历史格内。
    if status == "pending":
        assert "验证" in label
    if status == "saving":
        assert "保存" in label


def test_confirmed_auth_rejection_has_same_action_across_pages(ui):
    page, state, _ = ui
    _require_shared_loader(page)
    state["login"] = _payload("login_required")
    faces = _render_faces(page)
    assert faces["auth"]["needsLogin"] is True
    label = faces["auth"]["label"]
    assert all(label in faces[key] for key in ("config", "source", "search")), faces
    assert faces["actionHidden"] is False
    assert faces["actionPlatform"] == "qunar"


def test_failed_state_read_does_not_turn_saved_session_into_missing_login(ui):
    page, state, _ = ui
    _require_shared_loader(page)
    state["login"] = _payload("saved")
    page.evaluate("loadChannelState(true)")
    state["login_code"] = 500
    state["login"] = {"ok": False, "err": "fixture unavailable"}
    page.evaluate("loadChannelState(true)")
    auth = page.evaluate("channelAuthView('qunar')")
    assert auth["status"] != "missing"
    assert auth["needsLogin"] is False
    assert auth["label"] != "未登录"
    assert page.evaluate("Boolean(CHANNEL_STATE.error)") is True
    assert page.locator("#scQState").text_content() != "未登录"


def test_late_old_request_cannot_overwrite_newer_authentication_state(ui):
    page, _, _ = ui
    _require_shared_loader(page)
    page.evaluate("""() => {
        window.channelReplies = [];
        const originalFetch = window.fetch.bind(window);
        window.fetch = (url, options) => String(url).includes('/api/login-state')
          ? new Promise(resolve => window.channelReplies.push(resolve))
          : originalFetch(url, options);
        window.oldChannelLoad = loadChannelState(true);
        window.newChannelLoad = loadChannelState(true);
    }""")
    assert page.evaluate("window.channelReplies.length") == 2
    page.evaluate("""async payload => {
        window.channelReplies[1](new Response(JSON.stringify(payload),
          {status:200, headers:{'Content-Type':'application/json'}}));
        await window.newChannelLoad;
    }""", _payload("pending"))
    page.evaluate("""async payload => {
        window.channelReplies[0](new Response(JSON.stringify(payload),
          {status:200, headers:{'Content-Type':'application/json'}}));
        await window.oldChannelLoad;
    }""", _payload("login_required"))
    assert page.evaluate("channelAuthView('qunar').status") == "pending"
    assert page.evaluate("CHANNEL_STATE.payload.plats.qunar.status") == "pending"
    assert page.evaluate("channelAuthView('qunar').needsLogin") is False


def test_quote_service_failure_does_not_replace_independent_login_state(ui):
    page, _, _ = ui
    page.evaluate("loadLogin(null,true)")
    page.evaluate("() => { S=null; _markStale('报价服务异常'); }")
    assert page.locator("#loginRows .lgcard").count() == 5
    assert "已有登录态" in page.locator("#loginRows").text_content()


def test_explicit_refresh_restores_login_cards_with_unchanged_payload(ui):
    page, _, _ = ui
    page.evaluate("loadLogin(null,true)")
    page.evaluate("document.querySelector('#loginRows').textContent='报价服务异常'")
    page.evaluate("loadLogin(null,true)")
    assert page.locator("#loginRows .lgcard").count() == 5


def test_unchanged_background_state_keeps_search_action_focus(ui):
    page, _, _ = ui
    # 900px 短桌面按产品口径隐藏能力条；本用例要看动作焦点，
    # 放到 1000px 让 #srxCapbar 正常显示。
    page.set_viewport_size({"width": 1280, "height": 1000})
    page.evaluate("loadChannelState(true)")
    result = page.evaluate("""async () => {
        document.querySelector('#searchview').style.display='';
        // loadChannelState(true) 在载荷未变时不会重绘；先显式渲染价带
        // 动作条，再验证背景刷新保持同一节点与焦点。
        srxRenderCapbar();
        const action=document.querySelector('#srxCapbar button');
        action.focus();
        CHANNEL_STATE.at=0;
        await loadChannelState(false);
        return action.isConnected && document.activeElement===action;
    }""")
    assert result is True


def test_login_rejection_names_affected_scope_without_denying_other_scope(ui):
    page, state, _ = ui
    state["login"] = _payload("login_required")
    state["login"]["plats"]["qunar"]["scopes"] = {
        "domestic": {"needs_login": True, "auth_at": "2026-10-22 10:00:00"},
        "international": {"needs_login": False, "detail_available": True,
                          "detail_at": "2026-10-22 10:01:00"},
    }
    faces = _render_faces(page)
    assert "国内" in faces["auth"]["label"]
    assert all(faces["auth"]["label"] in faces[key] for key in ("config", "source", "search"))
    assert "国际" in faces["auth"]["title"]
