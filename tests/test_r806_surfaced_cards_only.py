# -*- coding: utf-8 -*-
"""r806 门禁：量「卡底留白」之前，必须先证明卡面可见。

背景（r804 的错误 + r836 的正确拦截）：
  · 我按 `card.bottom - 最后一个子元素.bottom` 量出 `.srf-time` 卡底 80/114px，
    判定为「上下不对齐、廉价感」并改成 `margin-top:auto` 沉底——自写门禁 4/4 全绿；
  · r836 以「卡内**最大**孤立空档 ≤34px」立刻抓红（space 只是把同一个洞换了位置）；
  · 再往下量才发现：`.srf-time` / `.srf-common` / `.srf-grid` 三者
    `background-color: rgba(0,0,0,0)`、`background-image: none`、
    `border-*-width: 0px`、`box-shadow: none`、`border-radius: 0px`
    —— **卡片没有可见边界**，那 80/114px 在屏幕上不存在任何可见形状。

判据（两条）：
  1. 筛选面板里任何**卡面可见**（有底色 / 描边 / 阴影任一）的卡，
     卡底余量必须 ≤ 34px（与 r836 的阈值同源）；
  2. 卡面**不可见**的卡不受此约束——但必须有另一条判据（r836 的 card 内 maxGap）
     兜住真正的「卡内孤立空洞」。这条把「不能拿不可见几何当缺陷」写成门禁。

负控：给 `.srf-time` 注入一个可见底色，它就会进入受约束集合；再注入 80px
底部内衬，第 1 条必须抓红——证明这条判据真的在看「可见卡」的余量。
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

JS = r"""() => {
  const fm = document.getElementById('srxFmore');
  if (!fm) return {err: 'no panel'};
  const R = e => { const b = e.getBoundingClientRect();
    return {t: b.top, b: b.bottom, h: b.height}; };
  const surfaced = cs =>
    !/^rgba\(0, 0, 0, 0\)$|^transparent$/.test(cs.backgroundColor)
    || (cs.backgroundImage && cs.backgroundImage !== 'none')
    || parseFloat(cs.borderTopWidth) > 0
    || parseFloat(cs.borderLeftWidth) > 0
    || (cs.boxShadow && cs.boxShadow !== 'none');
  const out = [];
  for (const c of fm.querySelectorAll('.srf-card')) {
    const cs = getComputedStyle(c);
    const kids = [...c.children].filter(k => k.getBoundingClientRect().height > 1);
    if (!kids.length) continue;
    const cr = R(c), last = R(kids[kids.length - 1]);
    out.push({cls: c.className.trim(), surfaced: surfaced(cs),
              bg: cs.backgroundColor, voidH: +(cr.b - last.b).toFixed(1),
              maxGap: (function(){
                const padT = parseFloat(cs.paddingTop) || 0;
                let prev = cr.t + padT, m = 0;
                kids.forEach(k => { const r = R(k);
                  if (r.t - prev > m) m = r.t - prev; prev = r.b; });
                return +m.toFixed(1); })()});
  }
  return {cards: out};
}"""

SHOW = """()=>{try{if(!SRX.ctx)srxToggleCtx();
  document.getElementById('searchview').classList.add('show-filters');}catch(e){}
  const b=document.getElementById('srxMoreBtn'); if(b)b.click();}"""


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def probe():
    port = _free_port()
    base = "http://127.0.0.1:%d" % port
    srv = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(port)],
                           cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = {}
    try:
        ok = False
        for _ in range(120):
            try:
                urllib.request.urlopen(base + "/api/state", timeout=2)
                ok = True
                break
            except Exception:
                time.sleep(0.4)
        if not ok:
            pytest.skip("demo 服务未起来")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            for w in (1512, 1280):
                pg = br.new_page(viewport={"width": w, "height": 1400})
                pg.goto(base + "/", wait_until="domcontentloaded")
                pg.wait_for_timeout(3000)
                pg.evaluate("switchView('search')")
                pg.wait_for_timeout(1600)
                pg.evaluate(SHOW)
                pg.wait_for_timeout(1600)
                out[w] = pg.evaluate(JS)
                # 负控：强制把 srf-time 变成「可见卡」并注入底部内衬
                pg.add_style_tag(content=(
                    "#searchview .srf-time{background:#fff!important;"
                    "border:1px solid #ccc!important;padding-bottom:80px!important}"))
                pg.wait_for_timeout(400)
                out.setdefault("revert", {})[w] = pg.evaluate(JS)
                pg.close()
            br.close()
        yield out
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()


@pytest.mark.parametrize("w", [1512, 1280])
def test_visible_cards_have_no_tail_void(probe, w):
    d = probe[w]
    assert "err" not in d, d
    cards = d["cards"]
    assert len(cards) >= 2, "%d 档筛选面板没渲染出并排卡：%s" % (w, cards)
    bad = [c for c in cards if c["surfaced"] and c["voidH"] > 34]
    assert not bad, (
        "%d 档以下**卡面可见**的卡底部有 >34px 余量：%s"
        % (w, json.dumps(bad, ensure_ascii=False)))


@pytest.mark.parametrize("w", [1512, 1280])
def test_borderless_cards_are_not_judged_by_geometry(probe, w):
    """卡面无边界时，卡底几何留白不可作为缺陷判据。

    这条同时说明：r804 的「修」是判据错误——量的是不可见几何。
    若将来给这些卡加了底色/描边，本条会自动失效（surfaced 变 True 后
    归 test_visible_cards_have_no_tail_void 管），不需要改测试。
    """
    d = probe[w]
    invisible = [c for c in d["cards"] if not c["surfaced"]]
    assert invisible, (
        "%d 档所有卡都变成可见卡面了？请确认 .srf-card 是否新增了底色/描边：%s"
        % (w, json.dumps(d["cards"], ensure_ascii=False)))
    # 即便几何留白很大，也必须仍由「卡内孤立空洞」那条兜住
    for c in invisible:
        assert c["maxGap"] <= 34, (
            "%d 档 %s 卡面不可见，但卡内有 %.1fpx 孤立空洞（>34）——"
            "这才是用户真能看见的缺陷" % (w, c["cls"], c["maxGap"]))


@pytest.mark.parametrize("w", [1512, 1280])
def test_negative_control_visible_card_tail_is_caught(probe, w):
    """负控：把 srf-time 变成可见卡 + 80px 底部内衬，第 1 条判据必须抓红。"""
    d = probe["revert"][w]
    hit = [c for c in d["cards"] if "srf-time" in c["cls"]]
    assert hit, "%d 档负控里找不到 srf-time" % w
    c = hit[0]
    assert c["surfaced"], "%d 档负控注入的底色没生效（卡面仍判为不可见）" % w
    assert c["voidH"] > 34, (
        "%d 档负控无效：注入 80px 底部内衬后卡底只有 %.1fpx，"
        "说明判据没量到卡底余量" % (w, c["voidH"]))
