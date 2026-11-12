# -*- coding: utf-8 -*-
"""r813g：账本拦截不能被**另一端**同秒的明细证据抹掉。

现场（2026-11-01 22:21:11，data/prices.db）：
    tuniu PC blocked（滑块，0 行）+ tuniu H5/API ok（37 行）同一秒；
    之后到 00:45 没有任何 PC ok。
线上 /api/login-state 的 tuniu 却 status=available、block=null——
`_login_state_view` 把 `max(scopes.detail_at)` 作为 `detail_at` 传进
`_path_block_from_rows`，`base=max(saved_at, detail_at)` 让 PC 的
block（t<=base）被当成已恢复。用户点名的「途牛 PC 要验证码，为什么
登录处看不到」正是这条。

判据：同一 entry 的 ok/calendar/empty 或更新的 saved_at 才能解除；
别的端（H5/API）的明细证据不能解除 PC 的滑块。
"""
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui  # noqa: E402
from crawlers import REGISTRY  # noqa: E402

CAPTCHA = "人机验证页（滑块），需在渠道登录窗口完成验证"
TS = "2026-11-01 22:21:11"


def _row(entry, status, note="", rows=0):
    return {"fetched_at": TS, "entry_path": entry, "path_status": status,
            "note": note, "rows": rows, "request_url": ""}


class _Channel:
    login_suspect = False

    def __init__(self, cfg, logger):
        self.user_data_root = cfg.get("user_data_dir", "")

    @property
    def session_saved_at(self):
        return 0.0


@pytest.fixture
def env(monkeypatch, tmp_path):
    for p in REGISTRY:
        (tmp_path / p).mkdir(exist_ok=True)
        (tmp_path / p / "marker").write_text("profile", encoding="utf-8")
        monkeypatch.setitem(REGISTRY, p, _Channel)
    monkeypatch.setattr(webui._State, "cfg",
                        {"crawler": {"user_data_dir": str(tmp_path)}})
    monkeypatch.setattr(webui._State, "boot_cfg", None)
    monkeypatch.setattr(webui._State, "login_sessions", {})
    monkeypatch.setattr(webui._State, "login_pending", {})
    monkeypatch.setattr(webui._State, "login_errors", {}, raising=False)
    monkeypatch.setattr(webui._State, "logger", logging.getLogger("r813g"))
    monkeypatch.setattr(webui, "slot_crawler",
                        lambda key, cfg, logger: _Channel(cfg, logger))
    monkeypatch.setattr(webui, "_SLOT_VERIFY", {}, raising=False)
    monkeypatch.setattr(webui, "_ensure_slot_verify_loop", lambda: None)
    # 真实账本里 scopes.domestic.detail_at 就是这个时刻（来自 H5/API 那次成功）
    monkeypatch.setattr(webui, "_health_state", lambda hours: {
        "rounds": [], "evidence": {"tuniu": {"domestic": {"detail_at": TS}}}})
    monkeypatch.setattr(webui, "_recent_path_rows", lambda hours=24: {
        "tuniu": [_row("PC", "blocked", CAPTCHA),
                  _row("H5/API", "ok", "", 37)]})
    return tmp_path


def test_pc_captcha_is_not_masked_by_same_second_h5_detail(env):
    st = webui._login_state_view()["slots"]["tuniu"]
    assert st["status"] == "challenge", st
    assert st["block"] and st["block"]["kind"] == "captcha", st
    assert st["block"]["path"] == "PC", st


def test_pc_captcha_surfaces_without_any_detail_evidence(env, monkeypatch):
    """负控：没有明细证据时同样要红，证明上一条不是靠别的偶然路径。"""
    monkeypatch.setattr(webui, "_health_state", lambda hours: {
        "rounds": [], "evidence": {}})
    st = webui._login_state_view()["slots"]["tuniu"]
    assert st["status"] == "challenge", st
    assert st["block"] and st["block"]["path"] == "PC", st
