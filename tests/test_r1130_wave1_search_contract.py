# -*- coding: utf-8 -*-
"""r1130：2026-11-07 检索页整体重排契约（P0）。

本门禁只钉「物理量与交互意图」，不钉像素快照：
1) 首访搜索表单常驻，1440 表单 ≤56、hero ≤48；10 渠道 chip + 图标在独立行（≤40）；
2) 组合入口与实时探针同排同高（城市+日期+探针+组合一行）；开合两态
   触发器 dx/dy ≤1，面板紧贴下方，结果首行 y 不变；
3) 筛选为锚定浮层：触发器两态 dx/dy ≤1；桌面面板在触发器下方（top ≥ btn.bottom），
   宽 720–880、高 ≤70vh；打开/关闭结果列表 y 不变；航司搜索框独占一行且在 chips 上方，零相交；
4) 6 档零横向溢出；渠道 rail 仅在溢出时显示渐隐（is-over）。
"""
import os
import sys

import pytest

pytest.importorskip("playwright",
                    reason="检索页契约依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None
WIDTHS = [1440, 1024, 900, 768, 390, 320]


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
    priv = tempfile.mkdtemp(prefix="r1130_")
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


SNAP_BASE = """(() => {
  const R=e=>{if(!e)return null;const r=e.getBoundingClientRect();
    return {x:+r.x.toFixed(1),y:+r.y.toFixed(1),w:+r.width.toFixed(1),
      h:+r.height.toFixed(1),b:+r.bottom.toFixed(1)}};
  const v=document.getElementById('searchview');
  const probe=document.getElementById('srxProbe');
  const rail=document.getElementById('srxPlatPick');
  return {
    probeOpen:probe.classList.contains('open'),
    probeDisplay:getComputedStyle(probe).display,
    hero:R(document.querySelector('.srx-hero')),
    form:R(document.getElementById('srxProbeForm')),
    qrow:R(document.querySelector('#srxProbe .srx-qrow')),
    go:R(document.getElementById('srxGo')),
    rail:R(rail), railRow:R(document.getElementById('srxChannelRow')),
    chipRows:[...new Set([...rail.querySelectorAll('.srx-pchip')]
      .map(e=>Math.round(e.getBoundingClientRect().top)))].length,
    railClip:getComputedStyle(rail).overflow,
    chips:rail.querySelectorAll('.srx-pchip').length,
    chipVisible:[...rail.querySelectorAll('.srx-pchip')]
      .filter(e=>e.getBoundingClientRect().width>2).length,
    icons:rail.querySelectorAll('img.bic').length,
    railOver:rail.scrollWidth-rail.clientWidth,
    fader:rail.classList.contains('is-over'),
    batch:R(document.getElementById('srxBatchRow')),
    batchTrigger:R(document.getElementById('srxBatchToggle')),
    batchInForm:!!document.getElementById('srxBatchToggle')
      .closest('#srxProbeForm'),
    grid:R(document.getElementById('srxGrid')),
    docOver:document.documentElement.scrollWidth
      -document.documentElement.clientWidth,
    viewOver:v.scrollWidth-v.clientWidth,
    bodyH:document.body.scrollHeight,
  };
})()"""

SNAP_FILTER = """(() => {
  const R=e=>{if(!e)return null;const r=e.getBoundingClientRect();
    return {x:+r.x.toFixed(1),y:+r.y.toFixed(1),w:+r.width.toFixed(1),
      h:+r.height.toFixed(1),b:+r.bottom.toFixed(1)}};
  const fly=document.getElementById('srxCtxFly');
  const q=document.getElementById('srfAirQ');
  const chips=document.getElementById('srfAirChips');
  const grid=document.getElementById('srxGrid');
  const btn=document.getElementById('srxFilterBtn');
  const more=document.getElementById('srxMoreBtn');
  let overlap=null;
  if(q&&chips){const a=q.getBoundingClientRect(),b=chips.getBoundingClientRect();
    overlap=!(a.right<=b.left||b.right<=a.left||a.bottom<=b.top||b.bottom<=a.top)}
  return {fly:R(fly),pos:fly?getComputedStyle(fly).position:null,
    btn:R(btn),q:R(q),chips:R(chips),overlap,
    grid:R(grid),
    moreDisplay:more?getComputedStyle(more).display:null,
    /* r1148：可见表头是 `.srx-ctxfly-h`（`.srf-head` 是旧的隐藏模板）。
       门禁钉「表头里真的有命中/清除/关闭且表头可见」，不钉内部类名的代理。 */
    header:!!fly&&(()=>{const h=fly.querySelector('.srx-ctxfly-h');
      return !!h&&h.getBoundingClientRect().height>0&&!!h.querySelector('.srf-hit');})(),
    clear:!!fly&&(()=>{const h=fly.querySelector('.srx-ctxfly-h'),b=h&&h.querySelector('.srf-clearall');
      return !!b&&b.getBoundingClientRect().width>0;})(),
    close:!!fly&&(()=>{const h=fly.querySelector('.srx-ctxfly-h'),b=h&&h.querySelector('.srf-x');
      return !!b&&b.getBoundingClientRect().width>0;})(),
    docOver:document.documentElement.scrollWidth
      -document.documentElement.clientWidth,
    flyOver:fly?fly.scrollWidth-fly.clientWidth:null,
  };
})()"""


def _open_filter(pg):
    pg.evaluate("()=>{const b=document.querySelector('[data-mobile=filters]');"
                "if(b&&b.offsetParent)b.click();"
                "else document.getElementById('srxFilterBtn').click()}")


def test_search_first_screen_and_ci_rail(srv):
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
            pg.wait_for_timeout(700)
            pg.evaluate("()=>switchView('search')")
            pg.wait_for_timeout(700)
            d = pg.evaluate(SNAP_BASE)
            pg.close()
            if not d["probeOpen"] or d["probeDisplay"] == "none":
                bad.append("%d 首访搜索表单未常驻" % w)
            if w == 1440:
                if d["form"]["h"] > 56:
                    bad.append("1440 表单高 %s（≤56）" % d["form"]["h"])
                if d["hero"]["h"] > 48:
                    bad.append("1440 hero 高 %s（≤48）" % d["hero"]["h"])
            if d["chips"] != 10 or d["chipVisible"] != 10:
                bad.append("%d 渠道 chip %d/%d" % (w, d["chipVisible"], d["chips"]))
            if d["icons"] != 10:
                bad.append("%d 渠道官方图标 %d（应 10）" % (w, d["icons"]))
            # r1506：≤600 档渠道 rail 改成 5 列网格 + 裁剪（r1454/1501，替代
            # "按住往右拖"），于是：偏窄档渠道行必是 2 行 ≈124px，`scrollWidth`
            # 也会因裁剪内容而恒大于 clientWidth。判据改为**结构行数** + 只对
            # "真滚动"（overflow 非 hidden）才要求渐隐提示。
            if d["railRow"]["h"] > 40 * max(1, d.get("chipRows", 1)) + 60:
                bad.append("%d 渠道行高 %s（chip %d 行）"
                           % (w, d["railRow"]["h"], d.get("chipRows", 0)))
            scrolling = d.get("railClip") not in ("hidden", "clip")
            if ((d["railOver"] > 1) and scrolling) != bool(d["fader"]):
                bad.append("%d rail 渐隐与溢出不一致 over=%s fader=%s clip=%s"
                           % (w, d["railOver"], d["fader"], d.get("railClip")))
            if not d["batchInForm"]:
                bad.append("%d 组合入口不在表单主行" % w)
            if (d["batchTrigger"]["y"] < d["qrow"]["y"] - 1
                    or d["batchTrigger"]["b"] > d["qrow"]["b"] + 1):
                bad.append("%d 组合入口不在表单主行内" % w)
            if abs(d["batchTrigger"]["h"] - d["go"]["h"]) > 1:
                bad.append("%d 组合入口与探针按钮不同高 %s/%s"
                           % (w, d["batchTrigger"]["h"], d["go"]["h"]))
            if d["docOver"] > 1 or d["viewOver"] > 1:
                bad.append("%d 横向溢出 doc=%s view=%s"
                           % (w, d["docOver"], d["viewOver"]))
        b.close()
    assert not bad, "检索首屏: " + "；".join(bad)


def test_combo_and_filter_triggers_are_stable_overlays(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        bad = []
        for w in (1440, 390):
            pg = b.new_page(viewport={"width": w, "height": 900 if w > 500 else 844},
                            is_mobile=(w <= 600), has_touch=(w <= 600))
            pg.goto(BASE + "/", wait_until="load")
            pg.wait_for_function("typeof S!=='undefined'&&S&&S.users",
                                 timeout=25000)
            pg.wait_for_timeout(700)
            pg.evaluate("()=>switchView('search')")
            pg.wait_for_timeout(650)
            pg.evaluate("window.scrollTo(0,0)")
            pg.wait_for_timeout(150)
            # 组合：两态同坐标，面板在下方，结果首行不动
            c0 = pg.evaluate("()=>{const e=document.getElementById('srxBatchToggle');"
                             "const r=e.getBoundingClientRect();return {x:r.x,y:r.y,b:r.bottom,"
                             "exp:e.getAttribute('aria-expanded')}}")
            g0 = pg.evaluate("()=>document.getElementById('srxGrid').getBoundingClientRect().y")
            h0 = pg.evaluate("()=>document.body.scrollHeight")
            pg.evaluate("()=>document.getElementById('srxBatchToggle').click()")
            pg.wait_for_timeout(450)
            c1 = pg.evaluate("()=>{const e=document.getElementById('srxBatchToggle');"
                             "const r=e.getBoundingClientRect();return {x:r.x,y:r.y,b:r.bottom,"
                             "exp:e.getAttribute('aria-expanded')}}")
            g1 = pg.evaluate("()=>document.getElementById('srxGrid').getBoundingClientRect().y")
            h1 = pg.evaluate("()=>document.body.scrollHeight")
            dock = pg.evaluate("()=>{const e=document.getElementById('srxBatchDock');"
                               "if(!e)return null;const r=e.getBoundingClientRect();return {y:r.y,h:r.height,"
                               "disp:getComputedStyle(e).display}}")
            if abs(c1["x"] - c0["x"]) > 1 or abs(c1["y"] - c0["y"]) > 1:
                bad.append("%d 组合触发器位移 dx=%s dy=%s"
                           % (w, c1["x"] - c0["x"], c1["y"] - c0["y"]))
            if c1["exp"] != "true":
                bad.append("%d 组合 aria-expanded 未同拍" % w)
            if dock and dock["disp"] != "none" and dock["y"] < c1["b"] - 1:
                bad.append("%d 组合面板在触发器上方" % w)
            if abs(g1 - g0) > 1:
                bad.append("%d 组合展开推走首行 %spx" % (w, g1 - g0))
            if h1 != h0:
                bad.append("%d 组合展开改变页面高度 %s→%s" % (w, h0, h1))
            pg.evaluate("()=>document.getElementById('srxBatchToggle').click()")
            pg.wait_for_timeout(350)
            pg.evaluate("window.scrollTo(0,0)")
            pg.wait_for_timeout(150)
            # 筛选：两态同坐标，桌面浮层在下方，列表不动
            f0 = pg.evaluate("()=>{const e=document.getElementById('srxFilterBtn');"
                             "const r=e.getBoundingClientRect();return {x:r.x,y:r.y,b:r.bottom}}")
            gb = pg.evaluate("()=>document.getElementById('srxGrid').getBoundingClientRect().y")
            _open_filter(pg)
            pg.wait_for_timeout(900)
            fm = pg.evaluate(SNAP_FILTER)
            g2 = fm["grid"]["y"] if fm["grid"] else None
            fa = pg.evaluate("()=>{const e=document.getElementById('srxFilterBtn');"
                             "const r=e.getBoundingClientRect();return {x:r.x,y:r.y,b:r.bottom}}")
            if w > 900:
                if abs(fa["x"] - f0["x"]) > 1 or abs(fa["y"] - f0["y"]) > 1:
                    bad.append("%d 筛选触发器位移" % w)
                if not fm["fly"]:
                    bad.append("%d 筛选浮层不可见" % w)
                else:
                    if fm["pos"] != "fixed":
                        bad.append("%d 筛选浮层非 overlay" % w)
                    if fm["fly"]["y"] < f0["b"] - 1:
                        bad.append("%d 筛选浮层在触发器上方" % w)
                    if not (720 <= fm["fly"]["w"] <= 1280):
                        bad.append("%d 筛选浮层宽 %s" % (w, fm["fly"]["w"]))
                    if fm["fly"]["h"] > 900 * 0.78 + 1:
                        bad.append("%d 筛选浮层高 %s >70vh" % (w, fm["fly"]["h"]))
            if g2 is not None and abs(g2 - gb) > 1:
                bad.append("%d 筛选开合改变列表 y %spx" % (w, g2 - gb))
            if not fm["header"] or not fm["clear"] or not fm["close"]:
                bad.append("%d 筛选头缺 命中/清除全部/关闭" % w)
            if fm["moreDisplay"] != "none":
                bad.append("%d 二级「展开更多条件」仍可见" % w)
            if fm["overlap"]:
                bad.append("%d 航司搜索框与 chips 相交" % w)
            if fm["q"] and fm["chips"] and not (fm["q"]["b"] <= fm["chips"]["y"] + 1):
                bad.append("%d 航司搜索框未在 chips 上方" % w)
            if fm["flyOver"] and fm["flyOver"] > 1:
                bad.append("%d 筛选面板横向溢出 %s" % (w, fm["flyOver"]))
            if fm["docOver"] > 1:
                bad.append("%d 筛选打开横向溢出 %s" % (w, fm["docOver"]))
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(400)
            g3 = pg.evaluate("()=>document.querySelector('#srxGrid').getBoundingClientRect().y")
            if abs(g3 - gb) > 1:
                bad.append("%d 筛选关闭后列表未回位" % w)
            pg.close()
        b.close()
    assert not bad, "检索浮层: " + "；".join(bad)
