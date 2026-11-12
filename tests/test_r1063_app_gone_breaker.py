# -*- coding: utf-8 -*-
"""r1063 T129：识别「App 自行退出」并熔断，避免每轮白烧设备时间。

用户实测：飞猪「一点机票查询就程序重启」。核查结果：没有 tombstone、没有 SIGSEGV
——是 App **主动退出**（阿里检测到环境异常后自杀）。以前这套流程只会记一个
`timeout`，然后下一轮再花 80–150 秒试一次，账本上还看不出是风控。

现在：
1. `note_app_gone()` → 记 `service_state(app_gone, 默认 7200 秒)` + 降级项
   `app_risk_blocked`（面板可见：「App 风控」）；
2. `early_skip()` 第一道闸就是它：窗口内直接跳过并记 `blocked`（带剩余分钟），
   与「登录墙短路」同一形态；
3. `prepare_device()` 切前台后多一次「前置·存活」校验，退出即记账。
"""
import io
import os
import sys

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
