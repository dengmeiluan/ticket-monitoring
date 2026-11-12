# -*- coding: utf-8 -*-
"""r1063 T130：登录一次，同厂商的 App 渠道也要清墙。

缺口很实在：登录槽位 plat 是 `ctrip`，而携程 **App** 渠道的记忆在
`user_data/app_ctrip/`。以前只清 `ctrip/`，于是"浏览器登录成功了，App 还显示
需登录 N 分钟"——用户体感就是登录没用。

现在按 `VENDOR_APP_PLATS` 映射把同厂商的 `login_wall` 与 `app_gone`
（App 自杀熔断）一并清掉。
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


def _pin_root(tmp_path, monkeypatch):
    """把"根目录"钉到 tmp_path（三处来源全对齐）。

    必须钉 `_ud_root_runtime()`：`_effective_crawler_config()` 会用它覆盖
    `user_data_dir`，而它是**启动时缓存**的——只设环境变量对已启动实例无效。
    这也是"单独跑绿、批量跑红"的真因。
    """
    import webui
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(webui, "_ud_root_runtime", lambda: str(tmp_path),
                        raising=False)
    monkeypatch.setattr(
        webui._State, "cfg",
        {"crawler": {"user_data_dir": str(tmp_path)}}, raising=False)
    webui._State.login_sessions.clear()
    return webui


def test_ctrip_login_clears_app_ctrip(tmp_path, monkeypatch):
    _pin_root(tmp_path, monkeypatch)
    for plat in ("ctrip", "app_ctrip"):
        d = tmp_path / plat
        d.mkdir(parents=True, exist_ok=True)
        (d / "login_wall.json").write_text(
            json.dumps({"until": 9e9, "detail": "该日被要求登录"}),
            encoding="utf-8")

    cleared = _fn()("ctrip")
    assert not (tmp_path / "ctrip" / "login_wall.json").exists()
    assert not (tmp_path / "app_ctrip" / "login_wall.json").exists(), \
        "同厂商 App 渠道的墙没被清：%r" % (cleared,)
    assert any("app_ctrip" in c for c in cleared), cleared


def test_fliggy_login_clears_app_gone_memo(tmp_path, monkeypatch):
    _pin_root(tmp_path, monkeypatch)
    from core import service_state as ss
    ss.mark(str(tmp_path), "app_fliggy", "app_gone", "自行退出", window_s=7200)
    assert ss.until(str(tmp_path), "app_fliggy", "app_gone") > 0

    _fn()("fliggy_h5")
    assert ss.until(str(tmp_path), "app_fliggy", "app_gone") == 0, \
        "登录后 App 自杀熔断也该被清掉"


def test_unknown_vendor_only_clears_itself(tmp_path, monkeypatch):
    _pin_root(tmp_path, monkeypatch)
    d = tmp_path / "some_new_vendor"
    d.mkdir(parents=True, exist_ok=True)
    (d / "login_wall.json").write_text("{}", encoding="utf-8")
    cleared = _fn()("some_new_vendor")
    assert any("some_new_vendor" in c for c in cleared), cleared


def test_vendor_map_covers_all_slots():
    import webui
    needed = {"ctrip", "fliggy", "tongcheng", "tuniu", "qunar"}
    assert needed <= set(webui.VENDOR_APP_PLATS), webui.VENDOR_APP_PLATS
