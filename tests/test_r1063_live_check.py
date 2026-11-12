# -*- coding: utf-8 -*-
"""r1063 T100：`python -m core.live_check` —— 一条命令抽查**线上**能力。

为什么需要：`webui.py` 是 4.9MB 单文件、多人并行编辑的热点。本会话就发生过两次
"代码里有、线上没有"：并行会话整段重写后，面板接线在工作树里静默消失，
而实例跑的就是被覆盖的版本。**上线验收必须读 `/api`，不能只看代码。**

判据（任一不满足 → 退出码 1）：
1. 版本与源码一致（跑旧发行版会被点名）；
2. 登录槽位 9 格，且 PC 槽不指向移动域；
3. 渠道对象带 `session`（可用窗口）；
4. 通路读数带 `why`（失败原因原文）；
5. 降级账本可读。
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import live_check as LC  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GOOD_SLOTS = {
    "ctrip": {"surface_label": "PC", "login_url": "https://passport.ctrip.com/x"},
    "ctrip_h5": {"surface_label": "H5", "login_url": "https://m.ctrip.com/"},
    "fliggy": {"surface_label": "PC", "login_url": "https://www.fliggy.com/"},
    "fliggy_h5": {"surface_label": "H5", "login_url": "https://m.tb.com/"},
    "tongcheng": {"surface_label": "PC", "login_url": "https://www.ly.com/"},
    "tongcheng_h5": {"surface_label": "H5", "login_url": "https://m.ly.com/"},
    "tuniu": {"surface_label": "PC", "login_url": "https://passport.tuniu.com/"},
    "tuniu_h5": {"surface_label": "H5", "login_url": "https://m.tuniu.com/"},
    "qunar": {"surface_label": "全端·已停服", "login_url": "https://user.qunar.com/"},
}


def _fake_get(base, path, timeout=20.0):
    if path == "/api/state":
        return {"version": LC.source_version() or "0"}
    if path == "/api/login-state":
        return {"slots": dict(GOOD_SLOTS)}
    if path == "/api/pacing":
        return {"channels": {"fliggy": {"session": {"windows": 1},
                                        "paths": {"PC": {"why": "ok"}}}},
                "degraded": {"device_env": {"n": 1}}}
    raise AssertionError(path)


def test_all_good(monkeypatch):
    monkeypatch.setattr(LC, "_get", _fake_get)
    rep = LC.check(8765)
    assert rep["ok"] is True, rep
    assert rep["detail"]["slots"] == 9
    assert rep["detail"]["with_session"] == 1
    assert rep["detail"]["why_rows"] == 1


def test_flags_version_mismatch(monkeypatch):
    def g(base, path, timeout=20.0):
        if path == "/api/state":
            return {"version": "1.5.307"}
        return _fake_get(base, path, timeout)

    monkeypatch.setattr(LC, "_get", g)
    rep = LC.check(8765)
    assert rep["ok"] is False
    assert any("版本不一致" in p for p in rep["problems"]), rep


def test_flags_pc_slot_pointing_at_mobile(monkeypatch):
    def g(base, path, timeout=20.0):
        if path == "/api/login-state":
            bad = {k: dict(v) for k, v in GOOD_SLOTS.items()}
            bad["tuniu"]["login_url"] = "https://m.tuniu.com/flight/"
            return {"slots": bad}
        return _fake_get(base, path, timeout)

    monkeypatch.setattr(LC, "_get", g)
    rep = LC.check(8765)
    assert rep["ok"] is False
    assert any("移动域" in p for p in rep["problems"]), rep


def test_flags_missing_session_and_why(monkeypatch):
    def g(base, path, timeout=20.0):
        if path == "/api/pacing":
            return {"channels": {"fliggy": {"paths": {"PC": {}}}},
                    "degraded": {}}
        return _fake_get(base, path, timeout)

    monkeypatch.setattr(LC, "_get", g)
    rep = LC.check(8765)
    assert rep["ok"] is False
    assert any("session" in p for p in rep["problems"]), rep
    assert any("why" in p for p in rep["problems"]), rep


def test_offline_instance_reports_clearly(monkeypatch):
    def boom(*a, **k):
        raise OSError("refused")

    monkeypatch.setattr(LC, "_get", boom)
    rep = LC.check(1)
    assert rep["ok"] is False and "连不上" in rep["problems"][0]


def test_source_version_matches_main():
    txt = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    v = LC.source_version()
    assert v and '__version__ = "%s"' % v in txt
