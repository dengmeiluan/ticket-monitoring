# -*- coding: utf-8 -*-
"""r805be：内嵌手机画面要能「拖」——只有点击等于只能点当前屏第一页。

用户原话：「内嵌画中画的整体交互/能力/可操作性感觉比较有限，最好做成接近
无感操作模拟器」。两个 App 的主路径大量依赖滚动（热门城市列表、低价日历、
结果列表），原来画面只能点一下，滚不动 = 大半功能在画面里做不到。

本用例守四层：设备调用（dur 夹取/越界拒绝）→ 会话计数 → API 路由 → 前端接线。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.android.login_api import dispatch
from core.android.login_session import AppLoginRegistry, AppLoginSession

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Dev:
    size = (900, 1600)

    def __init__(self):
        self.swipes = []
        self.ok = True

    def window_size(self):
        return self.size

    def swipe(self, x1, y1, x2, y2, dur=300):
        self.swipes.append((x1, y1, x2, y2, dur))
        return self.ok


class RT:
    def __init__(self, dev):
        self._d = dev

    def device(self):
        return self._d


def _sess(dev):
    return AppLoginSession("app_qunar", RT(dev), "com.Qunar")


def test_swipe_forwards_and_counts():
    dev = Dev()
    s = _sess(dev)
    assert s.swipe(100, 1200, 100, 400, 250) is True
    assert dev.swipes == [(100, 1200, 100, 400, 250)]
    assert s.view()["swipes"] == 1


def test_swipe_clamps_duration():
    dev = Dev()
    s = _sess(dev)
    s.swipe(0, 0, 10, 10, 5)          # 太短 → 抬到 80
    s.swipe(0, 0, 10, 10, 99999)      # 太长 → 压到 2000
    assert [d for *_, d in dev.swipes] == [80, 2000]


def test_swipe_rejects_out_of_screen():
    dev = Dev()
    s = _sess(dev)
    assert s.swipe(100, 1200, 100, 1700) is False
    assert not dev.swipes
    assert "超出屏幕" in s.detail


def test_api_routes_swipe():
    dev = Dev()
    reg = AppLoginRegistry()
    reg._sessions["app_qunar"] = _sess(dev)     # 直插会话，绕开建会话的设备流程
    res, code = dispatch(reg, "POST", "/api/app-login/swipe", {},
                         {"plat": "app_qunar", "x1": 90, "y1": 1300,
                          "x2": 90, "y2": 500, "dur": 300}, {})
    assert code == 200 and res.get("ok"), res
    assert dev.swipes == [(90, 1300, 90, 500, 300)]


def test_frontend_drag_is_wired_to_swipe():
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert "/api/app-login/swipe" in src, "前端没接到滑动接口"
    assert "appLoginPtrDown" in src and "appLoginPtrUp" in src, "拖动没接线"
    assert "touch-action:none" in src, (
        "命中层缺 touch-action:none：触摸设备上拖动会被浏览器手势吃掉")
    # 拖动结束不能再补一刀 tap（否则滚动后误点）
    assert "APP_DRAG_AT" in src, "拖动后没有抑制补发的 click"

def test_polling_is_adaptive_around_interactions():
    """操作后快取（跟手），静置降频（别跟扫描抢 adb 资源）。"""
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert "function appLoginNextDelay()" in src, "轮询间隔没有自适应"
    assert "appLoginMark()" in src
    assert "setTimeout(()=>appLoginLoop(plat),appLoginNextDelay())" in src, (
        "轮询仍用固定间隔")
    body = src[src.index("function appLoginNextDelay()"):]
    body = body[:body.index("}")]
    assert "120" in body and "700" in body, (
        "自适应间隔缺档位（应为操作后 120ms / 静置 700ms）：%r" % body)
