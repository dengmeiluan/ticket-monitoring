# -*- coding: utf-8 -*-
r"""r659：节流行里的通路名同样要中文。

r658 修了健康卡的分通路小标，但节流面板有**三处**也在拼账本键名：
右半 `pws`（「App 航班列表 25% · 登录态快照恢复 ×1」）、结论行
「最差通路 国内 …」、退役标签「… 退役」。App 渠道在这三处会把
`app-list` / `snap-restore` / `app-dump` 直接打上屏。

顺带清掉一处重复：`dead.forEach(pp=>pws.push(pp+' 退役'))` 原先连着写了
两遍，同一条退役通路在行里出现两次。

判据：
① 源码里这三处都必须经 `pathCN()`；
② 真渲染（打桩 /api/pacing + /api/paths）后，智行 App 那一行不含英文
   通路 id，且同一退役通路只出现一次；
③ 行为负控：把 `pathCN` 换成恒等函数后再渲染，同一判据必须红。
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LATIN_IDS = ("app-list", "app-route", "app-blocker", "app-dump",
             "app-error", "android-runtime", "android-device",
             "snap-restore")


def _src():
    import io
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_pacing_row_renders_use_path_cn():
    src = _src()
    assert "pws.push(pathCN(pp)+' '" in src, (
        "节流行右半的通路名没走 pathCN，会打出 app-list 这类英文 id")
    assert "'最差通路 '+_worst[0]" in src and \
        "pathCN(pp)" in src.split("const _worst=[]")[1][:2000], (
        "结论行的「最差通路」仍在拼原始键名")
    assert "dead.forEach(pp=>pws.push(pathCN(pp)+' 退役'))" in src
    # 同一段写两遍会让退役通路在行里出现两次（r659 顺手清掉）
    assert src.count("pws.push(pathCN(pp)+' 退役')") == 1, (
        "退役标签又重复渲染了")


def _render(identity=False):
    import socket
    import subprocess
    import time
    import urllib.request

    from playwright.sync_api import sync_playwright

    scopes = {
        "dom": {"query_attempts": 20, "query_rate": 0.4,
                "query_rate_live": 0.4, "query_attempts_live": 20,
                "rate": 0.4,
                "paths": {
                    "app-list": {"attempts": 40, "ok": 10, "detail_ok": 8,
                                 "calendar_ok": 2, "rate": 0.25,
                                 "rate_excl_empty": 0.25, "login": 12,
                                 "soft": 0, "empty": 0, "unsupported": 0,
                                 "last_at": "10-30 05:20:00"},
                    "snap-restore": {"attempts": 9, "ok": 1, "detail_ok": 0,
                                     "calendar_ok": 1, "rate": 0.11,
                                     "rate_excl_empty": 0.11, "login": 0,
                                     "soft": 0, "empty": 0, "unsupported": 0,
                                     "last_at": "10-30 05:20:00"}}},
        "intl": {"query_attempts": 10, "query_rate": 1.0,
                 "query_rate_live": 1.0, "query_attempts_live": 10,
                 "rate": 1.0,
                 "paths": {"日历": {"attempts": 10, "ok": 10, "detail_ok": 6,
                                    "calendar_ok": 4, "rate": 1.0,
                                    "rate_excl_empty": 1.0, "login": 0,
                                    "soft": 0, "empty": 0, "unsupported": 0,
                                    "last_at": "10-30 05:20:00"}}},
    }
    path_node = {
        "paths": {
            "app-list": {"attempts": 40, "ok": 10, "detail_ok": 8,
                         "calendar_ok": 2, "rate": 0.25,
                         "rate_excl_empty": 0.25, "login": 12, "soft": 0,
                         "empty": 0, "unsupported": 0},
            "snap-restore": {"attempts": 9, "ok": 1, "detail_ok": 0,
                             "calendar_ok": 1, "rate": 0.11,
                             "rate_excl_empty": 0.11, "login": 0, "soft": 0,
                             "empty": 0, "unsupported": 0},
            "日历": {"attempts": 10, "ok": 10, "detail_ok": 6,
                     "calendar_ok": 4, "rate": 1.0, "rate_excl_empty": 1.0,
                     "login": 0, "soft": 0, "empty": 0, "unsupported": 0}},
        "retired": ["app-dump"], "scopes": scopes,
        "query_rate_live": 0.4, "query_attempts_live": 30}
    pacing = {
        "ok": True, "quiet": {}, "last_round": {"trips": []},
        "cfg": {"min_gap_s": 0, "per_minute": 0}, "effect": {},
        "channels": {"app_zhixing": {
            "state": "path_degraded", "reason": "", "needs_login": False,
            "advice": {"state": "path_degraded", "action": "route",
                       "hint": "国内 近 24h 有效率 25%"}}}}
    paths = {"demo": False, "platforms": {"app_zhixing": path_node}}

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
                pg = b.new_page(viewport={"width": 1440, "height": 1400})
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
                if identity:
                    pg.evaluate(
                        "()=>{window.pathCN=function(k){return k;};}")
                pg.evaluate("""()=>{try{switchView('mon')}catch(e){}
                  try{showMonTab&&showMonTab('health',true)}catch(e){}}""")
                pg.wait_for_timeout(1500)
                return pg.evaluate("""()=>{
                  const box=document.getElementById('paceBox');
                  if(!box)return '';
                  const row=[...box.querySelectorAll('.pace-row')]
                    .map(r=>r.innerText.replace(/\\s+/g,' '))
                    .find(t=>/智行/.test(t));
                  return row||'';}""")
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()


def _bare(text):
    import re
    return sorted({p for p in LATIN_IDS
                   if re.search(r"(?<![A-Za-z_-])" + re.escape(p)
                                + r"(?![A-Za-z_-])", text)})


def test_pacing_row_shows_chinese_path_names():
    row = _render()
    assert row, "没渲染出智行 App 的节流行，判据无从生效"
    bare = _bare(row)
    assert not bare, "节流行里还有英文通路 id：%s（实测 %r）" % (bare, row)
    assert "App 航班列表" in row and "登录态快照恢复" in row, (
        "缺中文通路名：%r" % row)
    assert row.count("登录态快照恢复") == 1, (
        "同一条通路在行里出现多次（退役标签重复渲染）：%r" % row)


def test_render_negative_control_turns_the_gate_red():
    row = _render(identity=True)
    assert row, "负控没渲染出行"
    assert _bare(row), (
        "负控没有红：换回恒等名字函数后仍是中文（%r），判据测不到东西" % row)
