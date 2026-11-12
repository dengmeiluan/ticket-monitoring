# -*- coding: utf-8 -*-
"""r1810：日期超出 App 视野的，规划阶段就别派它。

账本证据（app_zhixing 近 24h）：`app-date unsupported` **27 次** —— 每次都要启一次
App 走一趟才判「日期超出 App 视野，交浏览器」。这是能力边界（不该算失败），
但代价是真的（一次启动十几秒）。
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main as M  # noqa: E402

TODAY = date.today()


def test_far_dates_drop_app_channels_only():
    far = (TODAY + timedelta(days=200)).isoformat()
    near = (TODAY + timedelta(days=10)).isoformat()
    plats = {"app_zhixing", "app_qunar", "ctrip", "fliggy"}

    kept, dropped = M._drop_far_app_channels(plats, far, {})
    assert "app_zhixing" not in kept and "app_qunar" not in kept
    assert {"ctrip", "fliggy"} <= kept, "浏览器渠道不该被剔"
    assert {p for p, _ in dropped} == {"app_zhixing", "app_qunar"}

    kept2, dropped2 = M._drop_far_app_channels(set(plats), near, {})
    assert dropped2 == [], "近日期不该被剔"
    assert "app_zhixing" in kept2


def test_horizon_config_override():
    assert M._app_horizon_days({}, "app_zhixing") == 62
    cfg = {"crawler": {"app_date_horizon_days": 90}}
    assert M._app_horizon_days(cfg, "app_zhixing") == 90
    cfg2 = {"crawler": {"app_date_horizon_days": 90,
                        "app_date_horizon_days_map": {"app_ctrip": 120}}}
    assert M._app_horizon_days(cfg2, "app_ctrip") == 120
    assert M._app_horizon_days(cfg2, "app_qunar") == 90


def test_bad_date_is_noop():
    kept, dropped = M._drop_far_app_channels({"app_zhixing"}, "not-a-date", {})
    assert kept == {"app_zhixing"} and dropped == []


def test_filter_is_wired_before_failover():
    import io
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "main.py"), encoding="utf-8").read()
    i = src.index("_drop_far_app_channels(plats")
    j = src.index("预置换道（r1063 T23）")
    assert i < j, "过滤必须在换道展开之前"
