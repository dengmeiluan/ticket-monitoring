# -*- coding: utf-8 -*-
"""r930：慢机判死——固定秒数等页面，在"整机被拖慢"时必然失败。

真实日志（2026-11-03，14 次一模一样）：

    [app_zhixing] 前台是 com.Qunar，先切回 cn.suanya.zhixing（上一渠道未退出）
    [app_zhixing] 设置航线失败：首页未就绪（等待 60s 并回退 4 级仍找不到「机票查询」）

看着像"App 打不开"，其实是**预算算错了**：

* 空载一帧 `uiautomator dump` ≈2–3s → 60s 能取 20 帧，绰绰有余；
* **整机跑着 5 个浏览器渠道时单帧能到 ~20s** → 60s 只够 3 帧；
* 而"连续两帧都是首页"最少要 6 帧（中间任一帧是残留日历弹层就重置计数）。

于是慢机上**必然超时**，而判定文案说的是"App 没打开"——把人往错方向引。

修法（两处，同一策略）：
  1. `crawlers/app_base.py::wait_ready()` —— 抽出**共享实现**：按帧数预算
     + 首帧慢则自适应放宽总时长。以后各渠道等页面都该用它，别各写一套秒数。
  2. `app_zhixing_nav.set_flight_route()` —— 改成 14 帧 / 90s（慢机放宽到
     150s），并把 BACK 回退从 4 级加到 6 级（两层弹层差一步）。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r930_ready_budget.py -q
"""
import io
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers.app_base import wait_ready  # noqa: E402


class FakeDev:
    """按脚本逐帧返回 dump；``delay`` 模拟单帧耗时。"""

    def __init__(self, frames, delay=0.0):
        self.frames = list(frames)
        self.delay = delay
        self.n = 0
        self.dumps = 0

    def dump(self):
        self.dumps += 1
        if self.delay:
            time.sleep(self.delay)
        i = min(self.n, len(self.frames) - 1)
        self.n += 1
        return self.frames[i]


HOME = '<node text="机票查询" />'
DIALOG = '<node text="机票查询" /><node text="Search_Calendar_Dialog_Title" />'
OTHER = '<node text="选择城市" />'


# ---------------------------------------------------------------------------
# 1. 正常路径
# ---------------------------------------------------------------------------
def test_ready_when_two_stable_frames():
    d = FakeDev([HOME, HOME, HOME])
    ok, xml, why = wait_ready(d, "机票查询", interval=0)
    assert ok is True and "机票查询" in xml


def test_residual_dialog_is_not_ready():
    """残留日历弹层里也有「机票查询」，但那是未就绪。"""
    d = FakeDev([DIALOG, HOME, HOME])
    ok, _, _ = wait_ready(d, "机票查询",
                          exclude=("Search_Calendar_Dialog_Title",),
                          interval=0)
    assert ok is True
    assert d.dumps >= 3          # 跳过第一帧弹层


def test_never_ready_reports_frames():
    d = FakeDev([OTHER])
    ok, _, why = wait_ready(d, "机票查询", frames=4, base_s=0.01,
                            interval=0)
    assert ok is False
    assert "未就绪" in why and "机票查询" in why


# ---------------------------------------------------------------------------
# 2. 帧数预算（核心修复）
# ---------------------------------------------------------------------------
def test_frame_budget_is_respected():
    """帧数上限必须生效——慢机上不能无限等。"""
    d = FakeDev([OTHER], delay=0.0)
    wait_ready(d, "机票查询", frames=5, base_s=999, interval=0)
    assert d.dumps == 5, d.dumps


def test_slow_first_frame_extends_deadline():
    """首帧慢 → 放宽总时长（否则慢机 3 帧就撞死）。"""
    # 每帧 0.05s，base_s 极小：若不放宽，帧数还没用完就超时退出
    d = FakeDev([OTHER, OTHER, OTHER, HOME, HOME], delay=0.05)
    ok, _, _ = wait_ready(d, "机票查询", frames=6, base_s=0.01,
                          slow_s=5, slow_frame_s=0.01, interval=0)
    assert ok is True, "首帧慢时没有放宽总时长"
    assert d.dumps >= 5


def test_stable_counter_resets_on_bad_frame():
    """中间夹一帧坏页面，连续计数要重置（否则残留弹层被当首页）。"""
    d = FakeDev([HOME, OTHER, HOME, HOME], delay=0.0)
    ok, _, _ = wait_ready(d, "机票查询", interval=0, stable=2)
    assert ok is True
    assert d.dumps >= 4


def test_single_stable_frame_when_stable_1():
    d = FakeDev([HOME], delay=0.0)
    ok, _, _ = wait_ready(d, "机票查询", interval=0, stable=1)
    assert ok is True and d.dumps == 1


# ---------------------------------------------------------------------------
# 3. 源码钉：智行改成了帧预算
# ---------------------------------------------------------------------------
def test_zhixing_uses_frame_budget():
    src = io.open(os.path.join(ROOT, "crawlers", "app_zhixing_nav.py"),
                  encoding="utf-8").read()
    assert "frames < 14" in src, "智行等首页仍没有帧数预算"
    assert "time.time() + 150" in src, "智行没有慢机自适应放宽"
    assert "for _ in range(6)" in src, "BACK 回退仍是 4 级（两层弹层会差一步）"
    # 失败文案必须报出**实际帧数与耗时**，便于下次判断是慢还是真打不开
    assert "等 %d 帧" in src


def test_await_home_also_uses_frame_budget():
    """同一策略的第二处：`_await_home` 也必须是帧预算。

    2026-11-04 复查发现 `_await_home` 仍是纯秒数（默认 30s）。慢机
    （5 个浏览器渠道同时占 CPU，单帧 ~20s）30s 只够 1–2 帧，于是判
    「没取到首页（dump 连续为空），无法判断当前档位」——看着像
    uiautomator 挂了，其实只是慢。
    """
    src = io.open(os.path.join(ROOT, "crawlers", "app_zhixing_nav.py"),
                  encoding="utf-8").read()
    i = src.find("def _await_home")
    assert i > 0
    seg = src[i:i + 1800]
    assert "frames: int = 10" in seg, "_await_home 没有帧预算参数"
    assert "for _ in range(max(2, int(frames)))" in seg, \
        "_await_home 仍按纯时间循环"
