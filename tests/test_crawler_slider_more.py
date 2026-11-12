# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r916_slider_e2e.py
- tests/test_r974_slider_ddddocr_crosscheck.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import io as _io
import logging
import os
import pytest
import sys

from crawlers import slider


# ---- merged from tests/test_r916_slider_e2e.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

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








# ---- merged from tests/test_r974_slider_ddddocr_crosscheck.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _png(w=822, h=200, gray=128) -> bytes:
    from PIL import Image
    im = Image.new("L", (w, h), gray)
    buf = _io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 1. 纯函数：合并规则
# ---------------------------------------------------------------------------
def test_none_degrades_to_old_behaviour():
    """ddddocr 不可用 → 原样返回（**不得**改变任何既有结果）。"""
    for best, cands in ((300, [(300, 1.3), (120, 1.1)]), (0, []), (57, [(57, 1.4)])):
        assert slider._merge_gap(best, cands, None) == (best, cands)


def test_too_small_value_is_rejected():
    """小于 min_offset 的 x 是"拼图块自己"，不可信 → 原样返回。"""
    assert slider._merge_gap(300, [(300, 1.3)], 5, min_offset=12) == (300, [(300, 1.3)])


def test_rescues_when_edge_method_found_nothing():
    """边缘法空 + ddddocr 有值 → 用它。旧行为在这里直接放弃。"""
    best, cands = slider._merge_gap(0, [], 304)
    assert best == 304
    assert cands and cands[0][0] == 304


def test_agreement_keeps_edge_result_and_order():
    """两法接近 → 保持边缘法结果与顺序（互证即高置信）。"""
    cands = [(300, 1.3), (120, 1.1)]
    assert slider._merge_gap(300, cands, 308) == (300, cands)


def test_disagreement_appends_without_usurping():
    """两法分歧 → 追加为额外候选，但首选仍是边缘法的。"""
    cands = [(300, 1.3), (120, 1.1)]
    best, merged = slider._merge_gap(300, cands, 500)
    assert best == 300, "ddddocr 的分歧值不许篡位"
    offsets = [o for o, _s in merged]
    assert 500 in offsets, "分歧值应作为额外候选被尝试"
    assert offsets[0] == 300


def test_duplicate_disagreement_is_not_appended_twice():
    """已存在同一位置就不重复追加。"""
    cands = [(300, 1.3), (500, 1.2)]
    _best, merged = slider._merge_gap(300, cands, 502)
    assert [o for o, _s in merged].count(500) == 1


# ---------------------------------------------------------------------------
# 2. 整条链路：缺 ddddocr 时与旧实现完全一致
# ---------------------------------------------------------------------------
def test_find_gap_equals_edge_only_when_ddddocr_missing(monkeypatch):
    monkeypatch.setattr(slider, "_ddddocr_gap", lambda *a, **k: None)
    png = _png()
    assert slider.find_gap(png) == slider._find_gap_edges(png)


def test_find_gap_rescues_uniform_image(monkeypatch):
    """纯色图边缘法找不到任何缺口（旧行为 (0, [])）；ddddocr 给出值时用它。"""
    png = _png()
    base = slider._find_gap_edges(png)
    assert base == (0, []), "前提变了：纯色图不该有边缘候选"
    monkeypatch.setattr(slider, "_ddddocr_gap", lambda *a, **k: 304)
    best, cands = slider.find_gap(png)
    assert best == 304 and cands[0][0] == 304


def test_ddddocr_gap_returns_none_when_backend_missing(monkeypatch):
    """`slide_match` 不可用（返回 None）→ `_ddddocr_gap` 也是 None，不抛。"""
    from crawlers import captcha
    monkeypatch.setattr(captcha, "slide_match", lambda *a, **k: None)
    assert slider._ddddocr_gap(_png()) is None


def test_ddddocr_gap_survives_bad_image():
    """坏图不许抛：返回 None 就走边缘法。"""
    assert slider._ddddocr_gap(b"not-a-png") is None
    assert slider.find_gap(b"not-a-png") == (0, [])


# ---------------------------------------------------------------------------
# 3. 结构约束：不能再出现"注释承诺、无人调用"
# ---------------------------------------------------------------------------
def test_slide_match_now_has_a_caller():
    src = _io.open(os.path.join(ROOT, "crawlers", "slider.py"),
                   encoding="utf-8").read()
    assert "_ddddocr_gap" in src and "slide_match" in src, \
        "slider 里没有接 slide_match 的调用点"
    assert "def _find_gap_edges(" in src, "边缘法实现应保留为独立函数"
