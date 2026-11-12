# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_app_gone_breaker.py
- tests/test_r1063_app_stall_breaker.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import io
import os
import sys
import time


# ---- merged from tests/test_r1063_app_gone_breaker.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return io.open(os.path.join(ROOT, "crawlers", "app_base.py"),
                   encoding="utf-8").read()


def test_app_gone_recorded_and_bounded(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    from core import service_state as ss

    class Fake:
        name = "app_fliggy"
        APP_GONE_S = 7200
        config = {}
        logger = type("L", (), {"warning": lambda *a, **k: None})()

    from crawlers import app_base
    # 直接调用未绑定方法（只需要 name/config/logger/APP_GONE_S）
    from crawlers.app_base import AppCrawler
    AppCrawler.note_app_gone(Fake(), "切前台后 App 不在（自行退出）")

    root = str(tmp_path)
    left = ss.until(root, "app_fliggy", "app_gone") - __import__("time").time()
    assert left > 1000, left
    detail = ss.detail(root, "app_fliggy", "app_gone")
    assert "自行退出" in detail


def test_early_skip_has_app_gone_gate_first():
    src = _src()
    i = src.index("def early_skip")
    end = src.find("\n    def ", i + 1)
    seg = src[i:end if end > i else i + 9000]
    assert "app_gone_left_s" in seg, seg[:300]
    # 必须在 service_closed 之前（最省时间）
    assert seg.index("app_gone_left_s") < seg.index("service_closed_skip")


def test_prepare_device_checks_liveness():
    src = _src()
    i = src.index("def prepare_device")
    seg = src[i:i + 2600]
    assert "前置·存活" in seg
    assert "_app_alive" in seg
    assert "note_app_gone" in seg


def test_window_is_configurable():
    src = _src()
    assert "APP_GONE_S" in src
    assert "app_gone_s" in src, "应支持 config android.app_gone_s 覆盖"


# ---- merged from tests/test_r1063_app_stall_breaker.py ----

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
