# -*- coding: utf-8 -*-
"""r1063 T168：App 登录成功后必须**清登录墙记忆**（否则"登了也没用"）。

缺口：`login_api.handle_finish` 只 verify → snapshot → 落干预账，**不清**
`user_data/<plat>/login_wall.json` 与 service_state memo。于是用户明明在
App 里登成功了，面板/`early_skip` 仍按旧墙判「需登录（N 分钟内不再重试）」。

浏览器侧 T139 已做（`_finish_login` 无窗口也能保存 + 清墙）；这次补 App 侧，
成功后顺手后台复探一次（复用 T134 的 `_kick_login_probe`）。
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_app_login_finish_clears_wall_and_reprobes():
    """锚点必须用**本次改动独有**的文本：`/api/app-login/finish` 在 JS 里先出现，
    按它切片会切到前端代码里（本轮又踩了一次）。"""
    s = _src()
    i = s.index('note="App 内登录并导出快照（真机画面）")')
    seg = s[i:i + 1600]
    assert "_clear_login_wall_memo(_plata" in seg, \
        "App 登录成功后没有清登录墙记忆——用户会看到「登了还需要登录」"
    assert "_kick_login_probe(_plata)" in seg, \
        "登录成功应当顺手后台复探一次（与浏览器侧一致）"


def test_helper_clears_app_channel_wall(tmp_path, monkeypatch):
    """`_clear_login_wall_memo("app_ctrip")` 必须能清掉该渠道的墙文件。"""
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    d = tmp_path / "app_ctrip"
    d.mkdir(parents=True, exist_ok=True)
    (d / "login_wall.json").write_text(
        json.dumps({"until": 9e9, "detail": "该日被要求登录"}),
        encoding="utf-8")

    import webui
    monkeypatch.setattr(webui, "_ud_root_runtime", lambda: str(tmp_path),
                        raising=False)
    monkeypatch.setattr(webui._State, "cfg",
                        {"crawler": {"user_data_dir": str(tmp_path)}},
                        raising=False)
    cleared = webui._clear_login_wall_memo("app_ctrip", "app_ctrip")
    assert not (d / "login_wall.json").exists(), cleared
    assert any("app_ctrip" in c for c in cleared), cleared
