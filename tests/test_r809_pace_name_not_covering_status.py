# -*- coding: utf-8 -*-
"""r809 门禁：渠道节流表的渠道名不得压进右侧状态列。

实测缺陷（修前，1512/1024/600/390 四档一致）：
  `.pace` 品牌列固定 `--pcol:64px`（注释写明要与上方健康行同一条竖线），
  但「去哪儿 App」需要 84px。`.nm` 只有 `min-width:0`、没有 overflow 约束，
  于是文字**溢出盒外**：文本右缘 125.8 越过状态列左缘 116，
  **压进状态列 9.8px**——截图上「App」被状态徽标盖掉，读作「去哪儿」
  （PC 渠道），与 App 渠道事实不符。
  `.nm` 是 `inline-flex`，直接给它 `text-overflow:ellipsis` 不生效
  （文字成了匿名 flex item）——必须给名字单独包一层 `.nm-t`。

判据（渲染几何 + 计算样式）：
  1. 每个渠道名的文本右缘 ≤ 状态列左缘（`overlap <= 0.5px`）；
  2. 名字若放不下，承载它的 `.nm-t` 必须 `text-overflow:ellipsis`
     且 `overflow != visible`（真省略号，不是硬切）；
  3. `.nm` / `.nm-t` 必须有 `title`（全称可达）；
  4. 品牌列宽仍是 64px（与健康行同竖线的设计约束未被这条修复破坏）。
负控：把 `.nm-t` 的 overflow 注回 `visible`，压列必须复现（>5px）。
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
  // elementFromPoint 对视口外的点返回 null——先滚到节流表，否则负控永远探不到。
  const pace = document.querySelector('.pace');
  if (pace) pace.scrollIntoView({block: 'center'});
  const rows = [...document.querySelectorAll('.pace-row')];
  const out = [];
  let cols = null;
  for (const r of rows) {
    const nm = r.querySelector('.nm'), st = r.querySelector('.st');
    if (!nm || !st || nm.getBoundingClientRect().width < 1) continue;
    if (cols === null) cols = getComputedStyle(r).gridTemplateColumns;
    const nt = nm.querySelector('.nm-t');
    const ncs = nt ? getComputedStyle(nt) : null;
    const nr = nm.getBoundingClientRect();
    const sr = st.getBoundingClientRect();
    // **不能**用 Range 量「文字有没有压过去」：Range 返回的是布局矩形，
    // 不受 overflow 裁剪——已实测正控下 Range 右缘仍越过状态列 9.8px。
    // 真正该问的是「盒外的可见像素属于谁」→ elementFromPoint。
    const probeX = Math.min(nr.right + 2, sr.left - 1);
    const probeY = nr.top + nr.height / 2;
    const hitEl = document.elementFromPoint(probeX, probeY);
    const leaked = !!hitEl && (hitEl === nm || nm.contains(hitEl));
    const textRight = nr.right;
    out.push({txt: (nm.textContent || '').trim(),
              overlap: +(textRight - sr.left).toFixed(1),
              leaked,
              hasT: !!nt,
              te: ncs ? ncs.textOverflow : null,
              ovf: ncs ? ncs.overflow : null,
              lost: nt ? nt.scrollWidth - nt.clientWidth : 0,
              title: nm.getAttribute('title') || (nt && nt.getAttribute('title')) || ''});
  }
  return {cols: cols, n: out.length, rows: out};
}"""

# 负控不能用 CSS 构造：修复前是**裸文本节点**（匿名 flex item，不可收缩），
# 加 .nm-t 之后就一定有可收缩层了。要精确复现旧形态，只能在 DOM 里把
# 包层拆掉、把文字退回成裸节点。
UNWRAP = r"""() => {
  const rows = [...document.querySelectorAll('.pace-row')];
  let n = 0;
  for (const r of rows) {
    const nm = r.querySelector('.nm');
    const t = nm && nm.querySelector('.nm-t');
    if (!t) continue;
    const txt = t.textContent;
    nm.removeChild(t);
    nm.appendChild(document.createTextNode(txt));
    n++;
  }
  return n;
}"""


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
            for w in (1512, 1024, 600, 390):
                pg = br.new_page(viewport={"width": w, "height": 1200})
                pg.goto(base + "/", wait_until="domcontentloaded")
                pg.wait_for_timeout(3000)
                pg.evaluate("switchView('mon')")
                pg.wait_for_timeout(900)
                pg.evaluate("(()=>{try{showMonTab('health')}catch(e){}})()")
                pg.wait_for_timeout(2000)
                out[w] = pg.evaluate(M)
                out.setdefault("unwrappedN", {})[w] = pg.evaluate(UNWRAP)
                pg.wait_for_timeout(400)
                out.setdefault("revert", {})[w] = pg.evaluate(M)
                pg.close()
            br.close()
        yield out
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()


@pytest.mark.parametrize("w", [1512, 1024, 600, 390])
def test_channel_name_never_covers_status_column(probe, w):
    d = probe[w]
    assert d["n"] >= 2, "%d 档节流表没渲染出渠道行：%s" % (w, d)
    bad = [r for r in d["rows"] if r["overlap"] > 0.5 or r["leaked"]]
    assert not bad, (
        "%d 档渠道名压进状态列（盒越界或盒外仍有名字像素）：%s"
        % (w, json.dumps(bad, ensure_ascii=False)))


@pytest.mark.parametrize("w", [1512, 1024, 390])
def test_long_name_uses_ellipsis_with_full_text_in_title(probe, w):
    d = probe[w]
    long_names = [r for r in d["rows"] if r["lost"] > 1]
    if not long_names:
        pytest.skip("%d 档没有放不下的渠道名，本档无结论" % w)
    for r in long_names:
        assert r["hasT"], "%d 档「%s」没有 .nm-t 包裹层，ellipsis 不生效" % (w, r["txt"])
        assert r["te"] == "ellipsis" and r["ovf"] != "visible", (
            "%d 档「%s」放不下（lost %s）却没有省略号：text-overflow=%s overflow=%s"
            % (w, r["txt"], r["lost"], r["te"], r["ovf"]))
        assert r["title"].strip(), (
            "%d 档「%s」被省略但没有 title——全称无法到达" % (w, r["txt"]))


@pytest.mark.parametrize("w", [1512, 1024, 600, 390])
def test_brand_column_width_unchanged(probe, w):
    """品牌列仍是 64px：与上方健康行同一条竖线，不许被这条修复撑开。"""
    d = probe[w]
    assert d["cols"], "%d 档读不到 grid-template-columns" % w
    assert d["cols"].split(" ")[0] == "64px", (
        "%d 档品牌列变成 %s——与健康行竖线对齐的设计约束被破坏"
        % (w, d["cols"].split(" ")[0]))


@pytest.mark.parametrize("w", [1512, 390])
def test_negative_control_removing_overflow_covers_again(probe, w):
    """负控：撤掉 .nm-t 的 overflow，压列必须复现。"""
    assert probe["unwrappedN"][w] > 0, "%d 档负控没拆到 .nm-t" % w
    d = probe["revert"][w]
    leaked = [r for r in d["rows"] if r["leaked"]]
    assert leaked, (
        "%d 档负控无效：把名字退回裸文本后，盒外仍探不到名字像素（%s）"
        % (w, json.dumps(d["rows"], ensure_ascii=False)[:300]))
