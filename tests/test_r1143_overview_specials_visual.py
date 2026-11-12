# -*- coding: utf-8 -*-
"""r1143：概览两列基线 + 特价图上部空白（真实渲染 + 像素 bbox + 负控）。

master v2.4c 附录两条点名缺陷的收口门禁：
- 概览：同一日期行的直飞/中转两列必须共用一条网格行，价格/进度条同基线；
- 特价雷达：画布内容不得在顶部留大片空白（顶空 ≤12%，纵向覆盖 ≥55%）。
两条判据都用注入式负控证明「能测出旧缺陷」，避免恒真。
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

BBOX_JS = r"""(cv)=>{
  const w=cv.width,h=cv.height;
  const d=cv.getContext('2d').getImageData(0,0,w,h).data;
  const c=[[0,0],[w-1,0],[0,h-1],[w-1,h-1]].map(([x,y])=>{
    const i=(y*w+x)*4;return [d[i],d[i+1],d[i+2],d[i+3]];});
  const bg=c[0];
  let minY=h,maxY=-1,n=0;
  for(let y=0;y<h;y++){for(let x=0;x<w;x++){
    const i=(y*w+x)*4;
    if(Math.abs(d[i]-bg[0])+Math.abs(d[i+1]-bg[1])+Math.abs(d[i+2]-bg[2])+Math.abs(d[i+3]-bg[3])>=24){
      n++; if(y<minY)minY=y; if(y>maxY)maxY=y;
    }
  }}
  if(maxY<0)return {w,h,content:0,bg};
  return {w,h,content:n,bg,minY,maxY,topRatio:minY/h,cover:(maxY-minY+1)/h};
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


def open_mon(b, width, height, tab):
    pg = b.new_page(viewport={"width": width, "height": height},
                    is_mobile=(width <= 600), has_touch=(width <= 600))
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(1800)
    pg.evaluate("switchView('mon');showMonTab('%s')" % tab)
    pg.wait_for_timeout(1200)
    return pg


def test_overview_two_columns_share_grid_baseline(srv, pw):
    for width in (1440, 1024, 901):
        pg = open_mon(pw, width, 1000, "overview")
        try:
            data = pg.evaluate("""()=>{
              const out=[];
              for(const g of document.querySelectorAll('#montab-overview .dgroup')){
                const grid=g.querySelector('.grid');
                if(!grid) continue;
                const cols=getComputedStyle(grid).gridTemplateColumns.split(' ').filter(Boolean).length;
                const ks=[...grid.querySelectorAll(':scope > .kpi')];
                if(cols!==2||ks.length!==2) continue;
                const pick=(el,s)=>{const n=el.querySelector(s);if(!n)return null;
                  const r=n.getBoundingClientRect();return {y:+r.y.toFixed(1),h:+r.height.toFixed(1)}};
                const gr=grid.getBoundingClientRect();
                out.push({date:(g.querySelector('.dlab')||{}).textContent||'',
                  num:ks.map(k=>pick(k,'.num')),bar:ks.map(k=>pick(k,'.bar')),
                  w:ks.map(k=>+k.getBoundingClientRect().width.toFixed(1)),
                  gridW:+gr.width.toFixed(1)});
              }
              return out;
            }""")
            assert len(data) >= 3, "%d：概览演示应有多个日期行，实测 %r" % (width, len(data))
            bar_rows = 0
            for row in data:
                assert row["num"][0] and row["num"][1], row
                assert abs(row["num"][0]["y"] - row["num"][1]["y"]) <= 1, \
                    "%d：两列金额不同基线 %r" % (width, row)
                if row["bar"][0] and row["bar"][1]:
                    bar_rows += 1
                    assert abs(row["bar"][0]["y"] - row["bar"][1]["y"]) <= 1, \
                        "%d：两列进度条不同基线 %r" % (width, row)
                assert abs(row["w"][0] - row["w"][1]) <= 1, "%d：两列不等宽 %r" % (width, row)
            assert bar_rows >= 3, "%d：有进度条的日期行不足 %r" % (width, bar_rows)
            if width == 1440:
                # 负控：把右列金额下移 9px，判据必须能测出
                pg.add_style_tag(content="#montab-overview .dgroup .grid>.kpi:nth-child(2) .num{transform:translateY(9px)}")
                pg.wait_for_timeout(120)
                bad = pg.evaluate("""()=>{
                  const g=document.querySelector('#montab-overview .dgroup .grid');
                  if(!g)return null;
                  const ks=[...g.querySelectorAll(':scope > .kpi')];
                  const y=k=>k.querySelector('.num').getBoundingClientRect().y;
                  return +Math.abs(y(ks[0])-y(ks[1])).toFixed(1);
                }""")
                assert bad is not None and bad >= 8, "负控未生效，判据可能恒真: %r" % bad
        finally:
            pg.close()


def _wait_chart(pg, timeout=12):
    t0 = time.time()
    while time.time() - t0 < timeout:
        box = pg.evaluate(BBOX_JS, pg.query_selector("#spMonChart"))
        if box and box.get("content", 0) > 500:
            return box
        pg.wait_for_timeout(400)
    return None


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_specials_chart_no_top_blank(srv, pw, width, height):
    pg = open_mon(pw, width, height, "specials")
    try:
        box = _wait_chart(pg)
        assert box and box["content"] > 500, "特价图未绘制内容: %r" % (box,)
        assert box["topRatio"] <= 0.12, "画布顶部空白过大: %r" % box
        assert box["cover"] >= 0.55, "画布纵向内容覆盖不足: %r" % box
        geom = pg.evaluate("""()=>{
          const r=s=>{const e=document.querySelector(s);if(!e)return null;
            const b=e.getBoundingClientRect();
            return {y:+b.y.toFixed(1),h:+b.height.toFixed(1),w:+b.width.toFixed(1)}};
          const wrap=document.querySelector('.spmon-chartwrap');
          return {wrap:r('.spmon-chartwrap'),chart:r('#spMonChart'),legend:r('#spMonLegend'),
            low:r('#spMonLow'),cal:r('#spMonCal'),
            over:wrap?wrap.scrollWidth-wrap.clientWidth:null};
        }""")
        assert geom["chart"] and geom["chart"]["w"] > 0, geom
        assert geom["over"] is not None and geom["over"] <= 1, "图表容器横向溢出: %r" % geom
        assert geom["chart"]["y"] >= geom["wrap"]["y"], geom
        assert geom["legend"] and geom["legend"]["y"] >= geom["wrap"]["y"] + geom["wrap"]["h"] - 30, geom
        # 负控：清空画布上半部（透明背景），顶空判据必须变红
        blanked = pg.evaluate("""()=>{
          const cv=document.getElementById('spMonChart');
          const ctx=cv.getContext('2d');
          const bg=ctx.getImageData(0,0,1,1).data;
          ctx.clearRect(0,0,cv.width,Math.floor(cv.height*0.55));
          const w=cv.width,h=cv.height;
          const px=ctx.getImageData(0,0,w,h).data;
          let minY=h;
          for(let y=0;y<h;y++){for(let x=0;x<w;x++){
            const i=(y*w+x)*4;
            if(Math.abs(px[i]-bg[0])+Math.abs(px[i+1]-bg[1])+Math.abs(px[i+2]-bg[2])+Math.abs(px[i+3]-bg[3])>=24){
              if(y<minY)minY=y;break;
            }
          }}
          return minY/h;
        }""")
        assert blanked > 0.12, "负控未生效，顶部空白判据可能恒真: %r" % blanked
    finally:
        pg.close()
