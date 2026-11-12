# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_slider_solver_e2e.py
- tests/test_r1063_slider_stats.py
- tests/test_r1063_slider_vision.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import io
import json
import os
import pytest
import sys

from core import channel_matrix as CM
from core.android import slider_vision as SV
from crawlers import slider as S


# ---- merged from tests/test_r1063_slider_solver_e2e.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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




# ---- merged from tests/test_r1063_slider_stats.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mk(tmp_path, plat="fliggy", fails=1, k_ok=2, k_fail=1, blocked=0):
    import time
    d = tmp_path / "fliggy"
    d.mkdir(parents=True, exist_ok=True)
    rec = {
        plat: {
            "tries": k_ok + k_fail, "day_used": 3, "fails": fails,
            "blocked_until": (time.time() + blocked) if blocked else 0,
            "last_ok": 1700000000,
            "by_kind": {"slider": {"tries": k_ok + k_fail, "ok": k_ok,
                                   "fail": k_fail}},
        }
    }
    (d / "slider_ledger.json").write_text(json.dumps(rec), encoding="utf-8")


def test_slider_stats_reads_ledger(tmp_path):
    _mk(tmp_path)
    rep = CM.slider_stats(str(tmp_path))
    assert rep["ok"] and len(rep["rows"]) == 1
    r = rep["rows"][0]
    assert r["plat"] == "fliggy" and r["profile"] == "fliggy"
    assert r["tries"] == 3 and r["today"] == 3 and r["fails"] == 1
    assert "滑块 2/3" in r["kinds"], r["kinds"]


def test_slider_text_shows_cooldown(tmp_path):
    _mk(tmp_path, blocked=600)
    rep = CM.slider_stats(str(tmp_path))
    txt = CM._slider_text(rep)
    assert "分钟" in txt, txt
    assert "滑块" in txt


def test_slider_text_empty_is_explanatory():
    txt = CM._slider_text({"ok": True, "rows": [], "root": "user_data"})
    assert "没有验证尝试记录" in txt
    assert "强人机验证" in txt, "要说明强验证不硬刚，避免误以为没实现"


def test_kind_cn_covers_all_kinds_used_by_slider():
    src = io.open(os.path.join(ROOT, "crawlers", "slider.py"),
                  encoding="utf-8").read()
    for kind in ("slider", "arithmetic", "text"):
        assert kind in CM.SLIDER_KIND_CN, kind
        assert kind in src, "slider.py 里用的类别必须在中文表里有名字：%s" % kind


def test_cli_has_slider_flag():
    src = io.open(os.path.join(ROOT, "core", "channel_matrix.py"),
                  encoding="utf-8").read()
    assert "--slider" in src and "def slider_stats(" in src


# ---- merged from tests/test_r1063_slider_vision.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 真机 OCR 输出（乱序单字按 y 归行后）
REAL_WORDS = [
    {"t": "亲", "x": 339, "y": 1460, "w": 40, "h": 40},
    {"t": "请", "x": 400, "y": 1460, "w": 40, "h": 40},
    {"t": "拖", "x": 460, "y": 1462, "w": 40, "h": 40},
    {"t": "动", "x": 520, "y": 1460, "w": 40, "h": 40},
    {"t": "下", "x": 580, "y": 1461, "w": 40, "h": 40},
    {"t": "方", "x": 640, "y": 1460, "w": 40, "h": 40},
    {"t": "滑", "x": 700, "y": 1460, "w": 40, "h": 40},
    {"t": "通过验证以", "x": 429, "y": 1540, "w": 400, "h": 30},
    {"t": "向右动验滑证", "x": 493, "y": 1690, "w": 266, "h": 34},
    {"t": "点我反馈>", "x": 551, "y": 2280, "w": 160, "h": 30},
]


def test_lines_group_single_chars():
    lines = SV._lines(REAL_WORDS)
    assert len(lines) >= 4
    joined = " ".join(ln["text"] for ln in lines)
    assert "拖动" in joined or "滑" in joined


def test_finds_track_on_the_lowest_matching_line():
    """标题/副标题/轨道文案都命中，必须取最下面那行（轨道在标题下方）。"""
    track = SV.find_track(REAL_WORDS, 1260, 2800)
    assert track is not None
    assert 1600 < track["y"] < 1800, track          # 轨道那一行
    assert track["distance"] > 600, track           # 用经验轨道带，不是文字宽度


def test_ignores_footer_and_non_slider_screens():
    only_footer = [{"t": "点我反馈>", "x": 551, "y": 2280, "w": 160, "h": 30}]
    assert SV.find_track(only_footer, 1260, 2800) is None
    plain = [{"t": "航班列表", "x": 100, "y": 600, "w": 200, "h": 40}]
    assert SV.find_track(plain, 1260, 2800) is None


def test_solve_never_raises_without_screen():
    class _NoScreen:
        def screencap(self):
            return b""

    rep = SV.solve_by_ocr(_NoScreen(), tries=1)
    assert rep["ok"] is False and rep["why"]


def test_wired_into_clear_blockers():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "crawlers", "app_base.py"),
               encoding="utf-8").read()
    assert "slider_vision.visible" in src
    assert 'path_note(\n                    "app-captcha"' in src or \
        '"app-captcha"' in src
