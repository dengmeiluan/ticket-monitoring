# -*- coding: utf-8 -*-
"""认证证据与历史采集结果分开：固定日志、固定时钟，不访问运行资料。"""
import pytest

from core.health import parse_health


NOW = "2026-10-22 12:00:00"


def _line(at, message, level="INFO"):
    return f"{at} [{level}] test-health: {message}"


def _parse(*lines, hours=24):
    return parse_health("\n".join(lines), now=NOW, hours=hours)


@pytest.mark.parametrize("reason", [
    "会话门拒（code=444 非法链接，body 55B）——请重登 tongcheng",
    "非法链接（code=444）",
    "会话门拒（签名或入口校验失败）",
    "请求环境拒绝（code=444 签名校验失败，body 55B）",
])
def test_business_gate_failure_does_not_claim_authentication_failure(reason):
    out = _parse(_line("2026-10-22 10:00:17",
                       "[tongcheng][intl] 2026-11-16 " + reason, "WARNING"))
    row = out["rounds"][0]["plats"]["tongcheng"]
    assert row["s"] == "fail"
    assert row["tot"] == 1
    assert row["need_login"] is False
    assert out["stats"]["tongcheng"]["auth"] == 0
    assert "重登" not in row["note"]
    assert not out.get("evidence", {}).get("tongcheng")


def test_explicit_auth_failure_records_event_time_and_safe_reason():
    out = _parse(
        _line("2026-10-22 10:00:00", "===== 开始一轮扫描 ====="),
        _line("2026-10-22 10:05:17", "[qunar][intl] 2026-11-16 "
              "未登录硬拒（1999/8） private-response=do-not-expose", "WARNING"),
        _line("2026-10-22 10:06:00", "===== 本轮扫描结束 ====="),
    )
    assert out["rounds"][0]["ts"] == "2026-10-22 10:00"
    assert out["rounds"][0]["plats"]["qunar"]["need_login"] is True
    assert out.get("evidence", {}) == {
        "qunar": {"international": {
            "auth_at": "2026-10-22 10:05:17", "detail_at": "",
            "auth_reason": "未登录硬拒",
        }},
    }


def test_calendar_success_keeps_auth_evidence_without_detail_verification():
    out = _parse(
        _line("2026-10-22 10:05:17", "[ctrip][intl] 需登录 · 国际列表需携程会话"),
        _line("2026-10-22 10:06:18", "[ctrip][intl] 2026-11-16 "
              "日历最低含税价 ￥719（1 行）"),
    )
    evidence = out.get("evidence", {}).get("ctrip", {}).get("international", {})
    assert evidence.get("auth_at") == "2026-10-22 10:05:17"
    assert evidence.get("detail_at") == ""
    assert out["rounds"][0]["plats"]["ctrip"]["cal"] == 1
    assert out["rounds"][0]["plats"]["ctrip"]["detail"] == 0


@pytest.mark.parametrize(("scope_text", "scope"), [
    ("[intl] ", "international"),
    ("[international] ", "international"),
    ("[国际] ", "international"),
    ("国际航线 ", "international"),
    ("[domestic] ", "domestic"),
    ("[国内] ", "domestic"),
    ("国内航线 ", "domestic"),
    ("", "unknown"),
])
def test_evidence_scope_requires_explicit_scope(scope_text, scope):
    out = _parse(_line("2026-10-22 10:00:31", "[qunar]" + scope_text
                       + "2026-11-16 最低价 ￥1526（航班明细 70 条）"))
    assert out.get("evidence", {}) == {"qunar": {scope: {
        "auth_at": "", "detail_at": "2026-10-22 10:00:31", "auth_reason": "",
    }}}


def test_airport_name_is_not_international_scope_evidence():
    out = _parse(_line("2026-10-22 10:00:31", "[qunar] 2026-11-16 "
                       "最低价 ￥1526（航班明细 70 条） 国际机场出发"))
    assert "unknown" in out.get("evidence", {}).get("qunar", {})


def test_latest_evidence_is_kept_per_platform_across_rounds():
    out = _parse(
        _line("2026-10-22 09:00:00", "===== 开始一轮扫描 ====="),
        _line("2026-10-22 09:01:12", "[qunar][intl] 未登录硬拒（1999/8）"),
        _line("2026-10-22 09:02:00", "===== 本轮扫描结束 ====="),
        _line("2026-10-22 10:00:00", "===== 开始一轮扫描 ====="),
        _line("2026-10-22 10:01:23", "[ctrip][intl] 需登录 · PC 列表需携程会话"),
        _line("2026-10-22 10:02:00", "===== 本轮扫描结束 ====="),
    )
    evidence = out.get("evidence", {})
    assert evidence.get("qunar", {}).get("international", {}).get("auth_at") == (
        "2026-10-22 09:01:12")
    assert evidence.get("ctrip", {}).get("international", {}).get("auth_at") == (
        "2026-10-22 10:01:23")
    assert "qunar" not in out["rounds"][-1]["plats"]


def test_domestic_detail_does_not_overwrite_international_auth_evidence():
    out = _parse(
        _line("2026-10-22 10:01:12", "[qunar][intl] 未登录硬拒（1999/8）"),
        _line("2026-10-22 10:02:23", "[qunar][domestic] 2026-11-16 "
              "最低价 ￥1526（航班明细 70 条）"),
    )
    evidence = out.get("evidence", {}).get("qunar", {})
    assert evidence.get("international", {}).get("auth_at") == "2026-10-22 10:01:12"
    assert evidence.get("international", {}).get("detail_at") == ""
    assert evidence.get("domestic", {}).get("detail_at") == "2026-10-22 10:02:23"
    assert evidence.get("domestic", {}).get("auth_at") == ""


def test_latest_evidence_uses_event_time_not_line_order():
    out = _parse(
        _line("2026-10-22 10:03:12", "[qunar][intl] 未登录硬拒（1999/8）"),
        _line("2026-10-22 10:04:23", "[qunar][intl] 2026-11-16 "
              "最低含税价 ￥1526（航班明细 70 条）"),
        _line("2026-10-22 10:01:00", "[qunar][intl] 需登录"),
        _line("2026-10-22 10:02:00", "[qunar][intl] 2026-11-16 "
              "最低含税价 ￥1526（航班明细 70 条）"),
    )
    assert out.get("evidence", {}).get("qunar", {}).get("international") == {
        "auth_at": "2026-10-22 10:03:12", "detail_at": "2026-10-22 10:04:23",
        "auth_reason": "未登录硬拒",
    }


def test_evidence_window_uses_event_time_even_when_round_started_before_cutoff():
    out = _parse(
        _line("2026-10-22 09:59:59", "===== 开始一轮扫描 ====="),
        _line("2026-10-22 09:59:59", "[qunar][intl] 未登录硬拒（1999/8）"),
        _line("2026-10-22 10:00:00", "[ctrip][intl] 需登录"),
        _line("2026-10-22 12:00:01", "[tuniu][intl] 需登录"),
        hours=2,
    )
    assert set(out.get("evidence", {})) == {"ctrip"}
    assert out["rounds"] == []  # 历史轮次仍按原有轮开始时间截窗。


@pytest.mark.parametrize("price_text", [
    "最低价 ￥719", "最低价 ￥719（明细 0 条）",
    "日历最低含税价 ￥719（1 行）",
])
def test_price_without_positive_flight_details_is_not_detail_evidence(price_text):
    out = _parse(_line("2026-10-22 10:00:31", "[qunar][intl] 2026-11-16 "
                       + price_text))
    assert out["rounds"][0]["plats"]["qunar"]["ok"] == 1
    assert out.get("evidence", {}) == {}
