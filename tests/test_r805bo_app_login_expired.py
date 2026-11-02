# -*- coding: utf-8 -*-
"""r805bo：App 登录卡必须如实说「会话已失效」。

现场（2026-11-01 21:28 起）：去哪儿 App 的快照文件还在（卡片显示
「已保存 · 会话待验证」），但每轮采集都停在登录墙、账本记 `app-login/login`
与「快照已失效」。用户看到「待验证」就不会去重登——状态卡必须改成「需登录」。

判据三层：账本证据（先遇到 login/快照已失效 → 失效；先遇到带行数的 ok → 可用）
→ 接口下发 `needs_login` → 卡片把 needs_login 翻译成 login_required。
"""
import io
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _db(tmp_path, rows):
    p = tmp_path / "prices.db"
    c = sqlite3.connect(str(p))
    c.execute("CREATE TABLE fetch_paths (platform TEXT, entry_path TEXT,"
              " path_status TEXT, rows INTEGER, note TEXT, fetched_at TEXT)")
    for i, (st, n, note) in enumerate(rows):
        c.execute("INSERT INTO fetch_paths VALUES (?,?,?,?,?,datetime('now'))",
                  ("app_qunar", "航班明细", st, n, note))
    c.commit()
    c.close()
    return str(p)


def _call(monkeypatch, db):
    import webui
    monkeypatch.setattr(webui._State, "cfg", {"output": {"db_path": db}})
    return webui._app_login_expired("app_qunar")


def test_login_evidence_marks_expired(monkeypatch, tmp_path):
    db = _db(tmp_path, [("timeout", 0, "set-city-dep"),
                        ("login", 0, "需要手机号登录")])
    assert _call(monkeypatch, db) is True


def test_snapshot_invalid_note_marks_expired(monkeypatch, tmp_path):
    db = _db(tmp_path, [("ok", 0,
                         "登录态恢复（非取数）：已恢复快照；快照已失效（仍停在登录墙，需重新登录）")])
    assert _call(monkeypatch, db) is True


def test_recent_rows_mean_available(monkeypatch, tmp_path):
    db = _db(tmp_path, [("ok", 3, "3 条真实航班/时刻/价格"),
                        ("login", 0, "旧的登录墙")])
    assert _call(monkeypatch, db) is False


def test_empty_ledger_is_not_flagged(monkeypatch, tmp_path):
    db = _db(tmp_path, [])
    assert _call(monkeypatch, db) is False


def test_api_and_card_carry_needs_login():
    api = io.open(os.path.join(ROOT, "core", "android", "login_api.py"),
                  encoding="utf-8").read()
    assert '"needs_login"' in api, "接口没下发 needs_login"
    ui = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert '"needs_login": _needs_login' in ui, "ctx 没把账本证据接进去"
    assert "needs_login:!!a.needs_login" in ui, "App 槽位没带 needs_login"
    assert "s.needs_login?'login_required'" in ui, (
        "卡片没有把 needs_login 翻成「需登录」")
