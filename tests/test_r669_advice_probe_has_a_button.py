# -*- coding: utf-8 -*-
r"""r669：结论让人按「自检」，行里就必须真有自检按钮。

后端 `advise()` 在多条结论里写「点『自检』看具体路径」：
`soft_reject`（上一轮被软拒）、`calendar_only`（只拿到日历价）、
`path_degraded`（某条通路劣化）——它们的 `action` 都是 `probe`。

但前端按钮原先只按 `v.state` / `v.needs_login` 拼：这几种状态一行都落
不到按钮分支，于是行里只剩「展开溯源」。**结论让用户按的按钮不存在**，
等于把人晾在原地（这是「可干预」准则的直接缺口）。

判据（真渲染，打桩 /api/pacing）：
① `action=probe` 的结论行必须有「自检」按钮，且 onclick 指向 probeNow；
② 结论里出现「自检」二字的行，也必须有该按钮（词面与动作一致）；
③ 不该有自检时不许硬塞：`action` 为 scan/wait/route/none 时不出现；
   登录行（needs_login / state=login）走「去登录」，不混入自检。
负控：去掉刚加的那段 probe 分支 → ① ② 同时红。
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _payload(action, state, hint, needs_login=False):
    ch = {}
    for i, p in enumerate(("qunar", "fliggy", "ctrip", "tongcheng", "tuniu")):
        if i == 0:
            ch[p] = {"state": state, "reason": "", "needs_login": needs_login,
                     "advice": {"state": "login" if needs_login else state,
                                "action": action, "severity": "auto",
                                "hint": hint, "eta_s": 60}}
        else:
            ch[p] = {"state": "ok", "advice": {"state": "ok",
                                               "action": "none"}}
    return {"ok": True, "quiet": {}, "last_round": {"trips": []},
            "cfg": {"min_gap_s": 0, "per_minute": 0}, "effect": {},
            "channels": ch}


# 后端真的会写「点『自检』」的三类结论
PROBE_HINTS = {
    "path_degraded": "国内 App 航班列表 近 24h 有效率 30%——可点「自检」验证",
    "calendar_only": "近 24h 只拿到日历价，没有航班明细；点「自检」看具体路径",
    "soft_reject": "上一轮被软拒 … 若连续出现，点「自检」看路径",
}


def _render(cases):
    import socket
    import subprocess
    import time
    import urllib.request

    from playwright.sync_api import sync_playwright

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
    state = {"pacing": {}, "paths": {"demo": False, "platforms": {}}}
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
                    body = state["pacing"] \
                        if "/api/pacing" in route.request.url \
                        else state["paths"]
                    route.fulfill(status=200,
                                  content_type="application/json",
                                  body=json.dumps(body, ensure_ascii=False))

                pg.route("**/api/pacing*", stub)
                pg.route("**/api/paths*", stub)
                pg.evaluate("""()=>{try{switchView('mon')}catch(e){}
                  try{showMonTab&&showMonTab('health',true)}catch(e){}}""")
                out = {}
                for key, (action, vstate, hint, nl) in cases.items():
                    state["pacing"] = _payload(action, vstate, hint, nl)
                    pg.wait_for_timeout(400)
                    pg.evaluate("()=>{try{loadPacing(true)}catch(e){}}")
                    pg.wait_for_timeout(900)
                    out[key] = pg.evaluate("""()=>{
                      const box=document.getElementById('paceBox');
                      const row=[...box.querySelectorAll('.pace-row')]
                        .find(x=>/去哪儿/.test(x.innerText));
                      if(!row)return {err:'no row'};
                      const btns=[...row.querySelectorAll('.ac button')];
                      return {labels:btns.map(b=>b.innerText.trim()),
                              html:btns.map(b=>b.getAttribute('onclick')||''),
                              ev:(row.querySelector('.ev')||{}).innerText||'',
                              title:row.getAttribute('title')||''};}""")
                return out
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()


@pytest.fixture(scope="module")
def rendered():
    return _render({
        "path_degraded": ("probe", "path_degraded", PROBE_HINTS["path_degraded"], False),
        "calendar_only": ("probe", "calendar_only", PROBE_HINTS["calendar_only"], False),
        "soft_reject": ("probe", "soft_reject", PROBE_HINTS["soft_reject"], False),
        "stale_probe": ("probe", "stale", "超过 TTL 无新数据", False),
        "stale_scan": ("scan", "stale", "超过 TTL 无新数据", False),
        "watch": ("watch", "degraded", "近 24h 成功率 40%，观察一轮", False),
        "login": ("relogin", "path_degraded", "会话失效，请重登", True),
    })


def _has_probe(row):
    return any("probeNow" in h for h in row["html"])


@pytest.mark.parametrize("key", ["path_degraded", "calendar_only",
                                 "soft_reject", "stale_probe"])
def test_probe_advice_has_a_probe_button(rendered, key):
    row = rendered[key]
    assert not row.get("err"), "行没渲染出来：%s" % row
    assert _has_probe(row), (
        "结论建议 probe，但行里没有自检按钮（实际按钮：%s）"
        % row["labels"])


@pytest.mark.parametrize("key", ["path_degraded", "calendar_only",
                                 "soft_reject"])
def test_hint_saying_selfcheck_matches_a_real_button(rendered, key):
    """后端 hint 里出现「自检」二字，行里就必须有能按的自检按钮。

    注意判据要读 **行 title 上的 advice.hint 原文**，不能读 .ev ——
    .ev 是前端自己压缩出来的简述，本来就不会带「点『自检』」这半句。
    """
    row = rendered[key]
    assert "自检" in row["title"], (
        "行 title 没带上后端 hint，判据不成立：%r" % row["title"])
    assert _has_probe(row), (
        "结论写着「点『自检』」，行里却没有自检按钮：%s" % row["labels"])


@pytest.mark.parametrize("key", ["stale_scan", "watch"])
def test_no_probe_button_when_advice_is_not_probe(rendered, key):
    row = rendered[key]
    assert not row.get("err"), row
    assert not _has_probe(row), (
        "action 不是 probe，却硬塞了自检按钮：%s / %s"
        % (row["labels"], row["html"]))


def test_login_row_offers_login_not_probe(rendered):
    row = rendered["login"]
    assert not row.get("err"), row
    assert any("登录" in x or "验证" in x for x in row["labels"]), (
        "登录行没有去登录/去验证：%s" % row["labels"])
    assert not _has_probe(row), (
        "登录行不该同时给自检（会把人引去做无效操作）：%s" % row["labels"])
