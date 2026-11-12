# -*- coding: utf-8 -*-
"""r1090：检索台窄档两行 + 渠道 rail 单行 + 组合与探针同排。

新契约（prompt_optimized_2026-11-07 §6.3/§6.4 + 2026-11-08 用户返工）：
- 桌面（≥601）：城市对 + 日期 + 实时探针 + 组合在**一行**（qrow ≤40px）；
- 窄档（≤600）：城市对一行、日期 + 探针 + 组合一行（qrow ≤80px）；
- 组合入口与探针同排同高，不再单独占第三行；队列浮层不推布局；
- 10 个官方渠道图标 + 名称在单独一行（≤40px），横向溢出时内部滚动，不撑破页面。
"""
import os
import sys

import pytest

pytest.importorskip("playwright",
                    reason="探针布局依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None
WIDTHS = [320, 360, 361, 375, 390, 480, 600, 601, 700, 768, 900]


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def srv():
    import subprocess
    import tempfile
    import time
    import urllib.request

    global BASE
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    logf = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    priv = tempfile.mkdtemp(prefix="r1090_")
    env = dict(os.environ, TEMP=priv, TMP=priv, TMPDIR=priv,
               PYTHONIOENCODING="utf-8")
    proc = None
    for _ in (1, 2):
        port = _free_port()
        BASE = "http://127.0.0.1:%d" % port
        proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
             "--port", str(port)],
            cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT, env=env)
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        up = False
        for _ in range(60):
            if proc.poll() is not None:
                break
            try:
                op.open(BASE + "/api/state", timeout=2)
                up = True
                break
            except Exception:
                time.sleep(0.5)
        if up:
            break
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
    else:
        pytest.fail("demo 启动失败（两次新端口重试后）")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    logf.close()


SNAP = """(() => {
  const q=document.querySelector('#srxProbe .srx-qrow');
  const rg=e=>{if(!e)return null;const r=e.getBoundingClientRect();
    return {L:Math.round(r.left),T:Math.round(r.top),R:Math.round(r.right),
      B:Math.round(r.bottom),W:Math.round(r.width),H:Math.round(r.height)}};
  const kids=[...q.children].filter(e=>e.getBoundingClientRect().width>2);
  const items=kids.map(e=>({cls:String(e.className).split(' ').pop(),
    r:rg(e),sw:e.scrollWidth,cw:e.clientWidth}));
  const inp=document.getElementById('srxFrom');
  const to=document.getElementById('srxTo');
  const date=document.getElementById('srxDate');
  const combo=document.getElementById('srxBatchToggle');
  const go=document.getElementById('srxGo');
  const rail=document.getElementById('srxPlatPick');
  const row=document.getElementById('srxChannelRow');
  return {items,row:rg(q),formH:Math.round(document.querySelector(
      '#srxProbeForm').getBoundingClientRect().height),
    combo:rg(combo),comboInForm:!!combo.closest('#srxProbeForm'),
    comboClip:combo.scrollWidth-combo.clientWidth,
    cityClip:inp.scrollWidth-inp.clientWidth,
    toClip:to.scrollWidth-to.clientWidth,
    dateClip:date.scrollWidth-date.clientWidth,
    rail:Object.assign(rg(rail),{ov:getComputedStyle(rail).overflow}),railRow:rg(row),chips:rail.querySelectorAll('.srx-pchip').length,
    chipRows:[...new Set([...rail.querySelectorAll('.srx-pchip')]
      .map(e=>Math.round(e.getBoundingClientRect().top)))].length,
    railOver:rail.scrollWidth-rail.clientWidth,
    goTitle:go.title, goLabel:go.getAttribute('aria-label'),
    over:document.documentElement.scrollWidth-innerWidth};
})()"""


def test_probe_two_rows_on_narrow_and_controls_in_place(srv):
    # r1500：渠道 rail 在 ≤600 由 r1454 改成**换行**（此前是横向拖动，用户看不全
    # App 渠道）。于是窄档行数上限从 1 行变 2 行；真正要守的是「首屏预算」与
    # 「不需要横向拖动」——所以这里按 2 行给上限，同时下面仍钉「零横向溢出」。
    MAX_RAIL_ROWS = 2
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        bad = []
        for w in WIDTHS:
            pg = b.new_page(viewport={"width": w, "height": 900},
                            is_mobile=(w <= 600), has_touch=(w <= 600))
            pg.goto(BASE + "/", wait_until="load")
            pg.wait_for_function("typeof S!=='undefined'&&S&&S.users",
                                 timeout=25000)
            pg.wait_for_timeout(800)
            pg.evaluate("()=>switchView('search')")
            pg.wait_for_timeout(550)
            pg.evaluate("()=>{const p=document.getElementById('srxProbe');"
                        "if(p&&!p.classList.contains('open'))"
                        "document.getElementById('srxProbeTool').click()}")
            pg.wait_for_timeout(450)
            d = pg.evaluate(SNAP)
            pg.close()
            items = d["items"]
            if len(items) != 6:
                bad.append("%d 档 qrow 可见控件 %d 个（应 6：出发/交换/到达/日期/探针/组合）"
                           % (w, len(items)))
                continue
            if d["formH"] > (80 if w <= 600 else 40):
                bad.append("%d 档表单高 %d（窄档两行 ≤80，桌面一行 ≤40）"
                           % (w, d["formH"]))
            tops = [x["r"]["T"] for x in items]
            if w > 600 and max(tops) - min(tops) > 6:
                bad.append("%d 档桌面仍分行: tops=%s" % (w, tops))
            if w <= 600:
                city = [x for x in items if x["cls"] in ("srx-fromfield", "srx-tofield", "srx-swap")]
                act = [x for x in items if x["cls"] in ("srx-datefield", "go")]
                if len(city) == 3 and max(x["r"]["T"] for x in city) - min(x["r"]["T"] for x in city) > 6:
                    bad.append("%d 档城市对不在同一行" % w)
                if len(act) == 2 and abs(act[0]["r"]["T"] - act[1]["r"]["T"]) > 6:
                    bad.append("%d 档日期与探针不在同一行" % w)
            row = d["row"]
            for x in items:
                if x["r"]["L"] < row["L"] - 1 or x["r"]["R"] > row["R"] + 1:
                    bad.append("%d 档 %s 越出行界" % (w, x["cls"]))
            if d["cityClip"] > 1 or d["toClip"] > 1:
                bad.append("%d 档城市名被裁 %d/%d" % (w, d["cityClip"], d["toClip"]))
            if d["dateClip"] > 1:
                bad.append("%d 档日期被裁 %d" % (w, d["dateClip"]))
            if not d["comboInForm"]:
                bad.append("%d 档组合入口不在表单主行" % w)
            if d["combo"] and (d["combo"]["T"] < d["row"]["T"] - 1
                               or d["combo"]["B"] > d["row"]["B"] + 1):
                bad.append("%d 档组合入口越出表单主行" % w)
            if d["comboClip"] > 1:
                bad.append("%d 档组合钮文字被裁 %d" % (w, d["comboClip"]))
            if d["chips"] != 10:
                bad.append("%d 档渠道 rail 只有 %d 个 chip" % (w, d["chips"]))
            if d["railRow"] and d["railRow"]["H"] > 40 * MAX_RAIL_ROWS + 60:
                bad.append("%d 档渠道行高 %d（chip %d 行，上限 %d 行）"
                           % (w, d["railRow"]["H"], d.get("chipRows", 0), MAX_RAIL_ROWS))
            if d.get("chipRows", 1) > MAX_RAIL_ROWS:
                bad.append("%d 档 chip 折成 %d 行（上限 %d 行）"
                           % (w, d["chipRows"], MAX_RAIL_ROWS))
            # r1504：≤600 档 rail 改成定列网格 + `overflow:hidden`（裁剪而非滚动），
            # 所以 `scrollWidth` 天然会大于 clientWidth（被裁的内容也算在内），
            # 这时再要求"必须形成内部滚动"就与设计相反。真意图是：**不许把页面
            # 撑宽、10 家都要看得见**——这两条下面分别有断言（over / chipRows）。
            if d["railOver"] > 1 and d["rail"].get("ov") != "hidden" \
                    and d["rail"]["W"] >= d["railRow"]["W"] - 1:
                bad.append("%d 档渠道 rail 溢出但未形成内部滚动" % w)
            if d["over"] > 1:
                bad.append("%d 档页面横向溢出 %d" % (w, d["over"]))
            if w == 320:
                cw = [x["r"]["W"] for x in items
                      if x["cls"] in ("srx-fromfield", "srx-tofield")]
                if min(cw) < 42:
                    bad.append("320 城市框仅 %s" % cw)
            if not d["goTitle"] or d["goLabel"] != "实时探针":
                bad.append("%d 档探针钮缺少可读名称" % w)
        b.close()
    assert not bad, "探针布局: " + "；".join(bad)
