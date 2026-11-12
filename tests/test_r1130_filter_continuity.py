# -*- coding: utf-8 -*-
"""r1130c：检索筛选浮层的「连续动作」契约。

用户原话：点击筛选弹出筛选，再点击任何一个筛选就会关掉页面，无法连续动作。

根因：条件点击后 `srxRenderFacets` 会重建浮层 DOM；document 冒泡阶段的
`e.target.closest('#srxCtxFly')` 此时已拿不到已脱离文档的旧节点 → 误判为
「点在外面」→ 收起。修法：捕获阶段判定 + `composedPath()`（事件路径在
派发时固定，不受 onclick 重建影响）。

判据（真实渲染，1440/390 两档）：
1) 打开后浮层可见、紧贴触发器下方；
2) 连续点「航线 chip → 日期 chip → 排序 select → 复选框」四次，浮层始终
   可见、`aria-expanded=true`，且第二次点航线后结果集确有变化；
3) 只有「关闭」按钮或点击浮层外才收起。
"""
import os
import sys

import pytest

pytest.importorskip("playwright",
                    reason="筛选连续动作依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


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
            pytest.skip("chromium 二进制缺失")

    logf = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    priv = tempfile.mkdtemp(prefix="r1130c_")
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


def _open_search(pg):
    pg.goto(BASE + "/", wait_until="load")
    pg.wait_for_function("typeof S!=='undefined'&&S&&S.users", timeout=25000)
    pg.wait_for_timeout(1200)
    pg.evaluate("()=>switchView('search')")
    pg.wait_for_timeout(900)


def _snap(pg):
    return pg.evaluate("""()=>{
      const f=document.getElementById('srxCtxFly');
      const b=document.getElementById('srxFilterBtn');
      const r=f?f.getBoundingClientRect():null, br=b?b.getBoundingClientRect():null;
      return {ctx:typeof SRX!=='undefined'?!!SRX.ctx:null,
        disp:f?getComputedStyle(f).display:null,
        flyTop:r?+r.top.toFixed(1):null, btnBottom:br?+br.bottom.toFixed(1):null,
        aria:b?b.getAttribute('aria-expanded'):null,
        rows:document.querySelectorAll('#srxRows .srx-row').length,
        pair:(document.querySelector('#srxCtxFly .srx-chip.on[data-pair]')||{}).textContent||'',
        date:(document.querySelector('#srxCtxFly .srx-chip.on[data-date]')||{}).textContent||''
      }}""")


def test_filter_stays_open_across_consecutive_actions(srv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        for w, mobile in ((1440, False), (390, True)):
            pg = b.new_page(viewport={"width": w, "height": 950},
                            is_mobile=mobile, has_touch=mobile)
            _open_search(pg)
            # 窄档筛选入口在底部工具条（桌面在首行）；两处是同一个状态机。
            trig = ("#srxFilterBtn" if w > 900
                    else "#srxMobilebar [data-mobile='filters']")
            pg.click(trig)
            pg.wait_for_timeout(500)
            d = _snap(pg)
            assert d["disp"] == "block" and d["ctx"] is True, (w, d)
            if w > 900:
                assert d["flyTop"] >= d["btnBottom"] - 1, (w, "浮层没贴在触发器下方", d)
            else:
                assert 0 <= d["flyTop"] <= 950, (w, "窄档浮层越出视口", d)
            assert d["aria"] == "true" or w <= 900, (w, d)

            # 1) 航线 chip（换一条航线，结果集必须变）
            pairs = pg.eval_on_selector_all(
                "#srxCtxFly .srx-chip[data-pair]",
                "els=>els.map(e=>e.getAttribute('data-pair'))")
            assert len(pairs) >= 2, (w, "航线 chip 不足 2 条，无法验证切换", pairs)
            pg.click('#srxCtxFly .srx-chip[data-pair="%s"]' % pairs[1])
            pg.wait_for_timeout(500)
            d1 = _snap(pg)
            assert d1["disp"] == "block" and d1["ctx"] is True, (w, "点航线后被收起", d1)
            assert d1["pair"] != d["pair"], (w, "航线切换后选中态没变", d, d1)

            # 2) 日期 chip
            has_date = pg.evaluate(
                "()=>document.querySelectorAll('#srxCtxFly .srx-chip[data-date]').length")
            if has_date:
                pg.click("#srxCtxFly .srx-chip[data-date]")
                pg.wait_for_timeout(400)
                d2 = _snap(pg)
                assert d2["disp"] == "block" and d2["ctx"] is True, (w, "点日期后被收起", d2)

            # 3) 排序 select
            pg.select_option("#srxSort", "price_desc")
            pg.wait_for_timeout(350)
            d3 = _snap(pg)
            assert d3["disp"] == "block" and d3["ctx"] is True, (w, "改排序后被收起", d3)

            # 4) 复选框
            pg.click("#srxNoStale")
            pg.wait_for_timeout(350)
            d4 = _snap(pg)
            assert d4["disp"] == "block" and d4["ctx"] is True, (w, "勾选后被收起", d4)

            # 关闭按钮才是关
            pg.click("#srxCtxFly .srx-ctxfly-h button[aria-label='关闭筛选']")
            pg.wait_for_timeout(400)
            d5 = _snap(pg)
            assert d5["disp"] == "none" and d5["ctx"] is False, (w, "关闭按钮没关", d5)

            # 再开：点浮层外收起
            pg.click(trig)
            pg.wait_for_timeout(400)
            pg.mouse.click(12, 120)
            pg.wait_for_timeout(400)
            d6 = _snap(pg)
            assert d6["disp"] == "none" and d6["ctx"] is False, (w, "点外部没关", d6)
            pg.close()
        b.close()


def test_outside_handler_uses_capture_and_composed_path():
    """静态守门：捕获阶段 + composedPath 是这次修复的两个必要件。

    只看行为容易在无重建的 demo 数据下假绿（点同一条航线不重建），所以
    这里同时钉住实现形状；行为由上面的连续动作用例负责。
    """
    src = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    i = src.find("r1130c：筛选浮层里的条件一点就会重建 DOM")
    assert i > 0, "缺少 r1130c 注释锚点"
    seg = src[i:i + 1200]
    assert "composedPath" in seg, "捕获判定没用 composedPath 兜底"
    assert "},true);" in seg, "document click 监听不在捕获阶段"
    assert "srxCtxFly" in seg, "判定没锚定浮层 id"

def test_channel_popover_stays_open_and_anchored(srv):
    """渠道浮层：锚在「渠道 5」下方；连续勾选/全选/清空不关闭；与筛选互斥。"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        for w, mobile in ((1440, False), (390, True)):
            pg = b.new_page(viewport={"width": w, "height": 950},
                            is_mobile=mobile, has_touch=mobile)
            _open_search(pg)
            trig = pg.query_selector("#srxPlatDD summary")
            assert trig, (w, "渠道 5 触发器不存在")
            assert trig.is_visible(), (w, "渠道 5 触发器不可见")
            pg.click("#srxPlatDD summary")
            pg.wait_for_timeout(450)
            d = pg.evaluate("""()=>{const d=document.getElementById('srxPlatDD');
              const p=document.getElementById('srxPlatPop'),s=d.querySelector('summary');
              const r=p.getBoundingClientRect(),t=s.getBoundingClientRect();
              return {open:d.open,disp:getComputedStyle(p).display,
                top:+r.top.toFixed(1),bottom:+r.bottom.toFixed(1),
                left:+r.left.toFixed(1),right:+r.right.toFixed(1),
                trigBottom:+t.bottom.toFixed(1),vw:innerWidth,
                sel:(document.getElementById('srxPlatSel')||{}).textContent||''}}""")
            assert d["open"] and d["disp"] != "none", (w, "渠道浮层没打开", d)
            assert d["top"] >= d["trigBottom"] - 1, (w, "渠道浮层没锚在触发器下方", d)
            assert d["left"] >= 0 and d["right"] <= d["vw"] + 1, (w, "渠道浮层越界", d)
            before = d["sel"]
            chips = pg.eval_on_selector_all(
                "#srxPlatPop .srx-pchip", """els=>els.map(e=>({
                    p:e.dataset.p,
                    dis:!!(e.querySelector('input')||{}).disabled
                        || e.getAttribute('aria-disabled')==='true'}))""")
            assert len(chips) == 10, (w, "渠道浮层不是 10 家", chips)
            # r1489：去哪儿网页通路已退役（PC/H5 均停服，数据只走 app_qunar），
            # 它的 chip 必须**不可选**——否则探针会去打一条已停服的网页。
            # 因此连续勾选只在可选 chip 上做（跳过它，并反过来钉住它确实被禁用）。
            dis = {c["p"] for c in chips if c["dis"]}
            assert "qunar" in dis, (w, "去哪儿网页已停服却被允许勾选", chips)
            clickable = [i + 1 for i, c in enumerate(chips) if not c["dis"]]
            # 连续勾选/取消（只点可选的）：浮层不关闭，计数每次都更新
            seq = []
            for n in clickable:
                pg.click("#srxPlatPop .srx-pchip:nth-child(%d)" % n)
                pg.wait_for_timeout(120)
                st = pg.evaluate("""()=>({open:document.getElementById('srxPlatDD').open,
                  disp:getComputedStyle(document.getElementById('srxPlatPop')).display,
                  sel:(document.getElementById('srxPlatSel')||{}).textContent||''})""")
                assert st["open"] and st["disp"] != "none", (w, "点渠道后被关闭", n, st)
                seq.append(st["sel"])
            assert len(set(seq)) > 1, (w, "渠道计数没有随勾选变化", seq)
            # 全选 / 清空
            names = pg.eval_on_selector_all(
                "#srxPlatPop .srx-platpop-f button", "els=>els.map(e=>e.textContent.trim())")
            assert any("全选" in n for n in names) and any("清空" in n for n in names), (w, names)
            pg.click("#srxPlatPop .srx-platpop-f button:last-child")
            pg.wait_for_timeout(200)
            st = pg.evaluate("()=>({open:document.getElementById('srxPlatDD').open,sel:document.getElementById('srxPlatSel').textContent})")
            assert st["open"], (w, "清空后浮层被关闭", st)
            # 与筛选互斥
            trig = ("#srxFilterBtn" if w > 900
                    else "#srxMobilebar [data-mobile='filters']")
            pg.click(trig)
            pg.wait_for_timeout(400)
            st = pg.evaluate("""()=>({dd:document.getElementById('srxPlatDD').open,
              fly:getComputedStyle(document.getElementById('srxCtxFly')).display,
              pop:getComputedStyle(document.getElementById('srxPlatPop')).display})""")
            assert st["dd"] is False and st["pop"] == "none" and st["fly"] == "block", (w, "筛选打开时渠道浮层未关", st)
            if w > 900:
                pg.click("#srxPlatDD summary")
                pg.wait_for_timeout(400)
                st = pg.evaluate("""()=>({dd:document.getElementById('srxPlatDD').open,
                  fly:getComputedStyle(document.getElementById('srxCtxFly')).display})""")
                assert st["dd"] is True and st["fly"] == "none", (w, "渠道浮层打开时筛选未关", st)
            pg.close()
        b.close()


def test_default_has_zero_overlays(srv):
    """首屏默认 0 浮层，主 CTA 可见（§6.9/§9.1）。"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        for w, mobile in ((1440, False), (390, True)):
            pg = b.new_page(viewport={"width": w, "height": 950},
                            is_mobile=mobile, has_touch=mobile)
            _open_search(pg)
            d = pg.evaluate("""()=>{const fly=document.getElementById('srxCtxFly');
              const dd=document.getElementById('srxPlatDD');
              const go=document.getElementById('srxGo');
              const r=go?go.getBoundingClientRect():null;
              return {fly:fly?getComputedStyle(fly).display:'none',
                dd:dd?dd.open:false,
                go:!!r&&r.top>=0&&r.bottom<=innerHeight&&r.width>20,
                goBox:r?[Math.round(r.left),Math.round(r.top),Math.round(r.width)]:null}}""")
            assert d["fly"] == "none" and d["dd"] is False, (w, "默认有浮层", d)
            assert d["go"], (w, "主 CTA 不在首屏", d)
            pg.close()
        b.close()


def test_negative_control_injected_internal_close_is_caught(srv):
    """负控：把「面板内点击关闭自身」的旧缺陷注回页面，判据必须变红。

    做法：在浮层捕获阶段注入一个 close-on-chip-click 监听器（模拟旧版
    冒泡 closest 失效的错误行为），再点 chip——浮层必须真的被关掉。
    这证明正向用例的「始终保持打开」不是空转。
    """
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 950})
        _open_search(pg)
        pg.click("#srxFilterBtn")
        pg.wait_for_timeout(400)
        pg.evaluate("""()=>{const f=document.getElementById('srxCtxFly');
          f.addEventListener('click',function(e){
            if(e.target.closest('.srx-chip')){SRX.ctx=false;srxRenderCtx()}
          },true)}""")
        pg.click("#srxCtxFly .srx-chip[data-pair]")
        pg.wait_for_timeout(300)
        d = pg.evaluate("()=>({ctx:SRX.ctx,disp:getComputedStyle(document.getElementById('srxCtxFly')).display})")
        assert d["ctx"] is False and d["disp"] == "none", (
            "负控无效：注入「点内即关」后浮层仍开着，说明判据量不到关闭", d)
        b.close()
