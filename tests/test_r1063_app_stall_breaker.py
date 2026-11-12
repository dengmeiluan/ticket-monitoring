# -*- coding: utf-8 -*-
"""r1063 T148：App 渠道"连续未取到结果"也熔断。

实测（整轮 386s / 7 查询）：App 侧本轮 0 行，但 `app_ctrip timeout 6 次`
——每轮都在白等设备时间。`app_gone`（T129）只覆盖"App 自行退出"，
管不到"能起但一直打不开/拿不到结果"。

现在：连续 3 次未取到结果 → `service_state(app_stall, 默认 1800s)`
→ `early_skip` 第二道闸直接跳过并如实记 `timeout`（带还剩多少分钟）；
成功一次即清零。
"""
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return io.open(os.path.join(ROOT, "crawlers", "app_base.py"),
                   encoding="utf-8").read()


def test_defaults_are_sane():
    from crawlers.app_base import AppCrawler
    assert AppCrawler.APP_STALL_STREAK >= 2, "太敏感会把偶发当熔断"
    assert AppCrawler.APP_STALL_S >= 600, "窗口太短等于没熔断"


def test_stall_recorded_and_bounded(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    from core import service_state as ss
    from crawlers.app_base import AppCrawler

    class Fake:
        name = "app_ctrip"
        APP_STALL_STREAK = 3
        APP_STALL_S = 1800
        config = {}
        _timeout_streak = 3
        logger = type("L", (), {"warning": lambda *a, **k: None})()

    AppCrawler.note_app_stall(Fake(), "连续 3 次未取到结果")
    left = ss.until(str(tmp_path), "app_ctrip", "app_stall") - time.time()
    assert left > 1000, left


def test_early_skip_checks_stall_after_gone():
    src = _src()
    i = src.index("def early_skip")
    seg = src[i:i + 2000]
    assert "app_gone_left_s" in seg and "app_stall_left_s" in seg
    assert seg.index("app_gone_left_s") < seg.index("app_stall_left_s"), \
        "顺序：先查自杀熔断，再查连续超时"


def test_success_resets_streak():
    src = _src()
    i = src.index('if got:')
    seg = src[i:i + 300]
    assert "_timeout_streak = 0" in seg, "成功一次必须清零，否则会误熔断"


def test_timeout_increments_and_triggers():
    src = _src()
    i = src.index('return self.path_note(path, "timeout"')
    seg = src[max(0, i - 700):i]
    assert "_timeout_streak" in seg and "note_app_stall" in seg
