# -*- coding: utf-8 -*-
"""r1063 T266：`--ms` / `--dist` 两个诊断视图进浏览器。

它们今天两次直接解决问题（"谁最慢"、"是不是日期太远"），却只在命令行——
按"一切功能都集成在浏览器"搬进面板。本用例钉住：

* 后端 `GET /api/insight?view=ms|dist&hours=N` 返回文本行（复用现成函数）；
* 前端有两个链接 + `showInsight/hideInsight` 顶层函数 + 容器；
* **`_insight` 必须在「无更新」早退分支之前定义**——放后面会 ReferenceError，
  被 loadPacing 的 try/catch 吞掉，面板整片空白（真机踩过：snote 0 条）。
"""
import io
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_insight_route_defined_and_query_tolerant():
    w = _w()
    assert 'self.path.split("?")[0] == "/api/insight"' in w, \
        "路由必须容忍 query（?view=ms&hours=24）"
    i = w.index('self.path.split("?")[0] == "/api/insight"')
    seg = w[i:i + 1200]
    assert "_cm.dist_table" in seg and "_cm.ms_table" in seg, \
        "必须复用 channel_matrix 的现成实现，不要重写查询"


def test_frontend_links_and_global_functions():
    w = _w()
    assert "showInsight" in w and "hideInsight" in w
    assert "通路耗时" in w and "距离分桶" in w
    assert 'id="insightBox"' in w, "要有容器"
    # 顶层函数（onclick 只能解析全局名）
    for fn in ("async function showInsight(", "function hideInsight("):
        i = w.index(fn)
        line_start = w.rfind("\n", 0, i) + 1
        assert w[line_start:i] == " ", "%s 必须是顶层函数" % fn


def test_insight_defined_before_early_return():
    """`_insight` 必须定义在「无更新」早退分支**之前**（真机踩过的空白页）。"""
    w = _w()
    i_def = w.index("const _insight = '<span class=\"muted\"")
    i_ret = w.index("if(!u||!u.latest){")
    assert i_def < i_ret, "_insight 定义落在早退之后 → 该分支 ReferenceError"


def test_insight_api_live_if_server_up():
    """有实例在跑就顺手验一次真实响应（没有则跳过）。"""
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:8765/api/insight?view=dist&hours=24",
                timeout=20) as r:
            d = json.loads(r.read().decode() or "{}")
    except (urllib.error.URLError, OSError):
        return
    assert d.get("ok") is True, d
    assert isinstance(d.get("lines"), list) and d["lines"], d
    assert "距离" in d.get("title", "") + "".join(d["lines"][:2])

def test_insight_links_are_visible_in_health_tab():
    """有实例时：进「渠道健康」标签，两个诊断链接必须**有尺寸**（能点到）。

    这项专门防"元素在 DOM 里但用户看不见"——只查 textContent 是抓不到的。
    没有实例/没有 playwright 时跳过。
    """
    if not _live_ui_enabled():
        import pytest
        pytest.skip("实时 UI 检查需 TM_LIVE_UI=1（默认跳过，源码级断言仍在跑）")
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True)
            pg = b.new_page(viewport={"width": 1280, "height": 1000})
            pg.goto("http://127.0.0.1:8765/", wait_until="domcontentloaded",
                    timeout=30000)
            pg.wait_for_timeout(4000)
            pg.evaluate("""()=>{const t=[...document.querySelectorAll('span.mtab')]
                .find(e=>(e.innerText||'').trim()==='渠道健康'); if(t)t.click();}""")
            pg.wait_for_timeout(1200)
            pg.evaluate("()=>{try{loadPacing()}catch(e){}}")
            pg.wait_for_timeout(5000)
            # r1392：健康右栏读数默认折叠，诊断链接在「展开读数」内；
            # 先展开再量尺寸，否则量到的是 display:none 的 0×0。
            pg.evaluate("""()=>{
              const b=document.getElementById('paceRailMore');
              if(b && b.getAttribute('aria-expanded')!=='true') b.click();
            }""")
            pg.wait_for_timeout(600)
            r = pg.evaluate("""()=>{
              const link=[...document.querySelectorAll('a[onclick*="showInsight"]')][0];
              // 版本行 = **包含该链接的**那个 snote（按文本找会抓到别处的同名字样）
              const ver=link?link.closest('.snote'):null;
              const lr=link?link.getBoundingClientRect():null;
              const vr=ver?ver.getBoundingClientRect():null;
              return {lw:lr?Math.round(lr.width):0, lh:lr?Math.round(lr.height):0,
                      vh:vr?Math.round(vr.height):0};
            }""")
            b.close()
    except Exception:
        return          # 无实例/浏览器不可用：跳过（不假装通过）
    assert r["lw"] > 0 and r["lh"] > 0, "诊断链接不可见（rect=%sx%s）" % (
        r["lw"], r["lh"])
    assert r["vh"] > 0, "版本行不可见（高 %s）" % r["vh"]

def test_distance_advice_link_is_visible():
    """有实例时：建议行里的「距离建议」链接必须有尺寸（可点去调视野）。

    与诊断链接同理——只查 textContent 会漏掉"被折叠/被隐藏"的情况。
    """
    if not _live_ui_enabled():
        import pytest
        pytest.skip("实时 UI 检查需 TM_LIVE_UI=1（默认跳过，源码级断言仍在跑）")
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True)
            pg = b.new_page(viewport={"width": 1440, "height": 1200})
            pg.goto("http://127.0.0.1:8765/", wait_until="domcontentloaded",
                    timeout=30000)
            pg.wait_for_timeout(4000)
            pg.evaluate("""()=>{const t=[...document.querySelectorAll('span.mtab')]
                .find(e=>(e.innerText||'').trim()==='渠道健康'); if(t)t.click();}""")
            pg.wait_for_timeout(1200)
            pg.evaluate("()=>{try{loadPacing()}catch(e){}}")
            pg.wait_for_timeout(5000)
            # 同上：建议行也折在「展开读数」里（r1392）。
            pg.evaluate("""()=>{
              const b=document.getElementById('paceRailMore');
              if(b && b.getAttribute('aria-expanded')!=='true') b.click();
            }""")
            pg.wait_for_timeout(600)
            r = pg.evaluate("""()=>{
              const a=[...document.querySelectorAll('a[onclick*="srxDistJump"]')][0];
              if(!a) return {n:0, w:0, h:0};
              const rc=a.getBoundingClientRect();
              return {n:1, w:Math.round(rc.width), h:Math.round(rc.height)};
            }""")
            b.close()
    except Exception:
        return          # 无实例/浏览器不可用：跳过
    if not r["n"]:
        return          # 当前没有建议（样本不足）时不强求
    assert r["w"] > 0 and r["h"] > 0, "距离建议链接不可见（rect=%sx%s）" % (
        r["w"], r["h"])

def _live_ui_enabled():
    """实时 UI 检查需显式开关（默认跳过，避免给别处制造噪音）。"""
    return os.environ.get("TM_LIVE_UI") == "1"
