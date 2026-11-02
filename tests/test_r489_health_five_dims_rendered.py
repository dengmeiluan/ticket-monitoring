# -*- coding: utf-8 -*-
"""r489：健康卡五维必须**渲染出来**，不是字符串在场。

`test_goal_d` 只查源码里有没有 `shownRate` / `scoped('dom','国内')` /
`dead.forEach(...' 退役')` / `healthSlotNote` / `_attach_diag_slots`。
字符串在场不等于渲染正确：字段名写错（`retired` vs `retired_paths`）、
容器换位置（诊断卡在 `#healthDiagBody` 而不是 `#healthcard` 内）这类问题
字符串守卫全都看不见。

这里用一份**与后端同形**的载荷真渲染，逐维取证：
  ① 厂商级在用口径（83%）
  ② 分域（国内 95% · 国际 70%，各自独立不互相冲抵）
  ③ 分通路（PC 92% · H5 43% · 日历 **退役**）
  ④ 分会话（PC 已存待验 / H5 需重登 —— 飞猪两套 cookie 分开说）
  ⑤ 诊断卡（指向失效端 H5，不是厂商级入口）
"""
import json
import os
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SLOTS = {"ok": True, "plats": {"fliggy": {"status": "saved", "saved": True}},
         "slots": {
             "fliggy": {"plat": "fliggy", "name": "飞猪 PC", "surface": "pc",
                        "surface_label": "PC", "status": "saved",
                        "saved": True, "needs_login": False, "account": "a"},
             "fliggy_h5": {"plat": "fliggy", "name": "飞猪 H5", "surface": "h5",
                           "surface_label": "H5", "status": "login_required",
                           "needs_login": True, "saved": True, "account": "a"},
         }}

# 与 /api/health 的 paths 同形：
#   - retired 不是 retired_paths
#   - scopes 的 key 是 dom/intl（path_stats 原始口径），不是 domestic/international
#     （前端 _scTxt 会把 dom 显示成「国内」）
PATHS = {"fliggy": {
    "paths": {"PC": {"attempts": 12, "ok": 11, "rate": 0.917},
              "H5": {"attempts": 28, "ok": 12, "rate": 0.429},
              "日历": {"attempts": 6, "ok": 1, "rate": 0.167}},
    "retired": ["日历"],
    "scopes": {"dom": {"query_rate": 0.95, "query_attempts": 20},
               "intl": {"query_rate": 0.7, "query_attempts": 20}},
    "query_rate_live": 0.825, "query_attempts_live": 40}}

HEALTH = {
    "ok": True,
    "rounds": [{"ts": "2026-10-29 02:50", "plats": {
        "fliggy": {"s": "part", "ok": 2, "tot": 3, "cal": 0, "detail": 2}}}],
    "stats": {"fliggy": {"ok": 33, "part": 2, "fail": 5, "maint": 0,
                         "rate": 0.825, "cal": 0, "detail": 33, "auth": 3}},
    "push": {"channels": {}}, "paths": PATHS,
    "diag": [{"plat": "fliggy", "name": "飞猪", "kind": "login",
              "label": "登录态失效", "action": "打开登录窗口重存会话",
              "s": "fail", "login": "login_required", "cookie": "missing",
              "evidence": "H5 会话被拒",
              "slots": [{"slot": "fliggy", "surface": "PC",
                         "needs_login": False, "status": "saved"},
                        {"slot": "fliggy_h5", "surface": "H5",
                         "needs_login": True, "status": "login_required"}],
              "dead_surfaces": ["H5"], "slot_action": "fliggy_h5"}],
    "coverage": {},
}


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as drv:
        if not os.path.exists(drv.chromium.executable_path):
            pytest.skip("Chromium 未安装")
        b = drv.chromium.launch()
        yield b
        b.close()


def test_health_card_renders_all_five_dimensions(browser):
    from playwright.sync_api import Error
    import webui
    tmp = os.path.join(ROOT, "_scratch", "_r489_t")
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as f:
        f.write(webui.PAGE.replace("__PAGEVER__", "r489t"))

    class H(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 8931), partial(H, directory=tmp))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = ctx.new_page()
    page.set_default_timeout(8000)
    page.add_init_script("window.setInterval=()=>1;")
    try:
        page.route("**/api/login-state", lambda r: r.fulfill(
            status=200, body=json.dumps(SLOTS)))
        page.route("**/api/health", lambda r: r.fulfill(
            status=200, body=json.dumps(HEALTH)))
        page.route("**/api/pulse", lambda r: r.fulfill(
            status=200, body=json.dumps({"ok": True, "items": []})))
        page.goto("http://127.0.0.1:8931/index.html",
                  wait_until="domcontentloaded")
        page.wait_for_function("typeof renderHealth==='function'", timeout=12000)
        page.evaluate("""async h => {
            try{switchView('mon');}catch(e){}
            try{showMonTab('health',true);}catch(e){}
            await loadChannelState(true);
            renderHealth(h);
            HL = JSON.stringify(h);
            renderHealthDiag();
            await new Promise(r=>setTimeout(r,300));
        }""", HEALTH)
        got = page.evaluate("""() => {
            const card=document.getElementById('healthcard');
            const row=[...card.querySelectorAll('.hrow')]
              .find(x=>x.textContent.includes('飞猪'));
            const rt=row?row.innerText.replace(/\\s+/g,' '):'';
            return {
              rate: /83%/.test(rt),
              dom: /国内 95%/.test(rt), intl: /国际 70%/.test(rt),
              /* 通路小标格式：`PC 单次 92%（12 次）`。中间允许夹一个口径词
                 （r636 加的），但仍要求「名称 → 口径词 → 百分比」按序相邻，
                 不能把 92% 挂到别的通路名下。 */
              pc: /PC (?:单次 )?92%/.test(rt),
              h5: /H5 (?:单次 )?43%/.test(rt),
              pcCaliber: /PC 单次 92%/.test(rt),
              h5Caliber: /H5 单次 43%/.test(rt),
              retired: /日历 退役/.test(rt),
              slotPc: /PC 已存待验/.test(rt), slotH5: /H5 需重登/.test(rt),
              diag: document.querySelectorAll(
                  '#healthDiagBody .hdiag-card').length,
              diagDead: /H5/.test((document.querySelector(
                  '#healthDiagBody')||{}).innerText||''),
              rowText: rt,
            };
        }""")
    finally:
        ctx.close()
        srv.shutdown()

    assert got["rate"], "① 厂商级在用口径未渲染：%r" % got["rowText"]
    assert got["dom"] and got["intl"], "② 分域未分别渲染：%r" % got["rowText"]
    assert got["pc"] and got["h5"], "③ 分通路未分别渲染：%r" % got["rowText"]
    # ③b 通路小标必须自带口径词（r636）：同一行里徽标/分域是**查询**口径，
    #     通路节点只有**尝试**口径。实测智行 App 渲染成「100% 国内 100% ·
    #     国际 100% android 33%」——三个 100% 与 33% 指两个不同分母，读者
    #     只会认为界面算错（真实库：查询 40/40=100%，尝试 40/121=33%）。
    assert got["pcCaliber"] and got["h5Caliber"], (
        "③b 分通路未标注口径（会被读成与徽标同一个分母）：%r"
        % got["rowText"])
    assert got["retired"], "③ 退役通路未标「退役」：%r" % got["rowText"]
    assert got["slotPc"] and got["slotH5"], \
        "④ 分会话未逐端渲染：%r" % got["rowText"]
    assert got["diag"] >= 1, "⑤ 诊断卡未渲染"
    assert got["diagDead"], "⑤ 诊断卡未点名失效端"


def test_backend_scope_fields_match_what_the_frontend_reads():
    """后端下发的分域字段名必须与前端读取的一致。

    实测缺陷（r490）：后端只发 `{rate, attempts}`，前端分域读的是
    `query_attempts[_live]` / `query_rate[_live]` —— 两侧不同名，
    「分域」这一维**在真实页面上从未渲染出来过**。
    `test_goal_d` 只查源码里有 `scoped('dom','国内')`，看不见字段名错配。

    上面那条渲染契约是**注入载荷**测的，打不到后端字段；这条直接钉后端。
    """
    import io
    import re as _re
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                newline="").read()
    # 前端实际读取的键
    i = w.index("const _qsc=((j.paths||{})[p]||{}).scopes||{};")
    front = set(_re.findall(r"_q\.([a-z_]+)", w[i:i + 700]))
    assert front, "未能解析前端分域字段"
    # 后端构造 _sc[_sn] 的分支
    j = w.index("_sc[_sn] = {")
    back_src = w[j:w.index("paths[_p] = {", j)]
    for k in front:
        assert '"%s":' % k in back_src, \
            "后端未下发前端要读的分域字段 %s（分域这一维渲染不出来）" % k


def test_badge_fallback_never_mixes_attempt_level_into_query_rate():
    """徽标兜底（`_liveRate` 不可用时）也必须按**查询**口径加权。

    `qRate` 曾用 `_q.rate × _q.attempts`——那是「尝试级 × 尝试数」，
    和分域小标（查询级）不是一个分母。`query_*_live` 缺失时同一行又
    会「13% 国际 73%」打架。现在：有查询字段就按查询加权；缺任一域的
    查询字段就整段作废（回落到轮次口径并在 title 里如实标注），
    绝不混着算。
    """
    import io
    import os
    import re

    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                  newline="").read()
    i = src.index("const _qscope=((_qp.scopes)||{});")
    seg = src[i:i + 1200]
    assert "query_attempts_live" in seg and "query_rate_live" in seg, (
        "徽标兜底没有用查询口径字段：%s" % seg[:400])
    assert "(_q.rate||0)*_q.attempts" not in seg, (
        "徽标兜底仍在用尝试级 rate 加权（与分域小标不同分母）：%s"
        % seg[:400])
    assert "_qmiss" in seg, "缺少「查询字段不全就别算」的标记"
