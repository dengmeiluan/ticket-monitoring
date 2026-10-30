# -*- coding: utf-8 -*-
"""Evidence-first diagnosis: no absent round is green; empty != login."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.health import parse_health  # noqa: E402
from core.health_diag import classify_round  # noqa: E402


def _line(at, message):
    return f"{at} [INFO] test-health: {message}"


def test_parser_keeps_long_markers_and_empty_is_not_failure():
    log = "\n".join([
        _line("2026-10-24 10:00:00", "===== 开始一轮扫描 ====="),
        _line("2026-10-24 10:01:00", "[ctrip] 2026-11-16 最低价 ￥500"),
        _line("2026-10-24 10:01:10", "[ctrip] 2026-11-17 未解析到价格"),
        _line("2026-10-24 10:01:20",
              "[tuniu] 请求异常 " + "远程服务返回异常 " * 4
              + "179991 触发IP风控，出口被限流，停止重试"),
        _line("2026-10-24 10:01:30",
              "[qunar] 1999 没有查询到符合条件的航班"),
        _line("2026-10-24 10:02:00", "===== 本轮扫描结束 ====="),
    ])
    out = parse_health(log, now="2026-10-24 12:00:00")
    p = out["rounds"][0]["plats"]
    assert p["ctrip"]["s"] == "part"
    assert "179991" in p["tuniu"]["note"] and len(p["tuniu"]["note"]) > 40
    assert p["qunar"]["s"] == "empty"
    assert out["stats"]["qunar"]["empty"] == 1
    assert out["stats"]["qunar"]["fail"] == 0


def test_classifier_covers_ip_empty_partial_captcha_cookie():
    rounds = {
        "tuniu": {"s": "fail", "ok": 0, "tot": 1,
                  "note": "179991 触发IP风控"},
        "qunar": {"s": "empty", "ok": 0, "tot": 0,
                  "note": "没有查询到符合条件的航班"},
        "ctrip": {"s": "part", "ok": 2, "tot": 3, "detail": 2,
                  "note": "部分日期查询失败（2/3 成功）"},
        "fliggy": {"s": "fail", "ok": 0, "tot": 1,
                   "note": "出现滑块验证码"},
    }
    cards = {c["plat"]: c for c in classify_round(
        rounds, cookie={"tongcheng": "expired"})}
    assert cards["tuniu"]["kind"] == "ip"
    assert cards["qunar"]["kind"] == "empty"
    assert cards["ctrip"]["kind"] == "partial"
    assert cards["fliggy"]["kind"] == "captcha"
    assert cards["tongcheng"]["kind"] == "cookie_expired"
    assert "unscanned" not in {c["kind"] for c in cards.values()}


def test_absent_round_is_unscanned_and_ok_requires_detail():
    cards = {c["plat"]: c for c in classify_round({
        "ctrip": {"s": "ok", "ok": 1, "tot": 1, "detail": 3, "cal": 0},
    })}
    assert cards["ctrip"]["kind"] == "ok"
    assert cards["qunar"]["kind"] == "unscanned"
    cards = {c["plat"]: c for c in classify_round({
        "ctrip": {"s": "ok", "ok": 1, "tot": 1, "detail": 0, "cal": 3},
    })}
    assert cards["ctrip"]["kind"] == "calendar_only"


def test_login_and_1999_login_wall():
    cards = {c["plat"]: c for c in classify_round({
        "qunar": {"s": "fail", "ok": 0, "tot": 1,
                  "note": "1999 登录墙，请登录"},
    })}
    assert cards["qunar"]["kind"] == "login"
