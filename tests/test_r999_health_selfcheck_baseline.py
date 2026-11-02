# -*- coding: utf-8 -*-
"""r999 门禁：渠道健康五张诊断卡的「自检」必须落在同一条水平线上。

用户反复点名：「渠道健康里又有不对齐的布局设计，自检按钮」。

r845 为「徽标不被省略号截断」把 ≤1024 档卡头改成 `flex-wrap:wrap`；
但五张卡的状态文字长短不同——实测 1024 档「智行/途牛」卡头 17.4px、
其余 35.9px；900 档「智行/途牛」动作说明 15.9px、飞猪/同程 31.9px
（文案更长）。于是同一排五颗「自检」落在 522.8 / 541.3 / 557.3 三个
纵坐标（900 档两档差 16px）。

修法：卡头回到单行（r557 的收缩 + 省略规则接管，全文仍在 title 里）；
动作说明行定高两行并裁剪。五行高度不再随文案长短变化。

判据：同一档内五颗「自检」的 top 只能有一个取值、尺寸必须一致，
且横坐标等距（五等分网格）。
负控：把卡头恢复成 `flex-wrap:wrap`、动作行去掉定高，top 必分裂 → 红。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = _free_port()
BASE = "http://127.0.0.1:%d" % PORT

JS = r"""() => {
  const vis = e => e.offsetParent !== null
    && e.getBoundingClientRect().width > 1 && e.getBoundingClientRect().height > 1;
  const cards = [...document.querySelectorAll('#healthDiag .hdiag-card')];
  const btn = c => [...c.querySelectorAll('button')].filter(b => vis(b)
    && /自检/.test(b.textContent))[0];
  const boxes = cards.map(c => {
    const b = btn(c);
    if (!b) return null;
    const r = b.getBoundingClientRect();
    return {l: +r.left.toFixed(1), t: +r.top.toFixed(1),
            w: +r.width.toFixed(1), h: +r.height.toFixed(1)};
  });
  const rows = cards.map(c => {
    const h = c.querySelector(':scope > .hdiag-h');
    const l = c.querySelector(':scope > .hdiag-l');
    const a = c.querySelector(':scope > .hdiag-a');
    const g = e => e ? +e.getBoundingClientRect().height.toFixed(1) : null;
    return {head: g(h), line: g(l), act: g(a)};
  });
  return {n: cards.length,
          expect: (typeof SRX_PLATS !== 'undefined')
            ? Object.keys(SRX_PLATS).length : 0,
          boxes: boxes, rows: rows,
          cardTops: cards.map(c =>
            +c.getBoundingClientRect().top.toFixed(1))};
}"""

# 负控：还原 r999 之前的写法（卡头/登录行无最小高度 + 动作行不定高）
REVERT = """
.hdiag[data-n="7"] .hdiag-h{min-height:0!important}
.hdiag[data-n="7"] .hdiag-l{min-height:0!important}
@media(max-width:1024px){
 .hdiag[data-n="5"] .hdiag-h{min-height:0!important}
}
.hdiag-a{min-height:0!important;-webkit-line-clamp:unset!important;
 display:block!important;overflow:visible!important}
"""


@pytest.fixture(scope="module")
def probe():
    srv = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(PORT)],
                           cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = {}
    try:
        ok = False
        for _ in range(90):
            try:
                urllib.request.urlopen(BASE + "/api/state", timeout=2)
                ok = True
                break
            except Exception:
                time.sleep(0.5)
        if not ok:
            pytest.skip("demo 服务未起来")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            for w in (1512, 1280, 1024, 900, 768):
                pg = br.new_page(viewport={"width": w, "height": 1000})
                pg.goto(BASE + "/", wait_until="domcontentloaded")
                pg.wait_for_timeout(2800)
                pg.evaluate("switchView('mon')")
                pg.wait_for_timeout(800)
                pg.evaluate("showMonTab('health')")
                pg.wait_for_timeout(2000)
                out[w] = pg.evaluate(JS)
                if w in (1512, 768):
                    pg.add_style_tag(content=REVERT)
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


@pytest.mark.parametrize("w", [1512, 1280, 1024, 900, 768])
def test_self_check_buttons_share_one_baseline(probe, w):
    """每张诊断卡的「自检」必须同 top、同尺寸；卡内行高一致。

    卡数按注册渠道派生（演示为 5 浏览器 + 2 App = 7），不写死 5——
    恢复 App 诊断卡后旧断言会假红。
    """
    d = probe[w]
    assert d["expect"] >= 5, "%d 档读不到注册渠道数：%s" % (w, d["expect"])
    assert d["n"] == d["expect"], "%d 档诊断卡不是注册渠道数：%s" % (w, d)
    boxes = [b for b in d["boxes"] if b]
    assert len(boxes) == d["n"], "%d 档有卡没渲染出自检按钮" % w
    # 对齐是**行内**约束：7 张在 4+3 布局下两行各有一个 top 是正常的；
    # 要求全卡同一个 top 只在「一行看完」的宽度成立（旧 5 卡断言）。
    byrow = {}
    for b, ct in zip(boxes, d["cardTops"]):
        byrow.setdefault(ct, []).append(b)
    for row in byrow.values():
        tops = {b["t"] for b in row}
        assert len(tops) == 1, (
            "%d 档同一行「自检」纵向分裂成 %d 个 top 值 %s（整卡 %s）"
            % (w, len(tops), sorted(tops), d["boxes"]))
    sizes = {(b["w"], b["h"]) for b in boxes}
    assert len(sizes) == 1, "%d 档自检按钮尺寸不一：%s" % (w, sizes)
    # 卡内三行（卡头 / 登录·Cookie·最近轮次 / 动作说明）高度必须逐卡一致——
    # 它们是把按钮推下去的原因。r999c：登录行也会折行（1024 档去哪儿实测
    # 47.5 vs 其余 31），单靠前两行定高仍会有 16.5px 错位。
    for key in ("head", "line", "act"):
        hs = {r[key] for r in d["rows"]}
        assert len(hs) == 1, (
            "%d 档 %s 行高五张不一致：%s（按钮会因此错位）"
            % (w, key, [r[key] for r in d["rows"]]))


@pytest.mark.parametrize("w", [1512, 768])
def test_negative_control_restores_split_baseline(probe, w):
    """负控：撤掉定高后「自检」必须重新分裂，否则判据没打到定高规则。

    负控宽度取 1512/768：7 张卡在这两档分别是 175/167px，长状态词/
    「去哪儿」登录行会折行；撤掉地板后必然出现 1 行 vs 2/3 行的高度差。
    """
    d = probe["revert"][w]
    tops = {b["t"] for b in d["boxes"] if b}
    assert len(tops) > 1, (
        "%d 档负控无效：撤掉定高后「自检」仍同 top（%s），"
        "说明这条判据量的不是卡头/登录行/动作行定高" % (w, sorted(tops)))
