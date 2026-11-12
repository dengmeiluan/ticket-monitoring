# -*- coding: utf-8 -*-
"""r1063 T21：点选题（图像定位题）纳入自动尝试 + 限制性文案清理。

用户要求（原话）：「滑块是简单滑块、简易拼图、简易图像识别、文字识别、
简易算数识别等简易通用的话验证，是否可以自动解码尝试…如果是非常强大的
人机识别就没必要了。要把之前项目中限制这些设计的文案、代码要通通改掉。」

因此本轮把**图像型**题目的最后一块补上——点选题（"按顺序点击图中的字/图标"）
本质是**目标检测题**，不是行为题：

  1. `detect_targets()`：ddddocr 检测模型给坐标，按语序（左→右、同列上→下）
     排序；没有检测后端返回 `[]`（**不瞎点**）；
  2. `Kind.solvable`：`click` 只在检测后端可用时算可解（降级而不是假装）；
  3. `attempt()`：点击分支**上移到输入框检查之前**——否则"找不到答案输入框"
     会把点选题直接挡掉（能力写了却不可达，这正是本项目最痛的一类缺陷）；
  4. 文案：把"交人工 / 按性价比不投入 / 越算越像机器"这类**立场式禁令**
     改成"能力边界"，行为型写明是**范围决定**（用户自己说没必要），
     并指出提高采集率的方向是真机/App 通路。
"""
import os

import pytest

from crawlers import captcha


# ---------------- 降级：没有检测后端时不假装可解 ----------------

def test_click_is_solvable_only_with_a_detector(monkeypatch):
    monkeypatch.setattr(captcha, "_det_backend", lambda: None)
    k = captcha.classify_kind("请按顺序点击图中的汉字", "请按顺序点击")
    assert k.name == "click"
    assert k.solvable is False, "没有检测后端却声称可解"
    assert "缺检测后端" in "、".join(k.reasons), k.reasons

    monkeypatch.setattr(captcha, "_det_backend", lambda: object())
    k2 = captcha.classify_kind("请按顺序点击图中的汉字", "请按顺序点击")
    assert k2.solvable is True, "有检测后端却不肯尝试（限制性设计没清干净）"
    assert "检测后端可用" in "、".join(k2.reasons), k2.reasons


def test_detect_targets_without_backend_returns_empty(monkeypatch):
    monkeypatch.setattr(captcha, "_det_backend", lambda: None)
    assert captcha.detect_targets(b"\x89PNG...") == [], \
        "没有后端时必须返回空（宁可不动，也不许瞎点）"


def test_detect_targets_sorts_by_reading_order(monkeypatch):
    class _Det:
        def detection(self, png):
            # 故意打乱：右、左、中
            return [[300, 10, 340, 50], [10, 10, 50, 50], [150, 10, 190, 50]]

    monkeypatch.setattr(captcha, "_det_backend", lambda: _Det())
    pts = captcha.detect_targets(b"x")
    assert [round(p[0]) for p in pts] == [30, 170, 320], pts


def test_detect_targets_respects_expected_count(monkeypatch):
    class _Det:
        def detection(self, png):
            return [[10, 10, 50, 50], [150, 10, 190, 50], [300, 10, 340, 50]]

    monkeypatch.setattr(captcha, "_det_backend", lambda: _Det())
    assert len(captcha.detect_targets(b"x", expect=2)) == 2


# ---------------- 可达性：点击分支必须早于「找输入框」 ----------------

def test_click_branch_runs_before_the_answer_box_lookup():
    import io
    from pathlib import Path

    src = io.open(os.path.join(Path(__file__).resolve().parents[1],
                               "crawlers", "captcha.py"),
                  encoding="utf-8").read()
    body = src[src.index("def attempt(page"):]
    i_click = body.index('if k.name == "click":')
    i_box = body.index("box = _first(page, _INPUT_SELECTORS)")
    assert i_click < i_box, (
        "点击分支排在『找答案输入框』之后：点选题没有 input，会先被挡掉")


# ---------------- 文案：限制性表述已清掉 ----------------

BANNED = ("交给人工", "交人工", "按性价比", "越算越像机器", "不必投入")


def test_no_restrictive_wording_left_in_challenge_modules():
    import io

    root = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    bad = []
    for name in ("crawlers/slider.py", "crawlers/captcha.py",
                 "crawlers/challenge.py", "config.example.yaml"):
        txt = io.open(os.path.join(root, name), encoding="utf-8").read()
        for w in BANNED:
            if w in txt:
                bad.append("%s：%s" % (name, w))
    assert not bad, "限制性文案没清干净：%s" % "、".join(bad)


def test_behavior_type_is_stated_as_scope_decision():
    """行为型不自动解要写成「范围决定」，而不是含糊的「暂不支持」。"""
    import io

    root = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    cfg = io.open(os.path.join(root, "config.example.yaml"),
                  encoding="utf-8").read()
    assert "范围决定" in cfg
    assert "真机" in cfg, "没给出提高采集率的替代方向"
