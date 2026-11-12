# -*- coding: utf-8 -*-
"""r1144：健康时间线 6 段契约（段高 36 / 格填满 / 点击归属 / 空段不可点）。

r1140 把 24 个小格收成 6 个 4 小时段按钮后，旧门禁仍按 `.hc` 小格找
onclick；本门禁直接量新契约，并用三段负控证明判据能测出旧缺陷：
- 段内格被 `max-width:22px` 压成左侧一小撮 → 右空腔 ≥10px；
- 段点击只带 data-p、格不带 → 日志渠道读成 undefined；
- 全段未扫描仍渲染成 button → 假手型。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

pytest.importorskip("playwright", reason="渲染门禁依赖 playwright")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None

MEASURE = """()=>{
  const rows=[...document.querySelectorAll('#hbody .hrow')];
  return rows.map(r=>{
    const x=r.querySelector('.hcells');
    if(!x)return {segs:0,cells:0,h:0,tail:null,over:0,fit:false};
    const segs=[...x.querySelectorAll('.hseg')];
    const cells=[...x.querySelectorAll('.hc')];
    const sr=segs.length?segs[segs.length-1].getBoundingClientRect():null;
    const lr=cells.length?cells[cells.length-1].getBoundingClientRect():null;
    return {segs:segs.length,cells:cells.length,
      h:segs.length?+segs[0].getBoundingClientRect().height.toFixed(1):0,
      tail:sr&&lr?+(sr.right-lr.right).toFixed(1):null,
      over:x.scrollWidth-x.clientWidth,fit:x.classList.contains('fit')};
  });
}"""


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def srv():
    global BASE
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失")
    port = free_port()
    BASE = "http://127.0.0.1:%d" % port
    proc = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(port)],
                            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(100):
        try:
            op.open(BASE + "/api/state", timeout=2)
            break
        except Exception:
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.fail("demo 未启动")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


@pytest.fixture(scope="module")
def pw():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def open_health(b, width, height):
    pg = b.new_page(viewport={"width": width, "height": height},
                    is_mobile=(width <= 600), has_touch=(width <= 600))
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(1500)
    pg.evaluate("switchView('mon');showMonTab('health')")
    pg.wait_for_function(
        "()=>document.querySelectorAll('#hbody .hcells .hseg').length>=6", timeout=20000)
    pg.wait_for_timeout(400)
    return pg


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_health_segments_fill_and_height(srv, pw, width, height):
    pg = open_health(pw, width, height)
    try:
        rows = pg.evaluate(MEASURE)
        assert len(rows) >= 10, "健康演示应有 ≥10 渠道行: %r" % len(rows)
        for row in rows:
            assert row["segs"] == 6, row
            assert row["cells"] == 24, row
            assert 35 <= row["h"] <= 37, "段高应 36px: %r" % row
            assert row["tail"] is not None and row["tail"] <= 1.5, \
                "段内格未填满（右空 %.1fpx）: %r" % (row["tail"], row)
            assert row["over"] <= 2, "格带横向溢出: %r" % row
        # 负控：恢复旧 max-width:22px，判据必须量出右空腔
        # （390 段宽 57px，4×22 仍会被 flex 收缩塞满，负控无区分度）
        if width >= 1024:
            pg.add_style_tag(content="#hbody .hseg .hc{max-width:22px!important}")
            pg.wait_for_timeout(150)
            bad = pg.evaluate(MEASURE)
            worst = max((r["tail"] or 0) for r in bad)
            assert worst >= 10, "负控未生效，填满判据可能恒真: %r" % worst
    finally:
        pg.close()


def test_health_segment_click_keeps_channel(srv, pw):
    pg = open_health(pw, 1440, 1000)
    try:
        res = pg.evaluate("""()=>{
          const row=document.querySelector('#hbody .hrow');
          const seg=[...row.querySelectorAll('button.hseg')]
            .find(s=>s.querySelector('.hc[data-ts]'));
          if(!seg)return {err:'no scanned segment'};
          const cs=[...seg.querySelectorAll('.hc[data-ts]')];
          const c=cs[cs.length-1];
          const saved=[...seg.querySelectorAll('.hc[data-ts]')].map(x=>x.dataset.p);
          window.__logArg=null;window.__showLog0=window.showLog;
          window.showLog=el=>{window.__logArg={p:el&&el.dataset?el.dataset.p:null,
            ts:el&&el.dataset?el.dataset.ts:null};};
          seg.click();
          const got=window.__logArg;
          // 负控：去掉格的 data-p（旧实现）再点，必须量到 undefined
          seg.querySelectorAll('.hc[data-ts]').forEach(x=>x.removeAttribute('data-p'));
          window.__logArg=null;seg.click();
          const bad=window.__logArg;
          seg.querySelectorAll('.hc[data-ts]').forEach((x,i)=>{
            if(saved[i]!=null)x.dataset.p=saved[i];});
          window.showLog=window.__showLog0;
          return {wantP:seg.dataset.p,wantTs:c.dataset.ts,got:got,bad:bad};
        }""")
        assert not res.get("err"), res
        assert res["wantP"], res
        assert res["got"] and res["got"]["p"] == res["wantP"], res
        assert res["got"]["ts"] == res["wantTs"], res
        assert res["bad"] is not None and res["bad"]["p"] is None, \
            "负控未生效，渠道归属判据可能恒真: %r" % res
    finally:
        pg.close()


def test_health_segment_keyboard_roving(srv, pw):
    """键盘：每行只有一个 tab 停靠段（首个有日志的段），←/→ 在段间移动；
    全未扫描的段不得带 data-rv/tabindex（零停靠点不造幽灵焦点）。"""
    pg = open_health(pw, 1440, 1000)
    try:
        res = pg.evaluate("""()=>{
          const row=document.querySelector('#hbody .hrow');
          const segs=[...row.querySelectorAll('button.hseg')];
          if(segs.length<2)return {err:'live segs<2'};
          const zero=segs.filter(s=>s.tabIndex===0).length;
          const neg=segs.filter(s=>s.tabIndex===-1).length;
          segs[0].focus();
          const before=document.activeElement===segs[0];
          segs[0].dispatchEvent(new KeyboardEvent('keydown',
            {key:'ArrowRight',bubbles:true}));
          const after=document.activeElement===segs[1];
          const now=new Date(),z=n=>String(n).padStart(2,'0');
          const ts=now.getFullYear()+'-'+z(now.getMonth()+1)+'-'+z(now.getDate())
            +' '+z(now.getHours())+':00';
          const html=_hcCells([{ts:ts,plats:{ctrip:{s:'ok',tot:1,ok:1}}}],
            'ctrip',{ok:'成功'});
          const host=document.createElement('div');
          host.style.cssText='position:absolute;left:-9999px;top:0';
          host.innerHTML=html;document.body.appendChild(host);
          const live=[...host.querySelectorAll('button.hseg')];
          const offs=[...host.querySelectorAll('span.hseg.off')];
          const liveTabs=live.map(s=>s.getAttribute('tabindex'));
          const offRv=offs.filter(s=>s.hasAttribute('data-rv')).length;
          const offTab=offs.filter(s=>s.hasAttribute('tabindex')).length;
          host.remove();
          return {zero,neg,before,after,live:live.length,offs:offs.length,
                  liveTabs,offRv,offTab};
        }""")
        assert not res.get("err"), res
        assert res["zero"] == 1 and res["neg"] >= 1, \
            "每行应只有一个 tabindex=0 的停靠段: %r" % res
        assert res["before"] and res["after"], \
            "←/→ 未在段间移动焦点: %r" % res
        assert res["live"] >= 1 and res["offs"] >= 1, res
        assert res["liveTabs"][0] == "0" and all(
            t == "-1" for t in res["liveTabs"][1:]), res
        assert res["offRv"] == 0 and res["offTab"] == 0, \
            "未扫描段不应有 roving 停靠点: %r" % res
    finally:
        pg.close()


def test_health_unscanned_segment_not_clickable(srv, pw):
    pg = open_health(pw, 1440, 1000)
    try:
        res = pg.evaluate("""()=>{
          const now=new Date(),z=n=>String(n).padStart(2,'0');
          const ts=now.getFullYear()+'-'+z(now.getMonth()+1)+'-'+z(now.getDate())
            +' '+z(now.getHours())+':00';
          const html=_hcCells([{ts:ts,plats:{ctrip:{s:'ok',tot:1,ok:1}}}],
            'ctrip',{ok:'成功'});
          const body=document.getElementById('hbody');
          const host=document.createElement('div');
          host.style.cssText='position:absolute;left:-9999px;top:0';
          host.innerHTML=html;body.appendChild(host);
          const btns=host.querySelectorAll('button.hseg');
          const offs=[...host.querySelectorAll('span.hseg.off')];
          window.__logArg=null;window.__showLog0=window.showLog;
          window.showLog=el=>{window.__logArg={p:el&&el.dataset?el.dataset.p:null};};
          if(offs[0])offs[0].click();
          const called=window.__logArg;
          window.showLog=window.__showLog0;
          const v={btn:btns.length,off:offs.length,
            cursor:offs[0]?getComputedStyle(offs[0]).cursor:null,
            onclick:!!(offs[0]||{}).onclick,called:called};
          host.remove();return v;
        }""")
        assert res["off"] >= 1 and res["btn"] >= 1, res
        assert res["cursor"] == "default", res
        assert res["onclick"] is False, res
        assert res["called"] is None, "空段点击不应打开日志: %r" % res
    finally:
        pg.close()
