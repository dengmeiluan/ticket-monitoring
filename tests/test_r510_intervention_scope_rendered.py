# -*- coding: utf-8 -*-
"""r510：干预账的作用域必须渲染出来——同两条「自检」不能长得一模一样。

实测：账本里 `scope` 早就分开记了（`probe` 有 **dom 2 次 / intl 7 次**，
`relogin` 记槽位 `fliggy`），但溯源表只渲染动作名。于是：

    10-29 13:02 · 自检 · 成功
    10-29 12:40 · 自检 · 失败

读者无法定位是哪一域失败，也无法把 PC 与 H5 的重登分开——「可区分」
「可定位」「可溯源」三项同时失效。数据在库里、也传到了前端，只是没渲染。

修法：作用域小标与动作名并排（小一号字、弱一档色），空值不占位；
两处溯源（节流面板 `pace-tline` / 退出检查面板）用同一套中文词。
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

_IVS = [
    {"at": "2026-10-29 13:02:00", "action": "probe", "ok": True,
     "scope": "intl", "ms": 12000, "note": "国际自检"},
    {"at": "2026-10-29 12:40:00", "action": "probe", "ok": False,
     "scope": "dom", "ms": 9000, "note": "国内自检"},
    {"at": "2026-10-29 11:00:00", "action": "relogin", "ok": True,
     "scope": "fliggy_h5", "note": "网页登录保存会话"},
    # 无作用域的历史记录（老账本）：不得渲染出空小标或 "undefined"
    {"at": "2026-10-29 10:00:00", "action": "warmup", "ok": True,
     "ms": 3000, "note": "预热"},
]


def _render():
    from playwright.sync_api import sync_playwright
    import webui

    tmp = os.path.join(ROOT, "_scratch", "_r510_t")
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as f:
        f.write(webui.PAGE.replace("__PAGEVER__", "r510t"))

    class H(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    _PORT = 0
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(H, directory=tmp))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    trace = {"ok": True, "rows": [], "interventions": _IVS, "effect": {}}
    try:
        with sync_playwright() as drv:
            if not os.path.exists(drv.chromium.executable_path):
                pytest.skip("Chromium 未安装")
            b = drv.chromium.launch()
            try:
                ctx = b.new_context(viewport={"width": 1280, "height": 900})
                page = ctx.new_page()
                page.set_default_timeout(9000)
                page.add_init_script("window.setInterval=()=>1;")
                page.route("**/api/trace*", lambda r: r.fulfill(
                    status=200, body=json.dumps(trace)))
                page.goto(("http://127.0.0.1:%d/index.html" % srv.server_address[1]),
                          wait_until="domcontentloaded")
                page.wait_for_function(
                    "typeof _paceTraceFill==='function'", timeout=12000)
                return page.evaluate("""async () => {
                    PACE.detail='fliggy';
                    await _paceTraceFill('fliggy');
                    const box=document.createElement('div');
                    /* 用真实面板宽度，不用 window-60：用一个更窄的临时容器
                       量出来的截断是假的，会把「布局正常」判成缺陷。 */
                    box.style.width='820px';
                    box.innerHTML=PACE.detailHTML||'';
                    document.body.appendChild(box);
                    const lines=[...box.querySelectorAll('.pace-tline')]
                      .filter(e=>!e.classList.contains('head'));
                    const out={
                      n:lines.length,
                      rows:lines.map(e=>{
                        const p=e.querySelector('.p');
                        const sc=p?p.querySelector('.sc'):null;
                        return {txt:(e.textContent||'').trim().replace(/\\s+/g,' '),
                                act:p?p.childNodes[0].textContent:'',
                                scope:sc?sc.textContent:''};
                      }),
                      emptySc:lines.filter(e=>{
                        const sc=e.querySelector('.p .sc');
                        return sc && !(sc.textContent||'').trim();
                      }).length,
                      badSc:box.innerHTML.indexOf('undefined')>=0,
                    };
                    box.remove();
                    return out;
                }""")
            finally:
                b.close()
    finally:
        srv.shutdown()
        srv.server_close()


def test_scope_is_rendered_so_two_probes_are_distinguishable():
    r = _render()
    assert r["n"] == 4, "干预行数不对：%r" % (r,)
    probes = [x for x in r["rows"] if x["act"] == "自检"]
    assert len(probes) == 2, "两条自检没有都渲染：%r" % (r,)
    scopes = sorted(x["scope"] for x in probes)
    assert scopes == ["国内", "国际"], \
        "两条「自检」仍然无法区分是哪一域：%r" % (r,)


def test_relogin_scope_shows_which_surface():
    """重登按槽位记（PC / H5 两套 cookie），必须看得出是哪一端。"""
    r = _render()
    re_ = [x for x in r["rows"] if x["act"] == "重登"]
    assert re_, "重登行没有渲染：%r" % (r,)
    assert "飞猪 H5" in re_[0]["scope"], \
        "重登没有标出哪一端（PC/H5 是两次独立登录）：%r" % (r,)


def test_empty_scope_renders_nothing_not_undefined():
    """老账本没有 scope：不得吐空小标或 undefined。"""
    r = _render()
    assert r["emptySc"] == 0, "空作用域渲染出了空小标：%r" % (r,)
    assert r["badSc"] is False, "页面里出现了 undefined：%r" % (r,)
    warm = [x for x in r["rows"] if x["act"] == "预热"]
    assert warm and warm[0]["scope"] == "", \
        "无 scope 的动作被塞了作用域：%r" % (r,)
