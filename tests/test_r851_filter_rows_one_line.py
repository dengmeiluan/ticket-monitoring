# -*- coding: utf-8 -*-
"""r851 门禁：航班明细筛选条的每一行，内容必须从同一条左缘起排。

实测缺陷（修前 1512）：
  · 标签宽度随文字走：「智能筛选/日期/航线/渠道/航司」右缘 179.5，
    只有「出发时段：/到达时段：」是 175.5 → 内容从 187.5 挪到 181.5；
  · 「价格 ￥」「余票紧张」那两行连标签位都没有 → 内容顶到卡缘 115.5。
同一张筛选卡里三条左缘线，正是用户截图圈出的「筛选条件不对齐」。

定案：标签统一走既有单源 `--flt-lab`（64/56），槽宽吃掉一次行 gap；
没有标签的行用 `::before` 补同宽空位；时段行的 `.wingrp` 内层 gap 归零。
修后实测 1512/1280/900 三档，七行内容左缘全部 = 行左缘 + 64 + 8。

判据走渲染几何，不做源码字面匹配。
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
  const R = e => { const b = e.getBoundingClientRect();
    return {t:+b.top.toFixed(1), l:+b.left.toFixed(1), w:+b.width.toFixed(1)}; };
  const wrap = document.getElementById('fltwrap');
  if(!wrap) return {err:'no fltwrap'};
  const rows = [...wrap.children].filter(e => e.getBoundingClientRect().height > 1);
  const out = rows.map((r, i) => {
    const rl = +r.getBoundingClientRect().left.toFixed(1);
    // 该行的「内容起点」：跳过标签与标签容器（wingrp/agrp 是包装层），
    // 取真正与用户视线对齐的第一个内容元素。
    const LAB = '.chiplab';
    let first = null;
    const seek = (root) => {
      for (const k of root.children) {
        if (k.getBoundingClientRect().width < 1) continue;
        if (k.matches(LAB) || k.classList.contains('chiplab')) continue;
        // 包装层：递归进去找它自己的第一个非标签子项
        if (k.classList.contains('wingrp') || k.classList.contains('agrp')) {
          const inner = seek(k);
          if (inner) return inner;
          continue;
        }
        return R(k);
      }
      return null;
    };
    first = seek(r);
    return {i, id: r.id || (r.className || '').toString().slice(0, 24),
            rowL: rl, firstL: first ? first.l : null, firstW: first ? first.w : null};
  }).filter(x => x.firstL != null);
  // 同行起点必须一致（以出现最多的那个为基准）
  const counts = {};
  out.forEach(x => { counts[x.firstL] = (counts[x.firstL] || 0) + 1; });
  let base = null, best = -1;
  Object.keys(counts).forEach(k => { if (counts[k] > best) { best = counts[k]; base = +k; } });
  return {rows: out, base, labW: getComputedStyle(
      wrap.querySelector('.chiplab')).width};
}"""


@pytest.fixture(scope="module")
def probe():
    global PORT, BASE
    srv = None
    out = {}
    # free-port 有 TOCTOU 竞态：选完端口到 Popen 之间可能被另一 worker 抢走，
    # 我们的服务 bind 失败退出，`/api/state` 却可能由抢到端口的另一个 demo
    # 应答。8 worker 全量实测因此把 r851 记成 setup 连接拒绝（非产品失败）。
    # 三次新端口重试，且每次确认应答来自**本进程**。
    for _attempt in range(3):
        PORT = _free_port()
        BASE = "http://127.0.0.1:%d" % PORT
        srv = subprocess.Popen(
            [sys.executable, "webui.py", "--demo", "--port", str(PORT)],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        ok = False
        for _ in range(90):
            if srv.poll() is not None:
                break
            try:
                op.open(BASE + "/api/state", timeout=2)
            except Exception:
                time.sleep(0.5)
                continue
            if srv.poll() is None:
                ok = True
            break
        if ok:
            break
        try:
            srv.terminate()
            srv.wait(timeout=5)
        except Exception:
            try:
                srv.kill()
            except Exception:
                pass
        srv = None
    if srv is None:
        pytest.skip("demo 服务未起来（3 次新端口重试后）")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            for w in (1512, 1280, 900):
                pg = br.new_page(viewport={"width": w, "height": 1500})
                pg.goto(BASE + "/", wait_until="domcontentloaded")
                pg.wait_for_timeout(2600)
                pg.evaluate("switchView('mon')")
                pg.wait_for_timeout(700)
                pg.evaluate("showMonTab('details')")
                pg.wait_for_selector("#monview table tbody tr", timeout=20000)
                pg.evaluate("""()=>{const b=document.getElementById('fltBtn');
                    if(b && b.getAttribute('aria-expanded')!=='true') b.click();}""")
                pg.wait_for_timeout(900)
                out[w] = pg.evaluate(JS)
                pg.close()
            br.close()
        yield out
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()


@pytest.mark.parametrize("w", [1512, 1280, 900])
def test_every_filter_row_starts_on_one_line(probe, w):
    d = probe[w]
    assert "err" not in d, d
    rows = d["rows"]
    assert len(rows) >= 6, "%d 档只量到 %d 行" % (w, len(rows))
    bad = [r for r in rows if abs(r["firstL"] - d["base"]) > 1]
    assert not bad, (
        "%d 档有 %d 行内容不从同一左缘起排（基准 %.1f）：%s"
        % (w, len(bad), d["base"],
           [(r["id"], r["firstL"]) for r in bad]))
