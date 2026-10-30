# -*- coding: utf-8 -*-
"""r512：干预成效必须能按域说——渠道级数字会把「国际没救回来」藏起来。

真实库（qunar，2026-10-29 15:27 实测）：

    渠道级：43.6%（117）→ 70.8%（120）
    国际域：47.8%（46） → 53.1%（64）

渠道级看着「救回来了」，而这次干预点的是**国际自检**——真正针对的那一域
只从 47.8% 挪到 53.1%。国内正常、国际全挂时渠道级会接近 100%，读作
「干预很成功」，操作者下一次还会按同样的钮。

判据沿用 `path_stats` 的分域口径（`core.intl.is_intl_route`），不另造一套；
scope 不是域（如 relogin 记的槽位名）时**不返回该组字段**——不猜。
"""
import os
import tempfile
from datetime import datetime, timedelta

from core.storage import PriceStorage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_INTL = ("BKK", "CAN")     # 国际（曼谷→广州）
_DOM = ("PEK", "SHA")      # 国内（北京→上海）


def _ps():
    return PriceStorage(os.path.join(tempfile.mkdtemp(), "t.db"))


def _at(minutes_ago):
    return (datetime.now() - timedelta(minutes=minutes_ago)).strftime(
        "%Y-%m-%d %H:%M:%S")


def _row(ps, plat, status, at, route):
    with ps._conn() as c:
        c.execute(
            "INSERT INTO fetch_paths (fetched_at,platform,from_city,"
            "to_city,depart_date,entry_path,path_status) "
            "VALUES (?,'%s',?,?,'2026-11-05','H5',?)" % plat,
            (at, route[0], route[1], status))


def test_scope_effect_exposes_the_domain_the_intervention_targeted():
    """国内全好、国际全挂：渠道级看不出问题，国际域必须看得出来。"""
    ps = _ps()
    ps.save_intervention("qunar", "probe", ok=True, scope="intl", at=_at(120))
    # 干预前：国内 4/4 好，国际 0/4 好 → 渠道级 50%
    _row(ps, "qunar", "ok", _at(300), _DOM)
    _row(ps, "qunar", "ok", _at(290), _DOM)
    _row(ps, "qunar", "ok", _at(280), _DOM)
    _row(ps, "qunar", "ok", _at(270), _DOM)
    for m in (180, 170, 160, 150):
        _row(ps, "qunar", "login", _at(m), _INTL)
    # 干预后：国内仍 4/4，国际仍 0/4 → 渠道级还是 50%
    _row(ps, "qunar", "ok", _at(100), _DOM)
    _row(ps, "qunar", "ok", _at(90), _DOM)
    _row(ps, "qunar", "ok", _at(80), _DOM)
    _row(ps, "qunar", "ok", _at(70), _DOM)
    for m in (60, 50, 40, 30):
        _row(ps, "qunar", "login", _at(m), _INTL)

    e = ps.intervention_effect("qunar", 24)
    assert e["has"] is True, e
    assert e["scope"] == "intl", e
    # 渠道级：前后都是 50% —— 看不出「国际一次都没救回来」
    assert round(e["before"], 2) == 0.5 and round(e["after"], 2) == 0.5, e
    # 分域：国际 0% → 0%，这才说得出真相
    assert e["scope_before"] == 0.0 and e["scope_before_n"] == 4, e
    assert e["scope_after"] == 0.0 and e["scope_after_n"] == 4, e


def test_dom_scope_ignores_intl_samples():
    """dom 干预时只看国内样本——国际的坏数据不能拖低国内读数。"""
    ps = _ps()
    ps.save_intervention("ctrip", "probe", ok=True, scope="dom", at=_at(120))
    _row(ps, "ctrip", "ok", _at(300), _DOM)
    _row(ps, "ctrip", "login", _at(120 + 40), _INTL)   # 干预前国际失败
    _row(ps, "ctrip", "ok", _at(100), _DOM)
    _row(ps, "ctrip", "login", _at(40), _INTL)         # 干预后国际也失败
    e = ps.intervention_effect("ctrip", 24)
    assert e["scope"] == "dom", e
    assert e["scope_before"] == 1.0 and e["scope_before_n"] == 1, e
    assert e["scope_after"] == 1.0 and e["scope_after_n"] == 1, e


def test_non_domain_scope_returns_no_scope_effect():
    """relogin 的 scope 是槽位名，不是域——不得硬套分域字段。"""
    ps = _ps()
    ps.save_intervention("fliggy", "relogin", ok=True,
                         scope="fliggy_h5", at=_at(60))
    _row(ps, "fliggy", "ok", _at(120), _DOM)
    _row(ps, "fliggy", "ok", _at(30), _DOM)
    e = ps.intervention_effect("fliggy", 24)
    assert e["has"] is True, e
    assert "scope_before" not in e and "scope_after" not in e, \
        "非域 scope 被硬套了分域字段：%r" % (e,)


def test_scope_effect_window_matches_the_channel_level_window():
    """分域窗口与渠道级同界：干预前超出 hours 的样本不得混进来。"""
    ps = _ps()
    ps.save_intervention("tuniu", "probe", ok=True, scope="intl", at=_at(60))
    _row(ps, "tuniu", "login", _at(60 + 30 * 60), _INTL)  # 30 小时前，窗外
    _row(ps, "tuniu", "login", _at(300), _INTL)           # 5 小时前，窗内
    _row(ps, "tuniu", "ok", _at(20), _INTL)
    e = ps.intervention_effect("tuniu", 24)
    assert e["scope_before_n"] == 1, \
        "分域前窗把窗外样本算进来了：%r" % (e,)
    assert e["scope_after_n"] == 1, e


def test_panels_render_the_scope_effect():
    """两处追溯面板都要把分域读数渲染出来（不只在节流面板）。"""
    import io
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert "eff.scope_before" in w, "节流面板没有渲染分域前后"
    assert "本次干预针对" in w, "退出检查面板没有渲染分域前后"
    # 渠道级那一行必须仍在（分域是附注，不是替换）：
    # 节流面板 `<span class="k">干预后对比</span>`、退出检查面板
    # 「干预后对比：」。两处都必须在场。
    assert w.count("干预后对比") >= 2, "渠道级成效行被分域替换掉了"


def test_scope_label_is_actually_rendered_not_undefined():
    """域名（国际/国内）必须真的出现在文本里。

    实测踩过：代码写 `esc(_scb.n)` 而对象字段叫 `nm` —— 页面上渲染成
    「undefined域 48%（46） → 53%（64）」，源码里搜「国际域」也搜得到
    （三元表达式里有这个字面量），**纯静态断言完全挡不住**。
    """
    from playwright.sync_api import sync_playwright
    import webui, json as _json

    tmp = os.path.join(ROOT, "_scratch", "_r512t")
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as f:
        f.write(webui.PAGE.replace("__PAGEVER__", "r512t"))

    class H(__import__("http.server", fromlist=["SimpleHTTPRequestHandler"])
            .SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    from functools import partial
    from http.server import ThreadingHTTPServer
    import threading
    import pytest as _pytest
    _PORT = 0
    srv = ThreadingHTTPServer(("127.0.0.1", 0),
                              partial(H, directory=tmp))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    eff = {"ok": True, "platform": "qunar", "has": True,
           "at": "2026-10-27 03:30:11", "action": "probe", "iv_ok": True,
           "before": 0.4359, "before_n": 117, "after": 0.7083, "after_n": 120,
           "trend": [], "regressed": False,
           "scope": "intl", "scope_before": 0.4783, "scope_before_n": 46,
           "scope_after": 0.5312, "scope_after_n": 64}
    trace = {"ok": True, "rows": [], "interventions": [], "effect": eff}
    try:
        with sync_playwright() as drv:
            if not os.path.exists(drv.chromium.executable_path):
                _pytest.skip("Chromium 未安装")
            b = drv.chromium.launch()
            try:
                ctx = b.new_context(viewport={"width": 1280, "height": 900})
                page = ctx.new_page()
                page.set_default_timeout(9000)
                page.add_init_script("window.setInterval=()=>1;")
                page.route("**/api/trace*", lambda r: r.fulfill(
                    status=200, body=_json.dumps(trace)))
                page.goto(("http://127.0.0.1:%d/index.html" % srv.server_address[1]),
                          wait_until="domcontentloaded")
                page.wait_for_function(
                    "typeof _paceTraceFill==='function'", timeout=12000)
                txt = page.evaluate("""async () => {
                    PACE.detail='qunar';
                    await _paceTraceFill('qunar');
                    const box=document.createElement('div');
                    box.style.width='820px';
                    box.innerHTML=PACE.detailHTML||'';
                    document.body.appendChild(box);
                    const sc=box.querySelector('.pace-effsc');
                    const t=sc?sc.textContent.replace(/\\s+/g,' '):'';
                    box.remove();
                    return t;
                }""")
                ctx.close()
            finally:
                b.close()
    finally:
        srv.shutdown()
        srv.server_close()

    assert "undefined" not in txt.lower(), \
        "分域读数渲染出了 undefined：%r" % (txt,)
    assert "国际域" in txt, "域名没有渲染出来：%r" % (txt,)
    assert "48%" in txt and "53%" in txt, "分域前后数字缺失：%r" % (txt,)
