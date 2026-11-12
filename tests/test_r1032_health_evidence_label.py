# -*- coding: utf-8 -*-
"""r1032：健康卡空证据行不再是一颗孤零零的「—」，改为有标题的「证据：—」。"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_static_empty_evidence_is_labelled():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        src = f.read()
    assert "'证据：—'" in src, "空证据行又退回裸「—」"
    # 有证据时仍以「证据：」开头，同行同前缀
    assert "('证据：'+he(c.evidence))" in src


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_rendered_evidence_rows_are_labelled_and_equal_height():
    import pytest
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        pytest.skip("playwright 缺失")
    port = _free_port()
    base = "http://127.0.0.1:%d" % port
    srv = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(port)],
                           cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ok = False
        for _ in range(90):
            try:
                urllib.request.urlopen(base + "/api/state", timeout=2)
                ok = True
                break
            except Exception:
                time.sleep(0.5)
        if not ok:
            pytest.skip("demo 服务未起来")
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            try:
                pg = br.new_page(viewport={"width": 1512, "height": 1000})
                pg.goto(base + "/", wait_until="domcontentloaded")
                pg.wait_for_timeout(1800)
                pg.evaluate("switchView('mon');showMonTab('health')")
                pg.wait_for_timeout(900)
                d = pg.evaluate("""()=>{
                  const cards=[...document.querySelectorAll('#healthDiag .hdiag-card')];
                  const ev=[...document.querySelectorAll('#healthDiag .hdiag-e')];
                  const hs=cards.map(c=>+c.getBoundingClientRect().height.toFixed(1));
                  return {n:cards.length, ev:ev.map(e=>e.textContent.trim()),
                    heights:hs, pageOF:document.documentElement.scrollWidth-innerWidth};
                }""")
                assert d["n"] == 10, d
                assert all(x.startswith("证据：") for x in d["ev"]), d
                assert max(d["heights"]) - min(d["heights"]) <= 1, (
                    "证据行占位导致卡高不一致", d["heights"])
                assert d["pageOF"] <= 1, d
                pg.close()
            finally:
                br.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=8)
        except Exception:
            srv.kill()
