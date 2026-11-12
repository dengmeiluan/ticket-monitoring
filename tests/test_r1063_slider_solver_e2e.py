# -*- coding: utf-8 -*-
"""r1063 T193：滑块自动解的**端到端**回归（合成页面，不碰真实渠道）。

为什么要有这条：用户反复问"简单滑块到底能不能自动过"。代码里有
`classify → find_gap → trajectory → apply_trajectory → _slider_gone` 一整条链，
但没有任何测试把它**跑通一遍**——于是"能不能过"只能靠嘴上说。

本用例在本地渲染一个**标准拼图滑块**（背景带缺口 + 可拖手柄 + 命中即消失），
然后调用项目自己的 `crawlers.slider.attempt_page()`，断言它能把滑块解开。

不碰真实渠道：失败两次会被拉黑 7 天，这种实验不该拿生产渠道做。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from crawlers import slider as S  # noqa: E402

HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>合成滑块</title><style>
body{margin:0;font:14px sans-serif}
.slide-verify{position:absolute;left:60px;top:120px;width:360px;height:200px;
 background:#e9e9e9;border:1px solid #ccc}
#bg{position:absolute;left:0;top:0}
.verify-move-block{position:absolute;left:0;top:150px;width:50px;height:44px;
 background:#4a90e2;border-radius:6px}
.hint{position:absolute;left:60px;top:60px;font-size:16px}
</style></head><body>
<div class="hint">请拖动滑块完成拼图</div>
<div class="slide-verify" id="track">
  <canvas id="bg" width="360" height="200"></canvas>
  <div class="verify-move-block" id="h"></div>
</div>
<script>
 var GAP_X=200,GAP_Y=40,GAP_W=50,GAP_H=44;
 var c=document.getElementById('bg'),g=c.getContext('2d');
 for(var x=0;x<360;x+=18){g.strokeStyle='#d0d0d0';g.beginPath();g.moveTo(x,0);
  g.lineTo(x,200);g.stroke();}
 for(var y=0;y<200;y+=18){g.strokeStyle='#dcdcdc';g.beginPath();g.moveTo(0,y);
  g.lineTo(360,y);g.stroke();}
 g.fillStyle='#333';g.fillRect(GAP_X,GAP_Y,GAP_W,GAP_H);
 var h=document.getElementById('h'),dragging=false,startX=0,baseLeft=0;
 h.addEventListener('pointerdown',function(e){dragging=true;startX=e.clientX;
  baseLeft=parseFloat(h.style.left||0);});
 window.addEventListener('pointermove',function(e){if(!dragging)return;
  var left=baseLeft+(e.clientX-startX);left=Math.max(0,Math.min(310,left));
  h.style.left=left+'px';});
 window.addEventListener('pointerup',function(){if(!dragging)return;dragging=false;
  var left=parseFloat(h.style.left||0);
  if(Math.abs(left-GAP_X)<=10){h.parentNode.removeChild(h);
   document.querySelector('.hint').textContent='';document.body.dataset.ok='1';}
  else{h.style.left='0px';}});
</script></body></html>
"""


def test_classify_says_simple():
    t = S.classify(HTML, "请拖动滑块完成拼图")
    assert t.solvable, t
    assert t.name in ("simple", "basic", "easy"), t


def test_attempt_page_solves_synthetic_slider(tmp_path):
    """端到端：分级 → 找缺口 → 拟人轨迹 → 拖拽 → 复核，一步不落。"""
    playwright = pytest.importorskip("playwright.sync_api")
    p = tmp_path / "slider.html"
    p.write_text(HTML, encoding="utf-8")
    url = "file:///" + str(p).replace("\\", "/")
    with playwright.sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        pg = b.new_page(viewport={"width": 800, "height": 600})
        try:
            pg.goto(url, wait_until="domcontentloaded")
            pg.wait_for_timeout(400)
            ok = S.attempt_page(pg, "demo", {"slider": {}})
            assert ok is True, "合成滑块没解开——自动识别链路退化"
            assert pg.evaluate("()=>document.body.dataset.ok||''") == "1", \
                "页面没记为通过（说明拖拽落点偏了）"
        finally:
            b.close()
