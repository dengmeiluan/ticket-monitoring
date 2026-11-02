# -*- coding: utf-8 -*-
"""r812 门禁：展开体必须紧贴触发器，中间不许夹「常驻」元素。

用户原话：「展开概览那个明显交互有问题，展开的中间还有元素常驻」
「说明的展开是在检索控制台的下面！展开收起怎么能中间有元素呢？」

判据只说一件事：**点击前就已经可见**的元素，不许出现在
「触发器底边 → 展开体顶边」之间（与触发器横向重叠 ≥8px、有可见边界）。
展开后才出现的摘要/说明/详情是展开内容本身，不算夹层。
另要求触发器两态坐标差 ≤2px、展开体可见且不在触发器上方。

覆盖 7 类折叠（检索概览/探针、健康说明/溯源、明细筛选/行比价、
关注更多条件）× 1512/1024/430 三档；负控=往区间里塞一块可见的常驻
元素，判据必须报红，证明它量的是渲染真相而不是恒真。
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

FOLDS = ("overview", "probe", "note", "trace", "flt", "row", "watch")


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


JS = r"""async (kind) => {
  const vis = e => { const r = e.getBoundingClientRect(); const cs = getComputedStyle(e);
    return cs.display !== 'none' && cs.visibility !== 'hidden' && r.width > 1 && r.height > 1
      && e.offsetParent !== null; };
  const painted = n => { const cs = getComputedStyle(n);
    return cs.backgroundColor !== 'rgba(0, 0, 0, 0)' || parseFloat(cs.borderTopWidth) > 0
      || parseFloat(cs.borderBottomWidth) > 0 || cs.boxShadow !== 'none'
      || ((n.textContent || '').trim().length > 0 && n.children.length === 0); };
  const d = v => +(+v).toFixed(1);

  let trig = null, body = null, requery = null, label = kind;
  if (kind === 'overview') {
    const v = document.getElementById('searchview');
    if (!v.classList.contains('srx-ov-collapsed')) { srxToggleOverview(); await new Promise(r=>setTimeout(r,400)); }
    trig = document.getElementById('srxOvHero');
    body = document.getElementById('srxBandBody');
  } else if (kind === 'probe') {
    /* 2026-11-01 起探针卡改成单行控制条：卡内「收起探针」只在卡展开时可见，
       卡收起时整块 display:none，**唯一入口**是工具行里的 #srxProbeTool。
       从关闭态起测时必须点外部入口，否则点的是一个用户点不到的隐藏按钮。 */
    const p = document.getElementById('srxProbe');
    if (p.classList.contains('open')) { srxToggleProbe(); await new Promise(r=>setTimeout(r,300)); }
    const inner = document.getElementById('srxProbeToggle');
    if (inner && vis(inner)) { trig = inner; body = document.getElementById('srxProbeForm'); }
    else { trig = document.getElementById('srxProbeTool'); body = p; }
  } else if (kind === 'note') {
    trig = document.getElementById('scNoteBtn');
    body = document.getElementById('scNote');
  } else if (kind === 'flt') {
    const w = document.getElementById('fltwrap');
    if (w.classList.contains('open')) { togFlt(); await new Promise(r=>setTimeout(r,300)); }
    trig = document.getElementById('fltBtn');
    body = w;
  } else if (kind === 'watch') {
    if (WS.more) { document.querySelector('[data-wsmore]').click(); await new Promise(r=>setTimeout(r,400)); }
    trig = document.querySelector('[data-wsmore]');
    body = document.getElementById('wsMoref');
    requery = () => document.querySelector('[data-wsmore]');
  } else if (kind === 'row') {
    trig = [...document.querySelectorAll('#ftable tbody tr[aria-expanded="false"]')].find(vis);
  } else if (kind === 'trace') {
    trig = [...document.querySelectorAll('#paceBox button[data-pk$=":trace"]')].find(vis);
  }
  if (!trig) return {kind, err: 'no-trigger'};
  const pk = kind === 'trace' ? trig.getAttribute('data-pk') : null;
  trig.scrollIntoView({block: 'center'});
  await new Promise(r => setTimeout(r, 220));

  const rb0 = trig.getBoundingClientRect();
  const trigWasVisible = vis(trig);
  const before = new Set();
  for (const n of document.querySelectorAll('#searchview *, #monview *, #cfgview *')) {
    if (vis(n) && painted(n)) before.add(n);
  }
  const sy = scrollY;
  trig.click();
  await new Promise(r => setTimeout(r, kind === 'trace' ? 900 : 500));

  let t2 = requery ? requery() : trig;
  if (kind === 'row') {
    let nx = t2 && t2.nextElementSibling;
    if (nx && nx.classList.contains('tgrow')) nx = nx.nextElementSibling;
    body = nx;
  } else if (kind === 'trace') {
    /* 重渲会换掉整行节点：按 data-pk 找回**那颗按钮**再比坐标——
       拿行去比按钮会量出 12px 纵向、上千像素横向的假位移。 */
    t2 = [...document.querySelectorAll('#paceBox button[data-pk$=":trace"]')]
      .find(b => b.getAttribute('data-pk') === pk);
    body = document.getElementById('paceDetail');
  } else if (kind === 'watch') {
    body = document.getElementById('wsMoref');
  }
  if (!t2) return {kind, err: 'trigger-gone'};
  if (!body || !vis(body)) return {kind, err: 'body-hidden'};
  const rb1 = t2.getBoundingClientRect(), rbb = body.getBoundingClientRect();

  const L = Math.max(rb1.left, rbb.left) + 1, R = Math.min(rb1.right, rbb.right) - 1;
  const mid = [];
  if (R - L >= 8) for (const n of before) {
    if (!n.isConnected || !vis(n)) continue;
    if (n === t2 || t2.contains(n) || n.contains(t2)) continue;
    if (n === body || body.contains(n) || n.contains(body)) continue;
    const r = n.getBoundingClientRect();
    if (r.top < rb1.bottom - 1 || r.bottom > rbb.top + 1) continue;
    if (Math.min(r.right, R) - Math.max(r.left, L) < 8) continue;
    mid.push({tag: n.tagName.toLowerCase(), id: n.id,
              cls: (n.className.toString() || '').slice(0, 20),
              txt: (n.textContent || '').trim().slice(0, 14)});
  }
  const out = {kind, trigWasVisible, bodyVisible: true,
               moved: d(rb1.top - rb0.top), movedX: d(rb1.left - rb0.left),
               gap: d(rbb.top - rb1.bottom), scrollDy: d(scrollY - sy),
               mid: mid.slice(0, 5)};

  // 复位，保证同类下一档从收起态开始
  if (kind === 'trace') { const b2 = [...document.querySelectorAll('#paceBox button[data-pk$=":trace"]')]
      .find(x => x.getAttribute('data-pk') === pk); if (b2) b2.click(); }
  else if (kind === 'row') { t2.click(); }
  else if (kind === 'watch') { const b2 = requery(); if (b2) b2.click(); }
  else {
    const b2 = (kind === 'overview') ? document.getElementById('srxOvHero')
      : (kind === 'probe') ? (vis(document.getElementById('srxProbeToggle'))
            ? document.getElementById('srxProbeToggle')
            : document.getElementById('srxProbeTool'))
      : (kind === 'note') ? document.getElementById('scNoteBtn')
      : document.getElementById('fltBtn');
    if (b2) b2.click();
  }
  return out;
}"""

POSCTL = r"""() => {
  const vis = e => { const r = e.getBoundingClientRect(); const cs = getComputedStyle(e);
    return cs.display !== 'none' && cs.visibility !== 'hidden' && r.width > 1 && r.height > 1
      && e.offsetParent !== null; };
  const painted = n => { const cs = getComputedStyle(n);
    return cs.backgroundColor !== 'rgba(0, 0, 0, 0)' || parseFloat(cs.borderTopWidth) > 0
      || parseFloat(cs.borderBottomWidth) > 0 || cs.boxShadow !== 'none'
      || ((n.textContent || '').trim().length > 0 && n.children.length === 0); };
  const trig = document.getElementById('scNoteBtn');
  const body = document.getElementById('scNote');
  if (!trig || !body) return {err: 'no node'};
  trig.scrollIntoView({block: 'center'});
  const before = new Set();
  for (const n of document.querySelectorAll('#searchview *, #monview *')) {
    if (vis(n) && painted(n)) before.add(n);
  }
  const rb0 = trig.getBoundingClientRect();
  const rbBody = body.getBoundingClientRect();
  // 高度必须整块落在「触发器底 → 展开体顶」之间，否则会被区间判据正确排除
  const h = Math.max(3, Math.min(18, rbBody.top - rb0.bottom - 3));
  const inj = document.createElement('div');
  inj.id = '__inj_block';
  inj.style.cssText = 'position:absolute;z-index:9999;height:' + h + 'px;background:#ffd0d0;'
    + 'border:1px solid #f00;left:' + (scrollX + rb0.left) + 'px;width:' + rb0.width + 'px;'
    + 'top:' + (scrollY + rb0.bottom + 1) + 'px;';
  document.body.appendChild(inj);
  before.add(inj);
  trig.click();
  const rb1 = trig.getBoundingClientRect(), rbb = body.getBoundingClientRect();
  const L = Math.max(rb1.left, rbb.left) + 1, R = Math.min(rb1.right, rbb.right) - 1;
  const mid = [];
  if (R - L >= 8) for (const n of before) {
    if (!n.isConnected || !vis(n)) continue;
    if (n === trig || trig.contains(n) || n.contains(trig)) continue;
    if (n === body || body.contains(n) || n.contains(body)) continue;
    const r = n.getBoundingClientRect();
    if (r.top < rb1.bottom - 1 || r.bottom > rbb.top + 1) continue;
    if (Math.min(r.right, R) - Math.max(r.left, L) < 8) continue;
    mid.push({id: n.id, tag: n.tagName.toLowerCase()});
  }
  inj.remove();
  trig.click();
  return {mid, gap: +(rbb.top - rb1.bottom).toFixed(1)};
}"""


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
            for w in (1512, 1024, 430):
                ctx = br.new_context(viewport={"width": w, "height": 1000})
                pg = ctx.new_page()
                pg.goto(base + "/", wait_until="domcontentloaded")
                pg.wait_for_timeout(3400)
                pg.evaluate("()=>switchView('search')")
                pg.wait_for_timeout(1400)
                rows = {}
                for kind in ("overview", "probe"):
                    rows[kind] = pg.evaluate(JS, kind)
                    pg.wait_for_timeout(300)
                pg.evaluate("()=>switchView('mon')")
                pg.wait_for_timeout(900)
                pg.evaluate("()=>{try{showMonTab('health')}catch(e){}}")
                pg.wait_for_timeout(1800)
                for kind in ("note", "trace"):
                    rows[kind] = pg.evaluate(JS, kind)
                    pg.wait_for_timeout(300)
                if w == 1512:
                    out["posctl"] = pg.evaluate(POSCTL)
                pg.evaluate("()=>{try{showMonTab('details')}catch(e){}}")
                pg.wait_for_timeout(1600)
                for kind in ("flt", "row"):
                    rows[kind] = pg.evaluate(JS, kind)
                    pg.wait_for_timeout(300)
                pg.evaluate("()=>{try{showMonTab('watch')}catch(e){}}")
                pg.wait_for_timeout(1600)
                rows["watch"] = pg.evaluate(JS, "watch")
                out[w] = rows
                ctx.close()
            br.close()
        yield out
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()


@pytest.mark.parametrize("w", [1512, 1024, 430])
def test_every_fold_measured(probe, w):
    """先证明仪器真的量到了东西：7 类折叠都要有声，否则后面的空断言恒真。"""
    rows = probe[w]
    bad = {k: v for k, v in rows.items() if v.get("err")}
    assert not bad, "%d 档有折叠没量到：%s" % (w, json.dumps(bad, ensure_ascii=False))
    assert set(rows) == set(FOLDS), "%d 档折叠集合不全：%s" % (w, sorted(rows))


@pytest.mark.parametrize("w", [1512, 1024, 430])
def test_body_follows_trigger_without_resident_middle(probe, w):
    rows = probe[w]
    for kind in FOLDS:
        r = rows[kind]
        assert r["bodyVisible"], "%d 档 %s 展开体不可见" % (w, kind)
        assert r["gap"] >= -2, (
            "%d 档 %s 展开体跑到触发器上方（gap=%s，用户：「展开在控制台下面」）"
            % (w, kind, r["gap"]))
        assert not r["mid"], (
            "%d 档 %s 触发器与展开体之间夹着常驻元素：%s"
            % (w, kind, json.dumps(r["mid"], ensure_ascii=False)))
        if r["trigWasVisible"]:
            assert abs(r["moved"]) <= 2 and abs(r["movedX"]) <= 2, (
                "%d 档 %s 触发器开合后位移 %s/%s px（两态须同坐标）"
                % (w, kind, r["moved"], r["movedX"]))
            assert abs(r["scrollDy"]) <= 2, (
                "%d 档 %s 开合伴随滚动 %spx" % (w, kind, r["scrollDy"]))


def test_negative_control_injected_resident_is_caught(probe):
    """负控：往触发器和说明之间塞一块可见常驻元素，判据必须抓到它。"""
    d = probe.get("posctl") or {}
    assert not d.get("err"), d
    ids = [m.get("id") for m in d.get("mid", [])]
    assert "__inj_block" in ids, (
        "注入的常驻块没被抓住（判据失效，前面的阴性结论不可信）：%s"
        % json.dumps(d, ensure_ascii=False))
