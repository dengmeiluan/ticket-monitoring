# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r959_device_lock_visibility.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import os
import sys
import time

from entry_mon_harness import _goto, page, srv


# ---- merged from tests/test_r959_device_lock_visibility.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def test_view_reports_owner_and_budget(monkeypatch):
    import webui
    from core.android import runtime as rt_mod

    class FakeRT:
        def lock_state(self):
            return {"owner": "app_qunar",
                    "since": time.time() - 187,
                    "budget_left": 12.5, "deadline_hits": 3}

    monkeypatch.setattr(rt_mod, "get_runtime",
                        lambda cfg, logger=None: FakeRT())
    v = webui._device_lock_view({"android": {"enabled": True}})
    assert v["enabled"] is True
    assert v["owner"] == "app_qunar"
    assert 186 <= v["held_s"] <= 190, v
    assert v["budget_left"] == 12.5 and v["deadline_hits"] == 3


def test_view_is_silent_when_android_disabled():
    import webui
    v = webui._device_lock_view({"android": {"enabled": False}})
    assert v == {"enabled": False, "owner": "", "held_s": 0,
                 "budget_left": 0.0, "deadline_hits": 0,
                 "unavailable": ""}


def test_health_payload_carries_lock_view():
    import io
    w = webui_full_src()
    assert '_hp["device_lock"] = _device_lock_view(' in w
    assert 'out["device_lock"] = _device_lock_view({})' in w


