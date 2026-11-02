# -*- coding: utf-8 -*-
"""采集节流/熔断内核契约测试（1–5 区）。

这些断言先于实现写成（红）：静默窗、分层 TTL、熔断阶梯、令牌桶、
错峰偏移、失败归类。任何一条变红都意味着「降负荷」承诺失效。
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pacing import (  # noqa: E402
    ChannelBreaker, Pacing, TokenBucket, classify_failure, in_window,
    parse_hhmm, parse_pacing, parse_retry_after, stagger_offset, tier_of,
)


# ---------- 静默窗（1 区） ----------
def test_parse_hhmm_accepts_hh_mm_only():
    assert parse_hhmm("01:00") == 60
    assert parse_hhmm("7:05") == 425
    assert parse_hhmm("23:59") == 1439
    assert parse_hhmm("") is None
    assert parse_hhmm("24:00") is None
    assert parse_hhmm("01:60") is None
    assert parse_hhmm("abc") is None


def test_in_window_handles_cross_midnight_and_off():
    assert in_window(90, 60, 180) is True
    assert in_window(59, 60, 180) is False
    assert in_window(180, 60, 180) is False            # 右开
    assert in_window(23 * 60 + 30, 23 * 60, 7 * 60) is True
    assert in_window(6 * 60 + 59, 23 * 60, 7 * 60) is True
    assert in_window(7 * 60, 23 * 60, 7 * 60) is False
    assert in_window(12 * 60, 23 * 60, 7 * 60) is False
    assert in_window(100, None, 200) is False          # 未配置=关闭
    assert in_window(100, 100, 100) is False           # 起止相同=关闭


# ---------- 分层 TTL（3 区） ----------
def test_tier_of_skips_until_ttl_expires():
    assert tier_of(0, True, 30, 120) == "skip"
    assert tier_of(29.9, True, 30, 120) == "skip"
    assert tier_of(30, True, 30, 120) == "fast"
    assert tier_of(60, False, 30, 120) == "skip"
    assert tier_of(120, False, 30, 120) == "slow"


# ---------- 错峰（5 区） ----------
def test_stagger_offset_is_deterministic_and_spread():
    assert stagger_offset("qunar", 0) == 0
    vals = [stagger_offset(p, 25) for p in
            ("qunar", "fliggy", "ctrip", "tongcheng", "tuniu")]
    assert all(0 <= v < 25 for v in vals)
    assert len(set(vals)) == 5
    assert stagger_offset("qunar", 25) == vals[0]


# ---------- 失败归类（2 区） ----------
def test_classify_failure_separates_ip_captcha_login_infra():
    assert classify_failure(["blocked"], "") == "captcha"
    assert classify_failure([], "179991 触发IP风控") == "ip"
    assert classify_failure([], "429 Too Many Requests") == "ip"
    assert classify_failure(["login"], "") == "login"
    assert classify_failure(["timeout"], "请求超时") == ""
    assert classify_failure(["ok"], "") == ""
    assert classify_failure(["parse_error"], "未解析到价格") == ""
    # 价格里的 1403 不是 HTTP 403；「协议未验证」不是人机验证
    assert classify_failure([], "最低价 ￥1403（含税）") == ""
    assert classify_failure([], "航班列表协议未验证；仅观察官方入口") == ""


# ---------- 熔断阶梯（2 区） ----------
def test_breaker_backs_off_exponentially_then_caps():
    b = ChannelBreaker(base_s=300, cap_s=3600)
    assert b.allow("qunar", now=0)[0] is True
    assert b.trip("qunar", "ip", now=0) == 300
    ok, remain = b.allow("qunar", now=0)
    assert ok is False and 299 <= remain <= 300
    assert b.trip("qunar", "ip", now=100) == 600
    assert b.trip("qunar", "ip", now=200) == 1200
    assert b.trip("qunar", "ip", now=300) == 2400
    assert b.trip("qunar", "ip", now=400) == 3600
    assert b.trip("qunar", "ip", now=500) == 3600      # 封顶不溢出
    b.reset("qunar")
    assert b.allow("qunar", now=501)[0] is True
    assert b.trip("qunar", "ip", now=502) == 300       # 复位后重新起步


def test_breaker_busy_never_cools_down():
    b = ChannelBreaker(base_s=300, cap_s=3600)
    assert b.trip("tuniu", "busy", now=0) == 0
    assert b.allow("tuniu", now=1)[0] is True
    assert b.snapshot(now=1)["tuniu"]["strikes"] == 0


def test_breaker_login_is_flat_and_flagged():
    b = ChannelBreaker(base_s=300, cap_s=3600)
    assert b.trip("ctrip", "login", now=0) == 900
    snap = b.snapshot(now=0)["ctrip"]
    assert snap["state"] == "cooldown"
    assert snap["needs_login"] is True
    assert snap["strikes"] == 0


# ---------- 令牌桶（5 区） ----------
def test_token_bucket_min_gap():
    t = TokenBucket(min_gap_s=3, per_minute=0)
    assert t.wait_hint("qunar", now=0) == 0
    t.record("qunar", now=0)
    assert t.wait_hint("qunar", now=1) == 2
    assert t.wait_hint("qunar", now=3) == 0
    assert t.wait_hint("ctrip", now=3) == 0            # 渠道间互不影响


def test_token_bucket_per_minute_window():
    t = TokenBucket(min_gap_s=0, per_minute=2)
    t.record("x", now=0)
    t.record("x", now=10)
    assert 48 <= t.wait_hint("x", now=11) <= 50
    assert t.wait_hint("x", now=61) == 0


# ---------- Pacing 聚合 ----------
def _pace(cfg=None, now=None):
    """可控时钟：now 是单元素列表，测试里手动推进。"""
    return Pacing(cfg or {}, clock=lambda: now[0])


def test_plan_query_uses_distance_to_threshold():
    now = [1000.0]
    p = _pace({"schedule": {"fast_ttl_min": 30, "slow_ttl_min": 120,
                            "near_ratio": 0.15}}, now)
    near = ("qunar", "SHA", "NRT", "2026-11-16")
    far = ("qunar", "SHA", "LHR", "2026-11-16")
    assert p.plan_query("qunar", near, 2500)[0] == "fast"    # 无历史先取基线
    p.note_fetch("qunar", near, 2400, ok=True)               # 距阈值 4%
    assert p.plan_query("qunar", near, 2500)[0] == "skip"
    p.note_fetch("qunar", far, 9000, ok=True)                # 远高于阈值
    assert p.plan_query("qunar", far, 2500)[0] == "skip"
    now[0] += 31 * 60
    assert p.plan_query("qunar", near, 2500)[0] == "fast"
    assert p.plan_query("qunar", far, 2500)[0] == "skip"
    now[0] += 90 * 60
    assert p.plan_query("qunar", far, 2500)[0] == "slow"


def test_plan_query_without_threshold_stays_fast():
    now = [1000.0]
    p = _pace({}, now)
    key = ("qunar", "SHA", "BKK", "2026-11-16")
    p.note_fetch("qunar", key, 800, ok=True)
    assert p.plan_query("qunar", key, 0)[0] == "skip"
    now[0] += 31 * 60
    assert p.plan_query("qunar", key, 0)[0] == "fast"


def test_observe_trips_only_on_real_rejection():
    p = Pacing({})
    p.observe("qunar", statuses=["blocked"], note="")
    assert p.snapshot()["channels"]["qunar"]["state"] == "cooldown"
    p2 = Pacing({})
    p2.observe("qunar", statuses=["ok"], note="")
    assert p2.snapshot()["channels"]["qunar"]["state"] == "ok"
    p3 = Pacing({})
    p3.observe("qunar", statuses=["timeout"], note="请求超时")
    assert p3.snapshot()["channels"]["qunar"]["state"] == "ok"


def test_quiet_window_uses_local_clock():
    ts = datetime(2026, 10, 25, 2, 0).timestamp()
    p = _pace({"schedule": {"scan_quiet_start": "01:00",
                            "scan_quiet_end": "07:00"}}, [ts])
    assert p.quiet_now() is True
    assert p.snapshot()["quiet"]["active"] is True
    p2 = _pace({"schedule": {"scan_quiet_start": "01:00",
                             "scan_quiet_end": "07:00"}},
               [datetime(2026, 10, 25, 12, 0).timestamp()])
    assert p2.quiet_now() is False


def test_snapshot_shape_and_hot_refresh():
    p = Pacing({"schedule": {"fast_ttl_min": 30}})
    snap = p.snapshot()
    for key in ("cfg", "quiet", "channels", "bucket", "last_round"):
        assert key in snap
    p.trip("qunar", "ip")
    p.refresh({"schedule": {"fast_ttl_min": 45, "fast_ttl_min_note": ""}})
    assert p.cfg["fast_ttl_min"] == 45
    assert p.snapshot()["channels"]["qunar"]["state"] == "cooldown"  # 热改不清状态


def test_parse_pacing_clamps_and_defaults():
    d = parse_pacing({})
    assert d["fast_ttl_min"] == 15 and d["slow_ttl_min"] == 120
    assert d["breaker_enabled"] is True and d["near_ratio"] == 0.15
    d = parse_pacing({"schedule": {"fast_ttl_min": 999999,
                                   "near_ratio": 5},
                      "crawler": {"rate": {"min_gap_s": -3},
                                  "breaker": {"base_s": 1,
                                              "cap_s": 10}}})
    assert d["fast_ttl_min"] == 1440
    assert d["near_ratio"] == 1.0
    assert d["min_gap_s"] == 0
    assert d["breaker_base_s"] >= 30 and d["breaker_cap_s"] >= 120


# ---------- Retry-After：服务端说要等多久，就等多久 ----------
def test_parse_retry_after_seconds_and_date():
    assert parse_retry_after("120") == 120
    assert parse_retry_after(" 120 ") == 120
    assert parse_retry_after("0") == 0
    assert parse_retry_after("-5") == 0
    assert parse_retry_after("") == 0
    assert parse_retry_after("abc") == 0
    assert parse_retry_after("120.2") == 121          # 向上取整，宁晚不早
    assert parse_retry_after("999999") == 86400       # 封顶一天
    # HTTP-date 形态（相对 now 计算，过去的日期=0）
    now = 1_700_000_000.0
    assert parse_retry_after("Tue, 14 Nov 2023 22:15:20 GMT", now=now) == 120
    assert parse_retry_after("Tue, 14 Nov 2023 22:00:00 GMT", now=now) == 0


def test_breaker_prefers_server_retry_after():
    b = ChannelBreaker(base_s=300, cap_s=3600)
    # 服务端说 20 分钟 → 按它来，即使超过自算封顶 1 小时
    assert b.trip("qunar", "ip", now=0, retry_after=1200) == 1200
    b.reset("qunar")
    # 服务端说的比阶梯短 → 取较长的那个（不提前回来）
    assert b.trip("qunar", "ip", now=0, retry_after=60) == 300
    b.reset("qunar")
    assert b.trip("qunar", "ip", now=0, retry_after=99999) == 86400


def test_observe_passes_retry_after_through():
    p = Pacing({})
    kind, cd = p.observe("qunar", statuses=[], note="429 Too Many",
                         retry_after=600)
    assert kind == "ip" and cd == 600
    snap = p.snapshot()
    assert snap["channels"]["qunar"]["remain_s"] > 500
    assert snap["last_round"]["trips"][0]["retry_after"] == 600


# ---------- 建议引擎：告诉用户「等」还是「动手」 ----------
def test_advise_wait_vs_intervene():
    from core.pacing import advise
    a = advise("qunar", {"state": "cooldown", "remain_s": 300}, {})
    assert a["action"] == "wait" and a["eta_s"] == 300
    assert a["severity"] == "wait"
    b = advise("qunar", {"needs_login": True}, {})
    assert b["action"] == "relogin" and b["severity"] == "act"
    c = advise("ctrip", {"state": "ok"},
               {"H5": {"attempts": 10, "ok": 1, "rate": 0.1},
                "PC": {"attempts": 10, "ok": 9, "rate": 0.9}})
    assert c["action"] == "route" and "H5" in c["hint"]
    d = advise("fliggy", {"state": "ok"}, {})
    assert d["action"] == "scan"
    e = advise("tuniu", {"state": "ok"},
               {"H5": {"attempts": 10, "ok": 9, "rate": 0.9}})
    assert e["action"] == "none" and e["severity"] == "ok"
    # 样本太少不做路径结论（<5 次）
    f = advise("tuniu", {"state": "ok"},
               {"H5": {"attempts": 3, "ok": 0, "rate": 0.0}})
    assert f["action"] == "watch"


def test_health_penalty_slows_poor_channel():
    now = [1000.0]
    p = _pace({}, now)
    key = ("qunar", "SHA", "NRT", "2026-11-16")
    p.note_fetch("qunar", key, 2400, ok=True)
    now[0] += 16 * 60                       # fast_ttl 默认 15 → 已到期
    assert p.plan_query("qunar", key, 2500)[0] == "fast"
    p.set_health("qunar", 0.2, 20)          # 成功率 20% → ×3
    assert p.snapshot()["channels"]["qunar"]["health"]["penalty"] == 3.0
    assert p.plan_query("qunar", key, 2500)[0] == "skip"
    p.set_health("qunar", 0.55, 20)         # 0.4–0.7 → ×1.5（22.5 分钟）
    now[0] += 8 * 60                        # 累计 24 分钟 > 22.5
    assert p.plan_query("qunar", key, 2500)[0] == "fast"
    p.set_health("qunar", 0.9, 20)          # 健康 → ×1 不惩罚
    assert p.snapshot()["channels"]["qunar"]["health"]["penalty"] == 1.0
    p.set_health("qunar", 0.0, 3)           # 样本不足不降频
    assert p.snapshot()["channels"]["qunar"]["health"]["penalty"] == 1.0


def test_advise_flags_stale_data():
    import time as _t
    from core.pacing import advise
    now = 1_700_000_000.0
    old = _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(now - 300 * 60))
    fresh = _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(now - 5 * 60))
    a = advise("qunar", {"state": "ok"},
               {"H5": {"attempts": 10, "ok": 9, "rate": 0.9,
                       "last_at": old}}, now=now)
    assert a["state"] == "stale" and a["action"] == "probe"
    b = advise("qunar", {"state": "ok"},
               {"H5": {"attempts": 10, "ok": 9, "rate": 0.9,
                       "last_at": fresh}}, now=now)
    assert b["action"] == "none"


def test_cadence_is_a_hard_floor_per_channel():
    now = [1000.0]
    p = _pace({"crawler": {"cadence": {"qunar": 60}}}, now)
    key = ("qunar", "SHA", "NRT", "2026-11-16")
    p.note_fetch("qunar", key, 2400, ok=True)
    now[0] += 31 * 60            # 全局 fast_ttl 15 已过，但渠道地板 60 未到
    tier, why = p.plan_query("qunar", key, 2500)
    assert tier == "skip" and "渠道节奏" in why
    now[0] += 30 * 60            # 累计 61 分钟
    assert p.plan_query("qunar", key, 2500)[0] == "fast"
    # 未配置的渠道不受影响
    assert p.cfg["cadence"].get("ctrip") == 0
