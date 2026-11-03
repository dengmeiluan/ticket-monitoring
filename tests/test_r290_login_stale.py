# -*- coding: utf-8 -*-
"""登录态分层显示（r290 收尾用户立案）：「已有登录态」检测的是本地会话
档案（user_data/<plat> 目录非空），不等于会话当前被服务端承认——qunar 对
失效会话软性返回空列表（本地档案在而服务端会话死），配置页绿点「已有登
录态」与采集端「请重新登录」两词面同屏矛盾。

分层：采集端抓到「服务端按未登录处理」的证据时置 login_suspect 类级标记
（_cooldown_until 同款类级状态先例，实例每轮新建故必须类级），成功即清
（恢复自愈，重启复位=重启后无失效证据）；_login_state_view 上浮 stale
字段，前端三态词面「会话可能失效，建议重登」。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r290_login_stale.py
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture
def q_cls():
    from crawlers.qunar import QunarCrawler
    had = hasattr(QunarCrawler, "login_suspect")
    old = getattr(QunarCrawler, "login_suspect", None)
    old_gap, old_back = QunarCrawler._MIN_GAP_S, QunarCrawler._BACKOFF_S
    old_cd, old_done = QunarCrawler._cooldown_until, QunarCrawler._last_done_ts
    QunarCrawler._MIN_GAP_S = 0
    # (0,)：一轮零秒重试——() 会在置标记分支之前走「耗尽」短路，置标记
    # 路径不可达（测试构造须让生产分支真实可达，十九§16 死档判据投影）
    QunarCrawler._BACKOFF_S = (0,)
    QunarCrawler._cooldown_until = 0.0
    QunarCrawler._last_done_ts = 0.0
    yield QunarCrawler
    if had:
        QunarCrawler.login_suspect = old
    elif hasattr(QunarCrawler, "login_suspect"):
        delattr(QunarCrawler, "login_suspect")
    QunarCrawler._MIN_GAP_S, QunarCrawler._BACKOFF_S = old_gap, old_back
    QunarCrawler._cooldown_until, QunarCrawler._last_done_ts = old_cd, old_done


def test_qunar_sets_suspect_on_server_reject(q_cls, monkeypatch, tmp_path):
    """无认证 Cookie 证据 + 三路径空结果 → 置 login_suspect。

    r817 起「认证 Cookie 在场且探测在线」改判软空、不催重登；本用例
    用隔离空档案验证「确实没有登录证据」时仍会置失效标记。
    """
    q_cls._auth_probe_at = 0.0
    q_cls._auth_probe_ok = None
    c = q_cls({"user_data_dir": str(tmp_path)}, logging.getLogger("t290"))
    monkeypatch.setattr(c, "_fetch_one", lambda a, b, d: None)
    q_cls._BACKOFF_S = (0,)
    assert c.fetch("上海", "海口", ["2027-01-29"]) == []
    assert q_cls.login_suspect is True


def test_qunar_clears_suspect_on_hit(q_cls, monkeypatch):
    """任一路径重新拿到数据即清标记（恢复自愈），卡片退回「已有登录态」。"""
    q_cls.login_suspect = True
    c = q_cls({}, logging.getLogger("t290"))
    flights = [{"code": "CA8573", "name": "国航CA8573", "price": 1750.0,
                "depTime": "15:30", "arrTime": "18:55"}]
    monkeypatch.setattr(c, "_fetch_one", lambda a, b, d: (1750.0, flights))
    rows = c.fetch("上海", "海口", ["2027-01-29"])
    assert rows
    assert q_cls.login_suspect is False


def test_login_state_view_carries_stale(q_cls, tmp_path, monkeypatch):
    """_login_state_view 上浮 stale 字段并随类属性联动；saved 语义不变
    （本地档案在场）。档案目录用 tmp_path 构造（离线可跑，不依赖生产
    user_data）。"""
    import webui
    (tmp_path / "qunar").mkdir()
    (tmp_path / "qunar" / "marker").write_text("x", encoding="utf-8")
    # 直接注入配置解析结果：_State.cfg/boot_cfg 是进程级全局，同 worker
    # 前序用例遗留的后台线程会在断言窗口内重载它（CI xdist 实测
    # saved=False）。这里只钉 _login_state_view 对 user_data_dir 的语义。
    monkeypatch.setattr(webui, "_effective_crawler_config",
                        lambda: {"user_data_dir": str(tmp_path)})
    try:
        q_cls.login_suspect = False
        v = webui._login_state_view()
        assert v["plats"]["qunar"]["saved"] is True
        assert v["plats"]["qunar"]["stale"] is False
        q_cls.login_suspect = True
        v = webui._login_state_view()
        assert v["plats"]["qunar"]["saved"] is True
        assert v["plats"]["qunar"]["stale"] is True
    finally:
        q_cls.login_suspect = False


def test_login_stale_wording_in_page(q_cls):
    """前端三态词面源码钉：失效档词面在 PAGE；「已有登录态」词面保留
    （无失效证据时不变——档案在且无失效证据仍显示登录态）。"""
    import webui
    src = open(webui.__file__, encoding="utf-8").read()
    assert "会话需重新登录" in src, "失效档词面缺席"
    assert "已有登录态" in src, "常态档词面被误删"
