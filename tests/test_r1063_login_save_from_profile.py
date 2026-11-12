# -*- coding: utf-8 -*-
"""r1063 T139：登录后「保存」必须成功——即使窗口已经关了。

真机现象（用户实测）：在弹窗里登录成功，点「我已登录完成」存不下来。
根因：`_finish_login` 只在 `_State.login_sessions[key]` 存在时工作；用户一关窗
会话就没了 → 永远返回「该登录槽位没有进行中的登录窗口」。而 profile 里其实
已经把登录态写盘了（`user_data/tuniu/session-state.json` 643KB）。

现在：无窗口但 profile 里有会话文件（6 小时内）→ 按"已有登录态"保存：
清墙（同厂商一起）+ 后台复探 + 返回 `saved: true, profile_already_logged_in: true`。
两者都没有 → 保留诚实报错，并给出"登完直接关窗即保存"的提示。

真机验证：
```
tuniu    → ok=True saved=True profile=True
tuniu_h5 → ok=True saved=True profile=True
槽位：login_required → available，needs_login=False
```
"""
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_finish_login_saves_from_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    d = tmp_path / "tuniu"
    d.mkdir(parents=True, exist_ok=True)
    (d / "session-state.json").write_text(
        json.dumps({"cookies": [], "origins": []}), encoding="utf-8")

    import webui
    webui._State.cfg = {"crawler": {"user_data_dir": str(tmp_path)}}
    webui._State.login_sessions.clear()
    calls = []
    monkeypatch.setattr(webui._State, "probe_cb",
                        lambda p, scope="": (calls.append(p) or {"ok": True}),
                        raising=False)

    rep = webui._finish_login("tuniu", "tuniu")
    assert rep["ok"] is True, rep
    assert rep.get("saved") is True
    assert rep.get("profile_already_logged_in") is True
    time.sleep(0.5)
    assert calls and calls[0] == "tuniu", calls


def test_finish_login_without_profile_is_honest(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    import webui
    webui._State.cfg = {"crawler": {"user_data_dir": str(tmp_path)}}
    webui._State.login_sessions.clear()
    rep = webui._finish_login("tuniu", "tuniu")
    assert rep["ok"] is False
    assert "没有进行中的登录窗口" in rep["err"]
    assert "关窗" in (rep.get("hint") or ""), rep


def test_stale_profile_is_not_trusted(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    d = tmp_path / "tuniu"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "session-state.json"
    f.write_text("{}", encoding="utf-8")
    old = time.time() - 24 * 3600
    os.utime(f, (old, old))

    import webui
    webui._State.cfg = {"crawler": {"user_data_dir": str(tmp_path)}}
    webui._State.login_sessions.clear()
    rep = webui._finish_login("tuniu", "tuniu")
    assert rep["ok"] is False, "超过 6 小时的旧会话不该被当成刚登录"
