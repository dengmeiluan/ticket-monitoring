# -*- coding: utf-8 -*-
"""r1130：组合探针状态机（2026-11-07 契约）。

替代被新布局推翻的 r1046/r992/r1025 布局断言，保留其真实意图：
- 按钮文案自洽：0/4 → 1/4，重复加入显示「已加入」且禁用；
- 面板在触发器正下方，不推表单/结果；清单在动作条上方，每行右侧 ×；
- 关闭后 aria-expanded=false、面板消失、触发器坐标不变。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_static_combo_copy_and_state_source():
    with open(os.path.join(ROOT, "webui.py"), encoding="utf-8") as f:
        src = f.read()
    assert "srxBatchSyncAdd" in src
    assert "add.textContent=dup?'已加入':(full?'已满 4 条':'＋ 当前条件')" in src
    assert "go.textContent='运行组合'" in src
    assert "运行组合 ('+a.length+')" not in src
    assert "该航线/日期已在组合中。" not in src


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_combo_panel_state_and_anchor():
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
                pg = br.new_page(viewport={"width": 1512, "height": 950})
                pg.goto(base + "/", wait_until="domcontentloaded")
                pg.wait_for_timeout(1800)
                pg.evaluate("switchView('search')")
                pg.wait_for_timeout(600)
                pg.evaluate("srxBatchToggle()")
                pg.wait_for_timeout(500)
                d = pg.evaluate("""()=>{
                  const R=e=>{const r=e.getBoundingClientRect();return {x:+r.x.toFixed(1),y:+r.y.toFixed(1),
                    w:+r.width.toFixed(1),h:+r.height.toFixed(1),b:+r.bottom.toFixed(1)}};
                  const tg=document.getElementById('srxBatchToggle'),dock=document.getElementById('srxBatchDock');
                  const chip=document.querySelector('.srx-blchip'),go=document.getElementById('srxBatchGo');
                  const list=document.getElementById('srxBatchList'),bar=document.querySelector('#srxBatchDock .srx-batchbar');
                  return {tg:R(tg),dock:R(dock),dockDisp:getComputedStyle(dock).display,
                    tgTxt:tg.textContent.trim(),aria:tg.getAttribute('aria-expanded'),
                    chip:R(chip),go:R(go),goTxt:go.textContent.trim(),goDisp:getComputedStyle(go).display,
                    list:R(list),bar:R(bar),
                    orderOk:!!(chip&&go&&bar&&list&&chip.getBoundingClientRect().top<bar.getBoundingClientRect().top),
                    over:document.documentElement.scrollWidth-innerWidth};
                }""")
                assert d["tgTxt"].startswith("组合 1/4"), d
                assert d["aria"] == "true", d
                assert d["dockDisp"] != "none", d
                assert d["dock"]["y"] >= d["tg"]["b"] - 1, ("组合面板未在触发器下方", d)
                assert d["goTxt"] == "运行组合", d
                assert d["goDisp"] != "none", d
                assert d["orderOk"], ("清单应在动作条上方", d)
                assert d["over"] <= 1, d
                # 重复加入同一腿 → 已加入 + 禁用
                pg.evaluate("()=>document.querySelector('#srxBatchWrap .srx-batchadd').click()")
                pg.wait_for_timeout(350)
                a = pg.evaluate("""()=>{const a=document.querySelector('#srxBatchWrap .srx-batchadd');
                  return {t:a.textContent.trim(),d:a.disabled}}""")
                assert a["t"] == "已加入" and a["d"] is True, a
                # 改日期 → 回到可加入
                pg.evaluate("""()=>{const d=document.getElementById('srxDate');const x=new Date();
                  x.setDate(x.getDate()+3);d.value=x.toISOString().slice(0,10);
                  d.dispatchEvent(new Event('change',{bubbles:true}))}""")
                pg.wait_for_timeout(300)
                b = pg.evaluate("""()=>{const a=document.querySelector('#srxBatchWrap .srx-batchadd');
                  return {t:a.textContent.trim(),d:a.disabled}}""")
                assert b["t"] == "＋ 当前条件" and b["d"] is False, b
                # 关闭：坐标不变、aria 同拍、面板消失
                before = pg.evaluate("""()=>{const r=document.getElementById('srxBatchToggle').getBoundingClientRect();
                  return {x:r.x,y:r.y}}""")
                pg.evaluate("srxBatchToggle()")
                pg.wait_for_timeout(400)
                after = pg.evaluate("""()=>{const tg=document.getElementById('srxBatchToggle');
                  const r=tg.getBoundingClientRect();const d=document.getElementById('srxBatchDock');
                  return {x:r.x,y:r.y,aria:tg.getAttribute('aria-expanded'),disp:getComputedStyle(d).display}}""")
                assert abs(after["x"] - before["x"]) <= 1 and abs(after["y"] - before["y"]) <= 1, (before, after)
                assert after["aria"] == "false" and after["disp"] == "none", after
                pg.close()
            finally:
                br.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=8)
        except Exception:
            srv.kill()
