# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1156_slot_verify_persist.py
- tests/test_r508_slot_tone_matches_text.py
- tests/test_r509_slot_saved_at_readable.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import json
import os
import pytest
import sys
import threading
import time

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


# ---- merged from tests/test_r1156_slot_verify_persist.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

WEBUI = webui_full_src()


def test_source_has_persistence_hooks():
    """源码必须有落盘/读回两个钩子，且写完后立刻落盘。"""
    assert "slot_verify.json" in WEBUI, "没有落盘文件名"
    assert "def _slot_verify_load(" in WEBUI, "缺少 _slot_verify_load"
    assert "def _slot_verify_save(" in WEBUI, "缺少 _slot_verify_save"
    assert "_SLOT_VERIFY.update(_slot_verify_load())" in WEBUI, (
        "启动时没有把上次核验结论读回来")
    assert "_slot_verify_save()" in WEBUI, "核验后没有落盘"


def test_round_trip_through_disk(tmp_path, monkeypatch):
    """行为断言：save → load 必须原样读回；坏文件/缺文件必须静默降级为空。"""
    import webui

    target = tmp_path / "slot_verify.json"
    monkeypatch.setattr(webui, "_SLOT_VERIFY_PATH", str(target), raising=False)

    assert webui._slot_verify_load() == {}, "文件不存在时必须返回空，不能抛"

    payload = {"tuniu_h5": {"ok": True, "status": "page_ok",
                            "detail": "页面未命中登录墙/验证",
                            "at": "2026-11-10 10:36:02", "ts": 1794276962.0}}
    monkeypatch.setattr(webui, "_SLOT_VERIFY", dict(payload), raising=False)
    webui._slot_verify_save()
    assert target.is_file(), "没有写出文件"
    assert json.loads(target.read_text(encoding="utf-8"))["tuniu_h5"]["status"] == "page_ok"
    assert webui._slot_verify_load() == payload, "读回内容必须与写入一致（重启不丢）"

    target.write_text("{bad json", encoding="utf-8")
    assert webui._slot_verify_load() == {}, "坏文件必须静默降级为空，不能抛异常"


# ---- merged from tests/test_r508_slot_tone_matches_text.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _login_state():
    """同一厂商两个槽位：小标只在「有多个独立会话」的厂商上渲染，
    所以这里必须让 PC 与 H5 同时在场（飞猪就是这种形态）。
    三个证据强度各一档：已存待验 / 明细可用 / 入口可达。"""
    base = {"name": "飞猪", "account": "a***@b.c", "requirement": "必须登录",
            "login_url": "https://example.invalid/", "active": False,
            "saving": False, "pending": False, "error": "",
            "needs_login": False, "health_need_login": False,
            "profile": "p", "saved_at": 0, "plat": "fliggy"}
    return {"ok": True, "plats": {}, "slots": {
        "fliggy": dict(base, slot="fliggy", surface="pc",
                       surface_label="PC", saved=True, status="saved",
                       detail="", verified_at="", page_ok=False,
                       session_verified=False, detail_ok=False),
        "fliggy_h5": dict(base, slot="fliggy_h5", surface="h5",
                          surface_label="H5", saved=True,
                          status="page_ok", detail="页面未命中登录墙/验证",
                          verified_at="2026-10-29 10:00:00", page_ok=True,
                          session_verified=True, detail_ok=False),
    }}




# ---- merged from tests/test_r509_slot_saved_at_readable.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _slots(saved_at):
    base = {"name": "飞猪", "account": "a***@b.c", "requirement": "必须登录",
            "login_url": "https://example.invalid/", "active": False,
            "saving": False, "pending": False, "error": "",
            "needs_login": False, "health_need_login": False,
            "profile": "p", "plat": "fliggy", "saved": True,
            "detail": "", "verified_at": "", "page_ok": False,
            "session_verified": False, "detail_ok": False}
    return {"ok": True, "plats": {}, "slots": {
        "fliggy": dict(base, slot="fliggy", surface="pc",
                       surface_label="PC", status="saved",
                       saved_at=saved_at),
        "fliggy_h5": dict(base, slot="fliggy_h5", surface="h5",
                          surface_label="H5", status="saved",
                          saved_at=saved_at),
    }}








