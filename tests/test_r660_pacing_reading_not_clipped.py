# -*- coding: utf-8 -*-
r"""r660：节流行的数据不能在中档宽度被裁掉。

`.pace-row .ev` 是 `e1（结论）+ e2（近24h 读数）` 的 flex 行。原先 e2 是
`flex:none` + nowrap，一行读数要 762px；而 765–1100 档证据列只有
405–636px（行是 `nm | st | ev | ac` 四列）。多出来的部分被网格列**直接
裁掉**：1024 档读数的尾巴消失、768 档整段读数一个字都看不见。

r640 只测了 1440/700/390，正好跳过这一段；而且它量的是「文本视觉行数」，
被裁掉的文字仍在文本流里，行数判据看不见——所以这个缺陷一直没被发现。

判据（真渲染，打桩 /api/pacing + /api/paths）：
① e2 的 scrollWidth ≤ clientWidth（没有被裁）；
② 整行 scrollWidth ≤ 行宽（不让行本身横向溢出）；
③ e2 的可见文字 === 完整读数（不是只剩前半段）。
负控：把 e2 改回 `flex:none` + `nowrap`，①②必须红。
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FULL = ("近24h国内 30% · 国际 50% · App 航班列表 30%（需登录 12 · 软拒 3） · "
        "登录态快照恢复 ×1 · 模拟器运行时 0% · 日历 50% · 查询 30% · "
        "明细 0 / 日历 0 · 60 次")


def _payloads():
    scopes = {
        "dom": {"query_attempts": 40, "query_rate": 0.3,
                "query_rate_live": 0.3, "query_attempts_live": 40,
                "rate": 0.3,
                "paths": {
                    "app-list": {"attempts": 40, "ok": 12, "detail_ok": 8,
                                 "calendar_ok": 4, "rate": 0.3,
                                 "rate_excl_empty": 0.3, "login": 12,
                                 "soft": 3, "empty": 4, "unsupported": 0,
                                 "last_at": "10-30 05:20:00"},
                    "snap-restore": {"attempts": 9, "ok": 1, "detail_ok": 0,
                                     "calendar_ok": 1, "rate": 0.11,
                                     "rate_excl_empty": 0.11, "login": 0,
                                     "soft": 0, "empty": 0,
                                     "unsupported": 0,
                                     "last_at": "10-30 05:20:00"},
                    "android-runtime": {"attempts": 63, "ok": 0,
                                        "detail_ok": 0, "calendar_ok": 0,
                                        "rate": 0, "rate_excl_empty": 0,
                                        "login": 0, "soft": 0, "empty": 0,
                                        "unsupported": 0,
                                        "last_at": "10-30 05:20:00"}}},
        "intl": {"query_attempts": 20, "query_rate": 0.5,
                 "query_rate_live": 0.5, "query_attempts_live": 20,
                 "rate": 0.5,
                 "paths": {"日历": {"attempts": 20, "ok": 10, "detail_ok": 4,
                                    "calendar_ok": 6, "rate": 0.5,
                                    "rate_excl_empty": 0.5, "login": 0,
                                    "soft": 0, "empty": 0, "unsupported": 0,
                                    "last_at": "10-30 05:20:00"}}},
    }
    paths = {"paths": {k: dict(v) for k, v in {
        "app-list": {"attempts": 40, "ok": 12, "detail_ok": 8,
                     "calendar_ok": 4, "rate": 0.3, "rate_excl_empty": 0.3,
                     "login": 12, "soft": 3, "empty": 4, "unsupported": 0},
        "snap-restore": {"attempts": 9, "ok": 1, "detail_ok": 0,
                         "calendar_ok": 1, "rate": 0.11,
                         "rate_excl_empty": 0.11, "login": 0, "soft": 0,
                         "empty": 0, "unsupported": 0},
        "android-runtime": {"attempts": 63, "ok": 0, "detail_ok": 0,
                            "calendar_ok": 0, "rate": 0,
                            "rate_excl_empty": 0, "login": 0, "soft": 0,
                            "empty": 0, "unsupported": 0},
        "日历": {"attempts": 20, "ok": 10, "detail_ok": 4, "calendar_ok": 6,
                 "rate": 0.5, "rate_excl_empty": 0.5, "login": 0, "soft": 0,
                 "empty": 0, "unsupported": 0}}.items()},
        "retired": ["app-dump", "app-blocker"], "scopes": scopes,
        "query_rate_live": 0.3, "query_attempts_live": 60}
    pacing = {
        "ok": True, "quiet": {}, "last_round": {"trips": []},
        "cfg": {"min_gap_s": 0, "per_minute": 0}, "effect": {},
        "channels": {"app_zhixing": {
            "state": "path_degraded", "reason": "", "needs_login": False,
            "advice": {"state": "path_degraded", "action": "route",
                       "hint": "国内 近 24h 有效率 30%"}}}}
    return pacing, {"demo": False, "platforms": {"app_zhixing": paths}}


def _measure(widths, force_nowrap=False):
    import socket
    import subprocess
    import time
    import urllib.request

    from playwright.sync_api import sync_playwright

    pacing, paths = _payloads()
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    srv = subprocess.Popen(
        [sys.executable, "webui.py", "--demo", "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, env=env)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = "http://127.0.0.1:%d" % port
    out = {}
    try:
        up = False
        for _ in range(160):
            try:
                op.open(base + "/api/state", timeout=1)
                up = True
                break
            except Exception:
                time.sleep(0.25)
        if not up:
            pytest.skip("演示服务未在期限内起来")
        with sync_playwright() as pw:
            if not os.path.exists(pw.chromium.executable_path):
                pytest.skip("chromium 二进制缺失")
            b = pw.chromium.launch()
            try:
                pg = b.new_page(viewport={"width": 1024, "height": 1400})
                pg.set_default_timeout(20000)
                pg.add_init_script("window.setInterval=()=>1;")
                pg.goto(base)
                pg.wait_for_function(
                    "typeof S!=='undefined'&&S&&S.users", timeout=30000)

                def stub(route):
                    body = pacing if "/api/pacing" in route.request.url \
                        else paths
                    route.fulfill(status=200, content_type="application/json",
                                  body=json.dumps(body, ensure_ascii=False))

                pg.route("**/api/pacing*", stub)
                pg.route("**/api/paths*", stub)
                if force_nowrap:
                    pg.add_style_tag(content=(
                        ".pace-row .ev .e2{flex:none!important;"
                        "white-space:nowrap!important;"
                        "overflow:visible!important}"))
                for w in widths:
                    pg.set_viewport_size({"width": w, "height": 1400})
                    pg.evaluate("""()=>{try{switchView('mon')}catch(e){}
                      try{showMonTab&&showMonTab('health',true)}catch(e){}}""")
                    pg.wait_for_timeout(900)
                    out[w] = pg.evaluate(r"""()=>{
                      const box=document.getElementById('paceBox');
                      const row=[...box.querySelectorAll('.pace-row')]
                        .find(x=>/智行/.test(x.innerText));
                      if(!row)return {err:'no row'};
                      const ev=row.querySelector('.ev');
                      const e2=ev.querySelector('.e2');
                      const rr=row.getBoundingClientRect();
                      return {rowW:rr.width, rowSW:row.scrollWidth,
                              evW:ev.clientWidth, evSW:ev.scrollWidth,
                              e2W:e2?e2.clientWidth:0,
                              e2SW:e2?e2.scrollWidth:0,
                              e2txt:(e2?e2.innerText:'').replace(/\s+/g,' '),
                              rowH:rr.height};}""")
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()
    return out


@pytest.mark.parametrize("width", [1024, 768])
def test_reading_is_not_clipped_at_mid_widths(width):
    got = _measure([width])[width]
    assert not got.get("err"), "智行 App 的节流行没渲染出来：%s" % got
    assert got["e2W"] > 0 and got["e2SW"] > 0, "e2 量不到尺寸，判据无从生效"
    assert got["e2SW"] <= got["e2W"] + 1, (
        "w=%d 读数被裁：scrollWidth %d > clientWidth %d（%r）"
        % (width, got["e2SW"], got["e2W"], got["e2txt"]))
    assert got["rowSW"] <= got["rowW"] + 1, (
        "w=%d 整行横向溢出：%d > %d" % (width, got["rowSW"], got["rowW"]))
    assert got["e2txt"].strip() == FULL, (
        "w=%d 可见读数不完整，应为：%r\n实得：%r"
        % (width, FULL, got["e2txt"]))


def test_negative_control_nowrap_gets_clipped():
    """负控：把 e2 改回 flex:none + nowrap，裁切必须重现。"""
    got = _measure([768], force_nowrap=True)[768]
    assert not got.get("err"), got
    assert got["e2SW"] > got["e2W"] + 1, (
        "负控没有红：nowrap 下读数竟然没被裁（%s），判据测不到东西" % got)


def test_css_keeps_both_halves_shrinkable():
    import io
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                  newline="").read()
    i = src.index(".pace-row .ev .e2{")
    seg = src[i:i + 260]
    assert "flex:none" not in seg, "e2 又变成不可收缩，中档会被裁"
    assert "white-space:nowrap" not in seg, "e2 又禁止换行，中档会被裁"
    j = src.index(".pace-row .ev .e1{")
    assert "min-width:0" in src[j:j + 140], "e1 必须可收缩（省略号收口）"
