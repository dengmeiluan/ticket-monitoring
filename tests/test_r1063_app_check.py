# -*- coding: utf-8 -*-
"""r1063 T187-T188：App 登录态**对账**工具 + 登录墙取证。

背景（用户实测）：「APP 三家已经登录了…但页面没变」。设备层 dump 显示
智行/携程首页确有「会员/积分/我的订单」，但采集仍记 `login`。
到底是"我们误判"还是"搜索时才拦"？——不看清当时屏上是什么就只能猜。

本模块两件事：
1. `core.app_check`：用设备实况对账（首页判定 已登录 / 登录页 / 未判定），
   `--fix` 时只清**确属已登录**的过期登录墙记忆；
2. `app_base.path_note(status="login")` 时把界面 dump 落盘
   （`app_login_fail_<时间>_<路径>.xml`，只留最近 6 份）。

真机结论（携程 App）：一进搜索就弹「手机验证码登录 / 请输入手机号 / 获取验证码」
——**首页已登录 ≠ 搜索可用**，账本记 login 是对的。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import app_check as AC  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _xml(*texts):
    return "<hierarchy>" + "".join(
        '<node text="%s" />' % t for t in texts) + "</hierarchy>"


def test_classify_logged_in_by_markers():
    r = AC.classify(_xml("会员", "积分", "机票", "酒店"))
    assert r["state"] == "logged_in", r
    assert "会员" in r["in_markers"]


def test_classify_login_page_by_hard_markers():
    r = AC.classify(_xml("手机验证码登录", "请输入手机号", "获取验证码",
                         "账号密码登录"))
    assert r["state"] == "login_page", r
    assert r["hard"], "硬登录标记必须被识别（避免把登录页判成已登录）"


def test_classify_unknown_when_no_markers():
    assert AC.classify(_xml("首页", "搜索"))["state"] == "unknown"


def test_classify_empty():
    assert AC.classify("")["state"] == "empty"


def test_fix_wall_clears_file_and_memo(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    import json
    d = tmp_path / "app_ctrip"
    d.mkdir(parents=True, exist_ok=True)
    (d / "login_wall.json").write_text(
        json.dumps({"until": 9e9, "detail": "需登录"}), encoding="utf-8")
    assert AC.fix_wall(str(tmp_path), "app_ctrip") is True
    assert not (d / "login_wall.json").exists()


def test_snapshot_written_on_login_note():
    """记 login 时要落盘界面快照（否则只能猜是登录墙还是误判）。"""
    src = io.open(os.path.join(ROOT, "crawlers", "app_base.py"),
                  encoding="utf-8").read()
    assert "app_login_fail_" in src
    assert "_last_dev" in src, "取不到设备句柄就抓不到 dump"
    i = src.index("app_login_fail_")
    seg = src[max(0, i - 600):i + 400]
    assert "_all[:-6]" in src or "只留最近 6 份" in src, "快照必须有保留上限"
