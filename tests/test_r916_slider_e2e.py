# -*- coding: utf-8 -*-
"""r916：滑块引擎的**端到端**验证（真实浏览器 + 真实拼图页，不是 mock）。

为什么单独做这一层：单测里的 page 是假对象，只能证明"逻辑分支对"，证明不了
「选择器能不能选中真实 DOM、缺口能不能在真实截图上找出来、拖完页面会不会真
认账」。这三件事任何一件不成立，自动解就是白跑。

做法：本地生成一个和主流实现同构的滑块页（canvas 画噪点背景 + 带白边的缺口，
可拖动方块，落在容差内才算通过），用项目自己的指纹参数开 Playwright，
走完整 ``slider.attempt_page`` 流程。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r916_slider_e2e.py -q
"""
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest  # noqa: E402

from crawlers import slider  # noqa: E402

_LOG = logging.getLogger("test_r916")

# 缺口中心在容器内的 x（容器 320 宽，缺口 46 宽，左边距 200）
GAP_X = 200
GAP_W = 46
GAP_CENTER = GAP_X + GAP_W // 2          # 223

_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<style>
 body{margin:0;background:#fff;font:14px/1.4 sans-serif}
 .wrap{padding:40px}
 .slide-verify{position:relative;width:320px;height:160px;
   border:1px solid #ddd;box-sizing:border-box}
 canvas{display:block;width:320px;height:160px}
 .sliderContainer{position:relative;width:320px;height:44px;margin-top:8px;
   background:#f4f4f4;border:1px solid #ddd;box-sizing:border-box}
 .slideBlock{position:absolute;left:0;top:0;width:46px;height:44px;
   background:#4a90d9;cursor:pointer;color:#fff;text-align:center;
   line-height:44px;user-select:none}
 .tip{position:absolute;left:60px;top:12px;color:#999}
</style></head><body>
<div class="wrap">
  <div class="slide-verify" id="box">
    <canvas id="cv" width="320" height="160"></canvas>
  </div>
  <div class="sliderContainer" id="track">
    <div class="slideBlock" id="btn">→</div>
    <div class="tip">拖动滑块完成拼图</div>
  </div>
  <div id="out"></div>
</div>
<script>
const GAP_X=%d, GAP_W=%d;
function draw(){
  const cv=document.getElementById('cv'), c=cv.getContext('2d');
  // 噪点背景
  for(let x=0;x<320;x+=2){for(let y=0;y<160;y+=2){
    const v=140+Math.floor(Math.random()*30);
    c.fillStyle=`rgb(${v},${v+6},${v+12})`; c.fillRect(x,y,2,2);}}
  // 缺口：深色块 + 白边（两条强竖直边 → 边缘检测的物理对象）
  c.fillStyle='#3a3a4a'; c.fillRect(GAP_X,34,GAP_W,90);
  c.strokeStyle='#ffffff'; c.lineWidth=2;
  c.strokeRect(GAP_X,34,GAP_W,90);
}
draw();
let dragging=false, startX=0;
const btn=document.getElementById('btn');
btn.addEventListener('mousedown',e=>{dragging=true;startX=e.clientX;e.preventDefault();});
window.addEventListener('mousemove',e=>{
  if(!dragging)return;
  const d=e.clientX-startX;
  btn.style.left=Math.max(0,Math.min(320-46,d))+'px';
});
window.addEventListener('mouseup',e=>{
  if(!dragging)return; dragging=false;
  const d=parseInt(btn.style.left||'0',10);
  const target=GAP_X-(46-GAP_W)/2;   // 让方块右缘对上缺口右缘
  if(Math.abs(d-target)<=8){
    document.getElementById('box').remove();
    document.getElementById('track').remove();
    document.getElementById('out').textContent='验证通过';
  }else{
    document.getElementById('out').textContent='验证失败';
    btn.style.left='0px';
  }
});
</script></body></html>
"""


def _has_browser() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            b.close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _has_browser(), reason="playwright 浏览器不可用")
def test_attempt_page_solves_real_puzzle(tmp_path):
    """真实页面：选择器命中 → 截图找缺口 → 拟人拖动 → 页面认账。"""
    from playwright.sync_api import sync_playwright

    html = _PAGE % (GAP_X, GAP_W)
    page_path = tmp_path / "slider.html"
    page_path.write_text(html, encoding="utf-8")

    cfg = {"slider": {"auto": True}}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(viewport={"width": 1366, "height": 900})
        page = ctx.new_page()
        page.goto(page_path.as_uri())
        page.wait_for_timeout(300)

        # 前置：分级必须是 simple，否则引擎会拒绝动手
        tier = slider.classify(page.content(), page.inner_text("body"))
        assert tier.solvable is True, tier.as_dict()

        ok = slider.attempt_page(page, "e2e", cfg, tier=tier,
                                 logger=_LOG,
                                 user_data_dir=str(tmp_path),
                                 profile="e2e")
        body = page.inner_text("body")
        ctx.close()
        b.close()

    assert ok is True, "真实滑块页未被解开，body=%r" % body[:120]
    assert "验证通过" in body


@pytest.mark.skipif(not _has_browser(), reason="playwright 浏览器不可用")
def test_find_gap_on_real_render(tmp_path):
    """真实渲染出的画布：缺口检测必须落在容差内（合成图之外的第二种证据）。"""
    from playwright.sync_api import sync_playwright

    page_path = tmp_path / "gap.html"
    page_path.write_text(_PAGE % (GAP_X, GAP_W), encoding="utf-8")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(viewport={"width": 1366, "height": 900})
        page = ctx.new_page()
        page.goto(page_path.as_uri())
        page.wait_for_timeout(300)
        box = page.query_selector(".slide-verify").bounding_box()
        shot = page.screenshot(full_page=False)
        ctx.close()
        b.close()

    off, cands = slider.find_gap(shot, (int(box["x"]), int(box["y"]),
                                        int(box["x"] + box["width"]),
                                        int(box["y"] + box["height"])))
    assert cands, "真实画布上没找到任何候选"
    assert abs(off - GAP_CENTER) <= 14, (off, GAP_CENTER, cands[:3])
