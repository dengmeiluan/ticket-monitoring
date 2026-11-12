# -*- coding: utf-8 -*-
"""App 渠道 cadence（每渠道最小采集间隔）：少启动 = 少自动化痕迹。

2026-11-06 实测：App 渠道一天被启动 **73 次**（07 时一小时 24 次）。
每次启动 = 打开 App + 导航 + 读页面，是最强的自动化指纹，也是
"越跑越容易被风控"的直接来源。数据本身（3 个月后的航线）变化很慢，
所以给 180 分钟的硬地板既不丢新鲜度，又能把启动次数降一个数量级。
"""
import time

from core.channels import APP_CHANNELS
from core.pacing import Pacing, parse_pacing


KEY = ("SHA", "PEK", "2026-11-16")


def _pac(floor=180):
    cad = {p: floor for p in APP_CHANNELS}
    return Pacing({"crawler": {"cadence": cad}})


def test_app_channel_skipped_within_cadence():
    now = time.time()
    pac = _pac(180)
    pac.seed_fetch("app_ctrip", KEY, 727.0, at_ts=now - 60 * 60)  # 1 小时前
    tier, why = pac.plan_query("app_ctrip", KEY, 0, days_ahead=10)
    assert tier == "skip", (tier, why)
    assert "渠道节奏" in why, why


def test_app_channel_runs_after_cadence():
    now = time.time()
    pac = _pac(180)
    pac.seed_fetch("app_ctrip", KEY, 727.0, at_ts=now - 181 * 60)
    tier, why = pac.plan_query("app_ctrip", KEY, 0, days_ahead=10)
    assert tier != "skip", (tier, why)


def test_cadence_zero_means_follow_global_ttl():
    now = time.time()
    pac = _pac(0)
    pac.seed_fetch("app_ctrip", KEY, 727.0, at_ts=now - 60 * 60)
    tier, _why = pac.plan_query("app_ctrip", KEY, 0, days_ahead=10)
    assert tier != "skip"


def test_first_run_has_no_baseline_and_runs():
    """没有历史基线时必须跑——cadence 不能把新渠道永久挡在门外。"""
    pac = _pac(180)
    tier, why = pac.plan_query("app_zhixing", KEY, 0, days_ahead=10)
    assert tier != "skip", (tier, why)
    assert "无历史基线" in why


def test_parse_covers_all_app_channels():
    """每个 App 渠道都要有 key：缺 key 会让调度层退化成"无节奏"。"""
    parsed = parse_pacing({"crawler": {"cadence": dict.fromkeys(
        APP_CHANNELS, 180)}})
    for p in APP_CHANNELS:
        assert parsed["cadence"].get(p) == 180, p


def test_yaml_later_key_wins_trap(monkeypatch):
    """回归我 2026-11-06 踩的坑：config.yaml 里若同时出现 `cadence: {}` 和
    一个完整的 cadence 块，YAML 是**后者胜出**——写在前面等于没写。
    这条不测 yaml 行为本身，而是钉住「解析结果必须来自唯一的 cadence 键」。
    """
    import yaml
    doc = "crawler:\n  cadence: {}\n  cadence:\n    app_ctrip: 180\n"
    parsed = parse_pacing(yaml.safe_load(doc))
    assert parsed["cadence"]["app_ctrip"] == 180
