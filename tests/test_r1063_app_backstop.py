# -*- coding: utf-8 -*-
"""r1063 T202-T203：换道的**反方向**——App 被拦时由同名浏览器渠道反补。

背景：`core/failover.py` 原来只有 **浏览器→App**（行为型挑战换到 App 通路）。
可现实相反：App 侧被登录墙 / 50003 拦死，浏览器四家 96–100% 健康。
只订阅 App 的用户，App 一拦 → 那些航线整轮没数。

真机第一炮就打偏过（都写成用例钉住）：
```
[反补] app_qunar → qunar（登录墙未解）      ← qunar 永久停服，请求进黑洞还要占额度
（app_ctrip 没被反补）                      ← 它首页有会员，**搜索时**才弹登录，文件里没墙
```
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import failover as F  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_browser_counterpart_maps_and_rejects():
    assert F.browser_counterpart("app_ctrip") == "ctrip"
    assert F.browser_counterpart("app_fliggy") == "fliggy"
    assert F.browser_counterpart("ctrip") == ""      # 反函数只吃 App 名
    assert F.browser_counterpart("") == ""


def test_retired_target_is_refused(tmp_path, monkeypatch):
    """qunar 已永久停服：反补过去就是往黑洞里扔请求（真机第一炮的反例）。"""
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    app, why = F.plan_backstop("app_qunar", {}, user_data_dir=str(tmp_path),
                              blocked=True)
    assert app == "", why
    assert "停服" in why, why


def test_backstop_uses_injected_fact(tmp_path, monkeypatch):
    """注入 blocked=True 时必须反补（文件里没墙也要认）。"""
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    app, why = F.plan_backstop("app_ctrip", {}, user_data_dir=str(tmp_path),
                              blocked=True)
    assert app == "ctrip", why


def test_no_counterpart_for_zhixing(tmp_path, monkeypatch):
    """智行没有浏览器孪生 → 不反补（避免造一个不存在的目标）。"""
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    app, why = F.plan_backstop("app_zhixing", {}, user_data_dir=str(tmp_path),
                              blocked=True)
    assert app == "", why


def test_running_counterpart_not_duplicated(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    app, why = F.plan_backstop("app_ctrip", {}, user_data_dir=str(tmp_path),
                              blocked=True, running=("ctrip",))
    assert app == "", "浏览器通路本轮已在跑，不该再加一次"


def test_budget_and_cooldown(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    # 记满额度后必须拒绝
    for _ in range(8):
        F.note_switch("backstop:app_ctrip", "ctrip",
                      user_data_dir=str(tmp_path))
    app, why = F.plan_backstop("app_ctrip", {}, user_data_dir=str(tmp_path),
                              blocked=True)
    assert app == "", why


def test_main_wires_both_directions():
    src = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    assert "_backstop" in src, "main 没接反补"
    assert "plan_backstop" in src
    assert "_blk_map" in src, "必须用 pacing 真账判定被拦（文件里没墙也会被拦）"
