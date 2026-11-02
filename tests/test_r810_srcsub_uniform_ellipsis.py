# -*- coding: utf-8 -*-
"""r810 门禁：五源卡副标题在各档必须是同一种溢出语法（省略号），不许硬切。

实测缺陷（修前 1024 档）：`@media(min-width:761px) and (max-width:1100px)`
给 `.srx-src-sub` 写的是 `white-space:normal;overflow:visible;text-overflow:clip`，
本意是允许折行；但 v298b 平面收口块里有
`.srx-src-sub{white-space:nowrap!important}`，把它压掉了 ——
于是 761–1100 档变成 **nowrap + overflow:visible + clip**：
文字溢出后由父级 `.srx-src{overflow:hidden!important}` 硬裁，**没有省略号**。
同元素 ≥1101 档是 `overflow:hidden/ellipsis`（正常省略），
所以同一张卡「换个窗口换个溢出语法」，用户读作不干净。

判据：任一档里 `.srx-src-sub` 只要内容放不下（scrollW > clientW + 1），
就必须 `overflow !== 'visible'` 且 `text-overflow === 'ellipsis'`。
负控：把 761–1100 档注回 `overflow:visible;text-overflow:clip`，1024 档必红。
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

M = r"""() => {
  const vis = e => { const r = e.getBoundingClientRect();
    return r.width > 1 && r.height > 1 && e.offsetParent !== null; };
  const list = [...document.querySelectorAll('#searchview .srx-src-sub')].filter(vis);
  return list.map(e => {
    const cs = getComputedStyle(e);
    return {txt: (e.textContent || '').trim().slice(0, 20),
            scrollW: e.scrollWidth, clientW: e.clientWidth,
            lost: e.scrollWidth - e.clientWidth,
            ws: cs.whiteSpace, ovf: cs.overflow, te: cs.textOverflow};
  });
}"""

# 负控要精确复现**修复前实际生效**的组合：
#   white-space 保持 nowrap（v298b 那条 !important 压掉了 normal），
#   只把 overflow/text-overflow 退回 visible/clip。
# 不能连 white-space 一起注回 normal——那等于真的允许换行，lost 会归零，
# 判据自然抓不到（第一版负控就是这么失效的）。
# 10 渠道后来源卡在 1024 档宽 220px，副标题已完整放下（lost=0）；
# 负控额外压窄卡片，确保注回 clip 后确有溢出可抓。
REVERT = ("@media(min-width:761px) and (max-width:1100px){"
          "#searchview .srx-brief .srx-src{flex:0 0 80px!important}"
          "#searchview .srx-src-sub{white-space:nowrap!important;"
          "overflow:visible!important;text-overflow:clip!important}}")


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
            for w in (1512, 1100, 1024, 900):
                pg = br.new_page(viewport={"width": w, "height": 1200})
                pg.goto(base + "/", wait_until="domcontentloaded")
                pg.wait_for_timeout(3000)
                pg.evaluate("switchView('search')")
                pg.wait_for_timeout(1600)
                pg.evaluate("()=>{try{srxToggleOverview()}catch(e){}}")
                pg.wait_for_timeout(1200)
                out[w] = pg.evaluate(M)
                if w == 1024:
                    pg.add_style_tag(content=REVERT)
                    pg.wait_for_timeout(400)
                    out["revert"] = pg.evaluate(M)
                pg.close()
            br.close()
        yield out
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()


@pytest.mark.parametrize("w", [1512, 1100, 1024, 900])
def test_subtitle_uses_ellipsis_when_overflowing(probe, w):
    d = probe[w]
    assert d, "%d 档没有可见的 .srx-src-sub（探针抓不到，本档无结论）" % w
    bad = [r for r in d if r["lost"] > 1
           and (r["ovf"] == "visible" or r["te"] != "ellipsis")]
    assert not bad, (
        "%d 档副标题溢出却没有省略号（硬切）：%s"
        % (w, json.dumps(bad, ensure_ascii=False)))


def test_negative_control_clip_grammar_is_caught(probe):
    """负控：注回 761–1100 的 normal/visible/clip，1024 档必须被判据抓红。"""
    d = probe["revert"]
    bad = [r for r in d if r["lost"] > 1
           and (r["ovf"] == "visible" or r["te"] != "ellipsis")]
    assert bad, (
        "负控无效：注回 clip 语法后 1024 档仍判为合格（%s）"
        % json.dumps(d, ensure_ascii=False)[:300])
