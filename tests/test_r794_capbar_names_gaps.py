# -*- coding: utf-8 -*-
"""r794 门禁：检索页「本次渠道产物」必须如实说明每个缺行的渠道。

来由（2026-11-01 实渲染复现）：r788 为修「App 渠道有产出却不显示」，
把产物条的渠道集合从 `SRX_PLAT_ORDER` 换成了「数据 ∪ 探针 want」——
方向对，但**顺带把「会话播报 / 需登录」的范围也收窄到产物渠道**。
于是去哪儿会话失效、本次无行时，检索页只有「途牛 · 明细 1」，
一个字不说去哪儿为什么缺；替身里连 `want` 都没有时更极端：
同程一家都不出现。用户读作「这家被跳过了」或「原站确实没这航班」，
与「宁缺勿错」的底线相反。

判据（真浏览器 + 真渲染，不看源码字面）：
1. 探针 want 里、本次无行的渠道，必须以 chip 出现并标「本次无明细」；
2. 会话失效的渠道，即使本次没被请求，也要看得见，且**不许**写成
   「本次无明细」（那是「查过、没票」的意思，属谎报）；
3. 不需要登录、也不在产物里的渠道不得凭空出现（负控：不许靠「全列
   一遍」蒙混过关）。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlsplit

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def server():
    import webui  # noqa: F401  确保模块可导入（PAGE 存在）

    port = _free_port()
    p = subprocess.Popen([sys.executable, "webui.py", "--demo",
                          "--port", str(port)],
                         cwd=ROOT, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    up = False
    for _ in range(120):
        try:
            op.open("http://127.0.0.1:%d/api/state" % port, timeout=1)
            up = True
            break
        except Exception:
            time.sleep(0.25)
    if not up:
        p.terminate()
        pytest.skip("演示服务未在期限内起来")
    yield port
    p.terminate()


def _faces(port, width=1280):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        try:
            pg = b.new_page(viewport={"width": width, "height": 1000})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            # 冻结全局周期轮询：它会用 /api/login-state 的真载荷覆盖下面
            # 注入的会话态，渲染时机不同就得到不同结论（并发跑测实测误红）。
            pg.add_init_script("window.setInterval = () => 1;")
            pg.goto("http://127.0.0.1:%d/" % port,
                    wait_until="domcontentloaded", timeout=30000)
            pg.wait_for_timeout(2500)
            pg.evaluate("""() => {
                /* 探针口径：want 里五家，实际只有途牛出数。
                   会话：去哪儿明确登录拒绝，其余已保存。 */
                window.__login = {ok:true, plats:{}};
                ['ctrip','tongcheng','tuniu','fliggy'].forEach(p=>{
                  window.__login.plats[p]={status:'saved',saved:true,
                    needs_login:false,active:false,saving:false,pending:false,
                    saved_at:1792638000,error:'',scopes:{},stale:false,
                    health_need_login:false};});
                window.__login.plats.qunar={status:'login_required',saved:true,
                  needs_login:true,active:false,saving:false,pending:false,
                  saved_at:1792638000,error:'',scopes:{},stale:false,
                  health_need_login:false};
                CHANNEL_STATE.payload=window.__login;CHANNEL_STATE.error='';
                SRX.probe={rows:[{from:'SHA',to:'NRT',date:'2026-11-16',
                  intl:true,platKey:'tuniu',code:'MU523',depTime:'09:05',
                  arrTime:'13:15',price:719,isStale:false,isCal:false}],
                  channels:{},legs:[],plans:[],
                  want:['ctrip','qunar','fliggy','tongcheng','tuniu']};
                SRX.pair='SHA|NRT';SRX.date='2026-11-16';
                switchView('search');
                const v=document.getElementById('searchview');
                if(v&&v.classList.contains('srx-ov-collapsed'))srxToggleOverview();
                srxRenderCapbar();
            }""")
            pg.wait_for_timeout(400)
            out = pg.evaluate("""() => {
                const el=document.getElementById('srxCapbar');
                const chips=[...el.querySelectorAll('.capchip')].map(c=>{
                  const r=c.getBoundingClientRect();
                  return {t:(c.textContent||'').trim(),cls:c.className,
                          w:Math.round(r.width),h:Math.round(r.height)};});
                return {chips, hidden:el.hidden,
                        text:(el.textContent||'').trim(),
                        sw:el.scrollWidth, cw:el.clientWidth,
                        boxW:Math.round(el.getBoundingClientRect().width)};
            }""")
            return out, errs
        finally:
            b.close()


def test_channels_without_rows_are_named_not_silently_dropped(server):
    out, errs = _faces(server)
    assert not errs, "检索页有 JS 报错：%s" % errs[:3]
    assert out["boxW"] > 0, "能力条没渲染出来：%s" % out
    by = {c["t"]: c for c in out["chips"]}
    names = " ".join(by)
    for ch in ("携程", "飞猪", "同程"):
        hit = [t for t in by if t.startswith(ch)]
        assert hit, "请求过却没有行的渠道 %s 在产物条上消失了：%s" % (ch, names)
        assert "本次无明细" in hit[0], (
            "%s 本次没出数，chip 应写「本次无明细」而不是静默：%s" % (ch, hit[0]))


def test_login_rejected_channel_is_visible_and_not_called_no_result(server):
    out, errs = _faces(server)
    assert not errs, errs[:3]
    qunar = [c for c in out["chips"] if c["t"].startswith("去哪儿")]
    assert qunar, "去哪儿会话失效，检索页却完全没有它的痕迹：%s" % out["text"]
    txt = qunar[0]["t"]
    assert "需登录" in txt or "登录" in txt, (
        "去哪儿缺行的原因是会话失效，chip 却写成「%s」" % txt)
    assert "本次无明细" not in txt, (
        "会话失效导致没行，写成「本次无明细」等于谎报『查过、无票』：%s" % txt)


def test_gate_is_reachable_and_negative_control(server):
    """负控：把会话补成正常后，「需登录」字样必须消失——否则上一条
    可能只是恒真的固定文案。"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        try:
            pg = b.new_page(viewport={"width": 1280, "height": 1000})
            pg.add_init_script("window.setInterval = () => 1;")
            pg.goto("http://127.0.0.1:%d/" % server,
                    wait_until="domcontentloaded", timeout=30000)
            pg.wait_for_timeout(2500)
            got = pg.evaluate("""() => {
                const pay={ok:true,plats:{}};
                ['ctrip','qunar','tongcheng','tuniu','fliggy'].forEach(p=>{
                  pay.plats[p]={status:'saved',saved:true,needs_login:false,
                    active:false,saving:false,pending:false,saved_at:1792638000,
                    error:'',scopes:{},stale:false,health_need_login:false};});
                CHANNEL_STATE.payload=pay;CHANNEL_STATE.error='';
                SRX.probe={rows:[{from:'SHA',to:'NRT',date:'2026-11-16',
                  intl:true,platKey:'tuniu',code:'MU523',depTime:'09:05',
                  arrTime:'13:15',price:719,isStale:false,isCal:false}],
                  channels:{},legs:[],plans:[],
                  want:['ctrip','qunar','fliggy','tongcheng','tuniu']};
                SRX.pair='SHA|NRT';SRX.date='2026-11-16';
                switchView('search');
                const v=document.getElementById('searchview');
                if(v&&v.classList.contains('srx-ov-collapsed'))srxToggleOverview();
                srxRenderCapbar();
                const el=document.getElementById('srxCapbar');
                return (el.textContent||'').trim();
            }""")
            assert "去哪儿的" not in got
            assert "需登录" not in got, (
                "会话正常后仍出现「需登录」，说明上面两条测的是固定文案：%s" % got)
            assert "本次无明细" in got, (
                "会话正常、本次无行的渠道仍应如实写「本次无明细」：%s" % got)
        finally:
            b.close()
