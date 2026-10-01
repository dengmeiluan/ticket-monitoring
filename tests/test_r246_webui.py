# -*- coding: utf-8 -*-
"""r246 WebUI 五案行为钉（_scratch/r246_report_webui.md 审计消化）：

W1 (P2-1) KPI 卡航线行跨天段「+1天」断词孤字（360 档实锤）——
brief.cross 与时刻段 depTime-arrTime 包 .nw（词组粒度 nowrap 纪律
同族漏收，与「经郑州」先例同构）。
W2 (P3-1) 价格日历 541-999 带跨行列边界错位——flex-wrap 行内 grow
使 8+7 折行两行格宽漂移（81/93 实测），带内改 grid 等分。
W3 (P3-2) 明细展开/子行 .stl 窄带孤字（360/768）——机场名段与
「航向+📈」组合段词组 nowrap。
W4 (P3-3) 运行脉冲 statline .ssub 360 档「22.2s」孤行——放开折行
时用时段包 nowrap 词组使断点落「·」后整段掉行。
W5 (P3-4) 推送预览弹层 .pvfoot 脚注宽档折行句尾单字悬行——末段
nowrap。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r246_webui.py -q
"""
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

import pytest

pytest.importorskip("playwright",
                    reason="行为钉依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = None
BASE = None


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_up(proc):
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(40):
        if proc.poll() is not None:
            return False
        try:
            op.open(BASE + "/api/state", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


@pytest.fixture(scope="module")
def srv():
    global PORT, BASE
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    logf = tempfile.TemporaryFile(mode="w+", encoding="utf-8",
                                  errors="replace")
    proc = None
    for _attempt in (1, 2):
        PORT = _free_port()
        BASE = "http://127.0.0.1:%d" % PORT
        proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
             "--port", str(PORT)],
            cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT)
        if _wait_up(proc):
            break
        # 诊断落盘（CI 红第一手定性证据）：失败时进程态+服务输出尾
        try:
            logf.flush()
            logf.seek(0)
            sys.stderr.write("[r246 srv attempt %d] poll=%s log_tail=%r\n"
                             % (_attempt, proc.poll(), logf.read()[-400:]))
        except Exception:
            pass
    else:
        try:
            proc.kill()
        except Exception:
            pass
        pytest.fail("demo 启动失败（两次新端口重试后）")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    logf.close()


_JS_ORPHAN = """
(sel) => {
  const out = [];
  for (const el of document.querySelectorAll(sel)) {
    if (!el.offsetParent) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none') continue;
    const rng = document.createRange();
    rng.selectNodeContents(el);
    const rects = [...rng.getClientRects()].filter(r => r.width > 2 && r.height > 2);
    if (rects.length < 2) continue;
    // 真折行=rect 跨行（Y 差 ≥ 行高）：nowrap 容器的 span 边界多
    // rect（同 Y）与 inline 基线错位（Y 差 1-3px）都不是折行——
    // 按字号容差聚类成行后再判（r246 W3 误报双根因）
    const fs = parseFloat(cs.fontSize);
    const rows = [];
    for (const r of rects) {
      const row = rows.find(x => Math.abs(x.top - r.top) < fs * 0.7);
      if (row) row.w += r.width;
      else rows.push({top: r.top, w: r.width});
    }
    if (rows.length < 2) continue;
    const first = rows[0].w, last = rows[rows.length - 1].w;
    if (last < fs * 2.5 && first > last * 3) {
      out.push({cls: (el.className || el.id || el.tagName).toString().slice(0, 30),
                txt: el.textContent.trim().slice(0, 24),
                lastW: Math.round(last), firstW: Math.round(first)});
    }
  }
  return out;
}
"""


def _page_at(srv, width, height=900):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": width, "height": height})
        pg.set_default_timeout(10000)
        pg.goto(BASE, wait_until="domcontentloaded")
        pg.wait_for_timeout(2000)
        yield pg
        b.close()


def _at(srv, width, height=900):
    """上下文管理形态的视口页（每测独立 context，状态零残留）。"""
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": width, "height": height})
    pg.set_default_timeout(10000)
    pg.goto(BASE, wait_until="domcontentloaded")
    pg.wait_for_timeout(2000)
    try:
        yield pg
    finally:
        b.close()
        pw.stop()


def test_w1_kpi_cross_no_orphan(srv):
    """360 档概览 KPI 航线行：跨天段/时刻段断词孤字清零（修复前
    「+1/天」末行 12px 孤字两处实锤）。"""
    for pg in _at(srv, 360):
        orph = pg.evaluate(_JS_ORPHAN, ".kpi .fb")
        assert not orph, orph


def test_w3_stl_no_orphan(srv):
    """360/768 档明细子行 .stl：孤字清零（修复前 12-16px 末行）。"""
    for w in (360, 768):
        for pg in _at(srv, w):
            pg.evaluate("switchView('mon');showMonTab('details');")
            pg.wait_for_timeout(600)
            orph = pg.evaluate(_JS_ORPHAN, ".stl")
            assert not orph, (w, orph)


def test_w4_ssub_no_orphan(srv):
    """360 档运行脉冲 statline 子行：用时孤行清零（修复前「22.2s」
    末行 25px）。"""
    for pg in _at(srv, 360):
        orph = pg.evaluate(_JS_ORPHAN, ".stat .ssub")
        assert not orph, orph


def test_w5_pvfoot_no_orphan(srv):
    """768 档推送预览弹层脚注：句尾单字悬行清零（修复前末行 11px）。"""
    for pg in _at(srv, 768):
        pg.evaluate("previewPush()")
        pg.wait_for_timeout(500)
        orph = pg.evaluate(_JS_ORPHAN, ".pvfoot")
        assert not orph, orph


def test_w2_calgrid_row_aligned(srv):
    """768/390 档价格日历跨行等宽：grid 等分后各行格宽一致（flex
    行内 grow 错位族——768 档曾 81/93；r247 实测 ≤540 带同族残留：
    390 档末行 3 格 108 vs 上行 80 差 28px，钉样本覆盖窄带）。"""
    for w in (768, 390):
      for pg in _at(srv, w):
        pg.evaluate("switchView('mon');showMonTab('trend');")
        pg.wait_for_timeout(800)
        res = pg.evaluate("""(()=>{
          const cells=[...document.querySelectorAll('.calgrid .calcell')]
            .filter(c=>c.offsetParent);
          if(cells.length<2)return {n:0};
          const top=cells[0].getBoundingClientRect().top;
          const rows={};
          for(const c of cells){
            const r=c.getBoundingClientRect();
            const k=Math.round(r.top);
            (rows[k]=rows[k]||[]).push(Math.round(r.width));
          }
          const ws=Object.values(rows).map(a=>[Math.min(...a),Math.max(...a)]);
          return {n:cells.length,rows:Object.keys(rows).length,ws,
                  lo:Math.min(...cells.map(c=>Math.round(c.getBoundingClientRect().width))),
                  hi:Math.max(...cells.map(c=>Math.round(c.getBoundingClientRect().width)))};
        })()""")
        assert res["n"] >= 2, res
        if res["rows"] > 1:
            # 断言维度=跨行全格极差（flex 行内 grow 恒行内等分——行内
            # min/max 钉面恒绿，跨行错位 80/108 抓不到，r247 钉面纠偏）
            assert res["hi"] - res["lo"] <= 1, res


def test_w6_preview_desp_paragraph_breaks(srv):
    """W6（r246 推送审校 P3-2）：预览 desp 全段落级换行（无孤立单
    \\n）——尾注曾以单 \\n 收尾（钉钉 PC 端单 \\n 粘行律的预览端
    残留；正文构建端已全段落级）。"""
    import json as _json
    import re as _re
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(
        BASE + "/api/preview", method="POST",
        data=_json.dumps({"user": 0}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    j = _json.loads(op.open(req, timeout=120).read().decode("utf-8"))
    assert j.get("ok"), {k: j.get(k) for k in ("ok", "err")}
    lone = _re.search(r"(?<!\n)\n(?!\n)", j["desp"])
    assert not lone, (lone.start(),
                      j["desp"][max(0, lone.start() - 40):lone.start() + 40])
