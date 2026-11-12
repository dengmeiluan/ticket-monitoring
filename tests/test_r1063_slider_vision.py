# -*- coding: utf-8 -*-
"""r1063 T86：滑块**截图兜底**——UI 树没有节点时，用 OCR 在截图里定位轨道。

真机背景（飞猪 App 点「机票」，2026-11-08 12:4x）：阿里 NC 把滑块画在 canvas 里，
`uiautomator`/u2 的 UI 树里只有 `WVUCWebView`；文案还会随渲染阶段消失。
所以 T81 那套"按文案找轨道"经常什么也找不到——**看不见就没法试**。

截图兜底链路：截图 → Windows OCR 词块 → 按 y 归行 → 命中最下面那行当轨道文案
→ 用经验轨道带（12%..85% 屏宽）定位 → 走同一条人化轨迹。

两个坑（都是真机喂出来的）：
1. Windows OCR 把中文**拆成单字**且**乱序**（实测读出 `向右动验滑证`），
   所以按"命中字符数"判，而不是整串匹配；
2. 标题/副标题/轨道文案都会命中，必须取**最下面那一行**（轨道在标题下方）。

识别精度：OCR 定位到 y=1707、轨道带 151..1071，与 UI 树真值（y≈1709、189..1058）一致。

诚实结论：**识别已经可靠，但阿里仍拒绝机器轨迹**（2 次尝试都回验证页）。
这类挑战按用户口径属"很强大的人机识别"，不值得继续硬刚；
这条兜底的价值是"能看见、能如实记账、能在弱一点的挑战上真过"。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.android import slider_vision as SV  # noqa: E402

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
