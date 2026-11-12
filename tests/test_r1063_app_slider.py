# -*- coding: utf-8 -*-
"""r1063 T81：App 内滑块验证的识别与自动尝试。

**现场证据**（2026-11-08 真机，飞猪 App 点「机票」后，1260×2800）：

    验证码拦截
    亲，请拖动下方滑块完成验证
    通过验证以确保正常访问
    [滑块]  向右滑动验证        ← UI 树里可达时能拿到

* 用 `adb shell input swipe` 单段等速直线滑一次 → 页面回
  `请点我重试(error:x2VW8)`：**轨迹被判成机器**，不是位置不对；
* 改用多段变速轨迹（ease-out + y 抖动 + 端点微调）才有机会过；
* 这个页面的滑块的**可访问性节点会消失**（渲染进 canvas），
  所以识别要能"节点消失时也认得出"（下一轮补截图兜底）。

这也解释了为什么我们之前把它当成「未到 Flutter 表单」：树里只有
`WVUCWebView` 和几行文案，没有我们熟悉的"验证码"关键词。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.android import appvcode  # noqa: E402

REAL = (
    '<hierarchy>'
    '<node text="验证码拦截" class="android.webkit.WebView" '
    'bounds="[0,68][1260,2800]"/>'
    '<node text="亲，请拖动下方滑块完成验证" bounds="[334,1451][928,1508]"/>'
    '<node text="通过验证以确保正常访问" bounds="[0,1523][1260,1577]"/>'
    '<node text="滑块" bounds="[203,1644][385,1779]"/>'
    '<node text="向右滑动验证" bounds="[189,1630][1058,1788]"/>'
    '</hierarchy>'
)


def test_detects_the_real_fliggy_slider_page():
    assert appvcode.is_slider_page(REAL) is True


def test_normal_page_is_not_a_slider():
    assert appvcode.is_slider_page(
        '<hierarchy><node text="航班列表" bounds="[0,0][10,10]"/></hierarchy>'
    ) is False
    assert appvcode.is_slider_page("") is False


def test_geometry_uses_handle_and_track_ends():
    geo = appvcode.slider_geometry(REAL)
    assert geo is not None
    assert geo["from"][0] < geo["to"][0], geo
    assert geo["distance"] > 400, geo
    # 轨道右端要留一点余量（贴边容易被判"没滑到位/滑过头"）
    assert geo["to"][0] <= 1058, geo


def test_human_path_is_monotonic_with_jitter():
    pts = appvcode.human_path(294, 1712, 1045, steps=40, seed=7)
    xs = [p[0] for p in pts]
    assert len(pts) >= 40
    assert xs == sorted(xs), "轨迹必须单调向右"
    assert pts[-1][0] == 1045, "末点必须精确落到轨道右端"
    # y 轴要有抖动（直线是最容易被判机器的特征之一）
    assert len({p[1] for p in pts}) > 1


def test_reports_platform_error_code_when_blocked():
    """平台自报 error 码要原样带回，才能区分"轨迹被识别"与"位置不对"。"""

    class _Dev:
        def __init__(self):
            self.n = 0

        def dump(self):
            self.n += 1
            if self.n == 1:
                return REAL
            return REAL.replace("向右滑动验证", "请点我重试(error:x2VW8)")

        def u2_swipe_points(self, pts, dur=1.0):
            return True

    rep = appvcode.solve(_Dev(), tries=1)
    assert rep["ok"] is False
    assert "x2VW8" in rep["why"], rep


def test_marks_success_when_page_changes():
    class _Dev:
        def __init__(self):
            self.n = 0

        def dump(self):
            self.n += 1
            if self.n == 1:
                return REAL
            return ('<hierarchy><node text="机票" bounds="[0,0][10,10]"/>'
                    '<node text="航班查询" bounds="[0,0][10,10]"/></hierarchy>')

        def u2_swipe_points(self, pts, dur=1.0):
            return True

    rep = appvcode.solve(_Dev(), tries=2)
    assert rep["ok"] is True and rep["tries"] == 1, rep


def test_never_raises_on_broken_device():
    class _Bad:
        def dump(self):
            raise RuntimeError("boom")

    rep = appvcode.solve(_Bad(), tries=1)
    assert rep["ok"] is False

    class _NoGeo:
        def dump(self):
            return "<hierarchy></hierarchy>"

        def u2_swipe_points(self, pts, dur=1.0):
            return True

    assert appvcode.solve(_NoGeo(), tries=1)["ok"] is False


def test_wired_into_clear_blockers_for_every_app_channel():
    src = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "crawlers", "app_base.py"), encoding="utf-8").read()
    assert "appvcode.is_slider_page" in src
    assert 'path_note(\n                    "app-captcha"' in src or \
        '"app-captcha"' in src
