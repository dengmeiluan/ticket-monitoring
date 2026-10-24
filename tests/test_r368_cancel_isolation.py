# -*- coding: utf-8 -*-
"""r368: a cancelled in-flight fetch cannot seed a new probe task."""
import json
import threading
import time
from types import SimpleNamespace

import crawlers
import pytest
import webui


class _SlowLate:
    name = "slowlate"

    def __init__(self, cfg, logger):
        self.paths = []
        self.probe_mode = False
        self.on_path = None

    def login_url(self):
        return ""

    def fetch(self, fc, tc, dates):
        time.sleep(0.6)
        return [SimpleNamespace(
            price=100, airline="测试航", flight_no="LATE1",
            depart_time="08:00", arrive_time="10:00",
            extra=json.dumps([{"price": 100, "code": "LATE1",
                               "name": "测试航", "depTime": "08:00",
                               "arrTime": "10:00"}], ensure_ascii=False))]


def test_cancel_late_result_stays_old_and_new_task_rejected():
    old_reg = crawlers.REGISTRY.get("slowlate")
    old_cfg = getattr(webui._State, "cfg", None)
    old_last = webui._PROBE_LAST
    crawlers.REGISTRY["slowlate"] = _SlowLate
    webui._State.cfg = {"crawler": {}}
    webui._PROBE_LAST = 0
    webui._PROBE_AUTH.clear()
    cancel = threading.Event()
    result = {}

    def run_old():
        try:
            result["old"] = webui._probe_search(
                None, None, None, ["slowlate"],
                legs=[{"from": "上海", "to": "北京", "date": "2026-10-25"}],
                cancel=cancel)
        except Exception as e:  # pragma: no cover
            result["err"] = repr(e)

    try:
        th = threading.Thread(target=run_old)
        th.start()
        time.sleep(0.15)
        cancel.set()
        with pytest.raises(RuntimeError) as ei:
            webui._probe_search(
                None, None, None, ["slowlate"],
                legs=[{"from": "上海", "to": "北京", "date": "2026-10-25"}])
        assert "冷却" in str(ei.value) or "已有探针" in str(ei.value)
        th.join(timeout=10)
        assert not th.is_alive()
        assert "err" not in result
        old = result["old"]
        codes = [r.get("code") for r in old.get("rows") or []]
        assert "LATE1" in codes, "cancelled fetch result must be retained on the old task"
    finally:
        if old_reg is None:
            crawlers.REGISTRY.pop("slowlate", None)
        else:
            crawlers.REGISTRY["slowlate"] = old_reg
        webui._State.cfg = old_cfg
        webui._PROBE_LAST = old_last
        webui._PROBE_AUTH.clear()
