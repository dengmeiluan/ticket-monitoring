# -*- coding: utf-8 -*-
"""r1156：槽位核验结果只在内存 → 每次重启都退回「已存待验」。

现场（2026-11-10 10:36 实测）：`tuniu_h5` 核验通过（`page_ok`/`available`，
`verified_at=10:36:02`）；重启 8765 后同一槽位 `verified_at` 变回空，
用户读到的又是「我登录了，你页面没变」。

修法：核验结论落盘到 `user_data/slot_verify.json`，启动时读回。
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

WEBUI = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


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
