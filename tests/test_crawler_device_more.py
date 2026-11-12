# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r947_device_distance_from_image.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import io
import os
import sys

from PIL import Image, ImageDraw
from crawlers import slider


# ---- merged from tests/test_r947_device_distance_from_image.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _scene(piece_x=57, piece_w=44, gap_x=266, gap_w=76, size=(822, 411)):
    """造"左拼图块 + 右缺口"的图（与携程真实截图形状一致）。"""
    im = Image.new("RGB", size, (240, 240, 240))
    d = ImageDraw.Draw(im)
    d.rectangle([piece_x, 120, piece_x + piece_w, 260], fill=(60, 60, 60))
    d.rectangle([piece_x, 120, piece_x + piece_w, 260],
                outline=(0, 0, 0), width=3)
    d.rectangle([gap_x, 130, gap_x + gap_w, 250], fill=(200, 200, 205))
    d.rectangle([gap_x, 130, gap_x + gap_w, 250],
                outline=(30, 30, 30), width=3)
    for y in range(0, size[1], 40):
        d.line([(0, y), (size[0], y)], fill=(225, 225, 228), width=1)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


class _Dev:
    def __init__(self, png):
        self.png = png

    def screencap(self):
        return self.png


# ---------------------------------------------------------------------------
# 1. 距离必须来自图像，不是配置常量
# ---------------------------------------------------------------------------
def test_distance_derived_from_image():
    png = _scene()
    cands = slider._device_gap_candidates(_Dev(png), {"piece_offset": 118})
    assert cands, "没算出任何候选距离"
    # 缺口中心 ≈ 266+76/2 = 304 → 距离 ≈ 304-118 = 186
    assert any(abs(d - 186) <= 25 for d, _x in cands), cands


def test_distance_changes_with_gap_position():
    """缺口右移 → 距离必须跟着变大（证明真的在读图）。"""
    a = slider._device_gap_candidates(
        _Dev(_scene(gap_x=200)), {"piece_offset": 118})
    b = slider._device_gap_candidates(
        _Dev(_scene(gap_x=420)), {"piece_offset": 118})
    assert a and b
    assert b[0][0] > a[0][0] + 100, (a, b)


def test_no_screenshot_falls_back_to_empty():
    """截不到图 → 返回空（调用方退回配置值），不许抛。"""
    class Bad:
        def screencap(self):
            raise RuntimeError("no device")
    assert slider._device_gap_candidates(Bad(), {}) == []


def test_blank_image_returns_empty():
    im = Image.new("RGB", (822, 411), (240, 240, 240))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    assert slider._device_gap_candidates(_Dev(buf.getvalue()), {}) == []


# ---------------------------------------------------------------------------
# 2. attempt_device 必须用候选距离，且能多试
# ---------------------------------------------------------------------------
def test_source_uses_candidates_not_fixed_distance():
    src = io.open(os.path.join(ROOT, "crawlers", "slider.py"),
                  encoding="utf-8").read()
    i = src.find("def attempt_device(")
    j = src.find("\ndef ", i + 10)
    body = src[i:j]
    assert "_device_gap_candidates" in body, "没按图算距离"
    # 不许再直接拿 device_distance 当唯一距离
    assert 'dist = int(sec.get("device_distance")' not in body, \
        "还在把配置值当唯一距离（盲拖）"
    # 要有候选循环 + 每次核对
    assert "for _i, dist in enumerate" in body, "没有多候选重试"


def test_single_shot_respected():
    src = io.open(os.path.join(ROOT, "crawlers", "slider.py"),
                  encoding="utf-8").read()
    assert 'single_shot' in src
    assert 'tries = ([best] if _pval("slider_attempt.single_shot"' in src, \
        "single_shot 没生效（会多拖几次，浪费预算）"


def test_logs_actual_distance():
    """日志要打出实际用的距离，便于事后判断"是不是算错了"。"""
    src = io.open(os.path.join(ROOT, "crawlers", "slider.py"),
                  encoding="utf-8").read()
    assert "距离 %dpx" in src
