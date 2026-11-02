# -*- coding: utf-8 -*-
"""r868 门禁：镜像栏没有任何行时，右半屏不能是一条空带。

用户截图圈的就是它：解析列表照旧半宽，右半栏只剩「本态未供」的空镜面，
整块空白（多张截图里都是同一条竖带）。这与「收起镜像」应得同一个结果——
右列塌掉，列表拿回整行。

判据走渲染几何：
  · 空作用域下 srxMirror 必须不可见，且列表实际宽度 ≈ 网格宽；
  · 有行时右列必须复原（镜像可见、两列各半）——空态收敛不能吃掉正常形态；
  · 两态来回切两次都必须稳定（不能只在第一次渲染时对）。
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
  const g = document.getElementById('srxGrid');
  const m = document.getElementById('srxMirror');
  const l = document.querySelector('#searchview .srx-list');
  const r = e => { const b = e.getBoundingClientRect();
                   return {w:+b.width.toFixed(1), l:+b.left.toFixed(1), r:+b.right.toFixed(1)}; };
  return {
    grid: r(g),
    cols: getComputedStyle(g).gridTemplateColumns,
    list: r(l),
    listRatio: +(r(l).w / r(g).w).toFixed(3),
    mirrorVisible: !!m.offsetParent && r(m).w > 1,
    mirrorW: r(m).w,
    emptyClass: m.classList.contains('srx-mempty'),
    gap: +(r(l).r < r(m).l ? m.getBoundingClientRect().left - l.getBoundingClientRect().right : -1).toFixed(1),
  };
}"""


@pytest.fixture(scope="module")
def states():
    srv = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(PORT)],
                           cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = {}
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        ok = False
        for _ in range(90):
            try:
                op.open(BASE + "/api/state", timeout=2)
                ok = True
                break
            except Exception:
                time.sleep(0.5)
        if not ok:
            pytest.skip("demo 服务未起来")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            pg = br.new_page(viewport={"width": 1590, "height": 900})
            pg.goto(BASE + "/", wait_until="domcontentloaded")
            pg.wait_for_timeout(2600)
            pg.evaluate("switchView('search')")
            pg.wait_for_timeout(1600)
            out["with_rows"] = pg.evaluate(JS)
            # 空作用域（用户那种「本态未供」）：两轮来回，验证可重复
            cycle = []
            for _ in range(2):
                pg.evaluate("""()=>{window.__mb=srxMirrorScope;
                    window.srxMirrorScope=()=>[];srxRenderMirror();}""")
                pg.wait_for_timeout(250)
                cycle.append(pg.evaluate(JS))
                pg.evaluate("window.srxMirrorScope=window.__mb;srxRenderMirror();")
                pg.wait_for_timeout(250)
                cycle.append(pg.evaluate(JS))
            out["cycle"] = cycle
            br.close()
        yield out
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()


def test_empty_mirror_yields_width_to_list(states):
    empties = [s for i, s in enumerate(states["cycle"]) if i % 2 == 0]
    bad = [s for s in empties if s["mirrorVisible"] or s["listRatio"] < 0.95]
    assert not bad, (
        "空镜像仍占着右半栏，列表没拿回整行：%s"
        % [(s["mirrorW"], s["listRatio"], s["cols"]) for s in bad])


def test_rows_restore_two_columns(states):
    full = [states["with_rows"]] + [s for i, s in enumerate(states["cycle"]) if i % 2 == 1]
    bad = [s for s in full if (not s["mirrorVisible"]) or not (0.45 <= s["listRatio"] <= 0.55)]
    assert not bad, (
        "有行时镜像列没有复原成两列各半：%s"
        % [(s["mirrorW"], s["listRatio"], s["cols"]) for s in bad])
