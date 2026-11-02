# -*- coding: utf-8 -*-
"""r339 观测立案修案：qunar 会话失效砍退避链。

r339c 数据观测立案 3（修）：未登录硬拒（软性空列表）走满 90/180/300
阶梯退避 + 4 轮浏览器抓取 ≈17 分钟，必触 900s 路由级栅栏（实录连续
~20 条「路由级超时(900s)」、单查询拖满栅栏是 14:38-17:00 段 ~5h 长链
主因）。硬拒=确定性拒绝——login_suspect 失效证据在案时重试注定同果
（登录态不会在退避窗内自愈），NOT_SUPPORT 同族律：绝不重试立即放弃；
无失效证据的空结果（疑似真限流）维持阶梯退避不变。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r339_qunar_backoff.py -q
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
    QunarCrawler._cooldown_until = 0.0
    QunarCrawler._last_done_ts = 0.0
    yield QunarCrawler
    if had:
        QunarCrawler.login_suspect = old
    elif hasattr(QunarCrawler, "login_suspect"):
        delattr(QunarCrawler, "login_suspect")
    QunarCrawler._MIN_GAP_S, QunarCrawler._BACKOFF_S = old_gap, old_back
    QunarCrawler._cooldown_until, QunarCrawler._last_done_ts = old_cd, old_done


def test_qunar_suspect_skips_backoff_chain(q_cls, monkeypatch):
    """login_suspect 在案 → 空结果单次放弃（不进 90/180/300 重试链）。"""
    calls = []

    def _empty(a, b, d):
        calls.append(1)
        return None

    c = q_cls({}, logging.getLogger("t339"))
    monkeypatch.setattr(c, "_fetch_one", _empty)
    q_cls.login_suspect = True
    q_cls._BACKOFF_S = (0, 0, 0)   # 三档全即时——未砍档则共试 4 次
    assert c.fetch("上海", "海口", ["2027-01-29"]) == []
    assert len(calls) == 1, f"失效证据在案仍重试 {len(calls)} 次"
    assert q_cls.login_suspect is True   # 失效证据不清（引导重登）


def test_qunar_suspect_hit_still_clears(q_cls, monkeypatch):
    """砍档不拦自愈路：失效证据在案但本轮出数 → 正常返回并清标记
    （r290 自愈语义不变；退避链能力随复位恢复——限流窗内下轮重新
    全链，砍档面仅限「证据在案的当轮重试」）。"""
    c = q_cls({}, logging.getLogger("t339"))
    flights = [{"code": "CA8573", "name": "国航CA8573", "price": 1750.0,
                "depTime": "15:30", "arrTime": "18:55"}]
    monkeypatch.setattr(c, "_fetch_one", lambda a, b, d: (1750.0, flights))
    q_cls.login_suspect = True
    out = c.fetch("上海", "海口", ["2027-01-29"])
    assert out and q_cls.login_suspect is False, out


def test_qunar_backoff_config_intact():
    """阶梯退避配置本体不拆（限流形态的退避能力保留面）——砍档门
    只在失效证据在案时旁路，不清配置不设冷却。源码钉形态：类属性
    断言受跨文件测试状态链影响（运行态脆钉），配置本体锁源码字面。"""
    mod = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "crawlers", "qunar.py"), encoding="utf-8").read()
    assert "_BACKOFF_S = (90, 180, 300)" in mod


def test_intl_login_reject_no_cooldown_sleep():
    """intl 1999 硬拒不设 30min 冷却（r339 观测轮 2 定谳：cooldown
    sleep 在 worker 线程内同步等 1776s=错峰等待即栅栏内泊车，每查询
    吃满 900s 路由栅栏实录 8 条/日——r330「等待不应在栅栏内」同律）。
    硬拒面由砍退避门+调度承接，源码钉锁断路器词面退场防回潮。"""
    mod = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "crawlers", "qunar.py"), encoding="utf-8").read()
    assert "_cooldown_until = _t.time() + 1800" not in mod
    assert "已断路 30 分钟" not in mod
