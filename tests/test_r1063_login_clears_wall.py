# -*- coding: utf-8 -*-
"""r1063 T128：登录成功必须**立刻清掉登录墙记忆**。

本会话反复出现的坑：用户刚登录完，面板却还写着「还需等 N 分钟」，
下一轮也照样跳过 → 用户体感"登录无效"。

登录墙有两层记忆：
1. `user_data/<plat>/login_wall.json`（App 侧 `mark_login_wall` 落的）
2. `core.service_state` 的 memo（跨进程）

登录成功那一刻两处都要清，并且**清理失败不能让登录变失败**（登录已是成功路径）。
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fn():
    import webui
    return webui._clear_login_wall_memo


def test_clears_app_login_wall_file(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    d = tmp_path / "app_ctrip"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "login_wall.json"
    f.write_text(json.dumps({"until": 9e9, "detail": "该日被要求登录"}),
                 encoding="utf-8")
    cleared = _fn()("app_ctrip")
    assert not f.exists(), "登录墙文件没被清掉"
    assert any("app_ctrip" in c for c in cleared), cleared


def test_clears_service_state_memo(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    from core import service_state as ss
    ss.mark(str(tmp_path), "app_fliggy", "login_wall", "需登录", window_s=600)
    assert ss.until(str(tmp_path), "app_fliggy", "login_wall") > 0
    cleared = _fn()("app_fliggy")
    assert ss.until(str(tmp_path), "app_fliggy", "login_wall") == 0
    # 注意：service_state 的 memo 就是同一个 login_wall.json（两层实为一层），
    # 所以这里只要求"清单里提到该渠道"，不纠结是文件还是 memo。
    assert any("app_fliggy" in c for c in cleared), cleared


def test_noop_when_nothing_to_clear(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    assert _fn()("ctrip") == []


def test_wired_into_login_success_path():
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    i = src.index("干预入账失败")
    seg = src[i:i + 900]
    assert "_clear_login_wall_memo" in seg, seg[:300]
