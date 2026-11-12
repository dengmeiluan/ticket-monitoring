# -*- coding: utf-8 -*-
"""r1063 T60：能力降级账本——fail-soft 必须留下可查的证据。

上轮的活教材：`geo.fix()` 调错设备 API，**定位固定从来没生效过**，只在日志里留过
一行 warning，藏了十几轮才被测试撞出来。"能力悄悄关掉"和"一切正常"在界面上长得
一模一样——这条把两者分开。

约定：只记**能力级**降级（定位没设上 / 识别后端缺失 / UA 与内核不同步），
不记单次网络抖动（那会淹没真问题）；不改控制流，调用方照旧 fail-soft。
"""
import io
import os

import pytest

from core import degraded as dg
from core.pacing import Pacing

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEO = io.open(os.path.join(ROOT, "core", "android", "geo.py"),
              encoding="utf-8").read()
CAPTCHA = io.open(os.path.join(ROOT, "crawlers", "captcha.py"),
                  encoding="utf-8").read()
BASE = io.open(os.path.join(ROOT, "crawlers", "base.py"),
               encoding="utf-8").read()
SRC = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


@pytest.fixture(autouse=True)
def _clean():
    dg.reset()
    yield
    dg.reset()


def test_counts_aggregate_per_capability():
    dg.note("app_geo", "", "emu geo fix 失败")
    dg.note("app_geo", "fliggy")
    dg.note("captcha_det", "", "缺后端")
    snap = dg.snapshot()
    assert snap["app_geo"]["n"] == 2, snap
    assert snap["app_geo"]["plats"].get("fliggy") == 1, snap
    assert "缺后端" in snap["captcha_det"]["last"]
    assert dg.total() == 3


def test_empty_capability_is_ignored():
    dg.note("", "", "没名字的不记")
    assert dg.snapshot() == {}


def test_ledger_never_raises_on_bad_input():
    dg.note("x", "", "", n="abc")      # 不抛
    assert dg.snapshot()["x"]["n"] == 1


def test_pacing_snapshot_carries_it():
    dg.note("app_geo", "", "失败")
    got = Pacing({"fliggy": {}}).snapshot()
    assert "degraded" in got and got["degraded"]["app_geo"]["n"] == 1, got


def test_geo_failure_is_recorded():
    assert 'dg.note("app_geo"' in GEO or "_dg.note(\"app_geo\"" in GEO


def test_missing_detector_is_recorded():
    assert 'note("captcha_det"' in CAPTCHA


def test_ua_kernel_mismatch_is_recorded():
    assert 'note("ua_kernel"' in BASE


def test_panel_shows_the_degraded_line_only_when_needed():
    # 窗口放宽：T61 又往 tips 里加了「下一步」（_DGFIX），1400 字不够
    seg = SRC[SRC.index("const _degradeLine="):][:2200]
    assert "j.degraded" in seg
    assert "if(!keys.length)return '';" in seg, "没有降级时不该占位"
    # 中文能力名与原因都要有
    assert "识别后端" in seg and "定位" in seg
    assert "esc(tips.join" in seg, "提示文案要转义"
    # r1392：右栏重构后降级行与建议/弱通路成组渲染，读数折叠进 pace-fold；
    # 断言保留原意——降级行必须挂在右栏（pace-side）且与建议同组。
    assert "+_degradeLine+_adviceLine+_pathLine" in SRC, "没挂到右栏"
    assert "+_stats+_rail+_kv+_fostats" in SRC, "读数未折进 pace-fold"
