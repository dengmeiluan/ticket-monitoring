# -*- coding: utf-8 -*-
"""r271 推送落地案（主修立案：停用态走势日志噪音 + 失败词面两因合并）：

停用态（全部航线 enabled: false）下每扫描轮 build_and_push 空转，
「暂无可画数据或所选图床无可用通路（provider=ghimg），本报告未发」
以 WARNING 级每轮刷屏（实录 10-08 起 104 条持续增长）。两因合一词面：
「配置面预期（用户停用/未配航线）」与「异常面（有启用航线但渲染/上
传失败）」混同一句——观测轮曾被该词面误导定性为「图床断路」（实际
ghimg 通路零失败记录，upload_ghimg 失败必留 [图床] WARNING 而日志
零命中）。修法：charts 空时按「启用航线数」二分——零启用航线=配置
面预期，INFO 归静默（停摆类警报先核启停态判例的生产日志面投影）；
有启用航线而零图才是真异常，保留 WARNING 原词面。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r271_push.py -q
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import report  # noqa: E402


def _cfg(enabled):
    route = {"from": "URC", "from_name": "乌鲁木齐", "to": "SHA",
             "to_name": "上海", "dates": ["2026-10-15"],
             "alert_direct": 1900, "alert_transfer": 1700,
             "enabled": enabled}
    return {
        "notifier": {"image_host": {"provider": "ghimg", "repo": "o/r",
                                    "token": "t"}},
        "users": [{"name": "u1", "routes": [route],
                   "platforms": ["qunar"]}],
    }


class _Notif(object):
    last_errcode = None


@pytest.fixture()
def empty_charts(monkeypatch):
    monkeypatch.setattr(report, "prepare_round_charts",
                        lambda *a, **k: {})


def _warns(caplog):
    return [r.getMessage() for r in caplog.records
            if r.levelno >= logging.WARNING]


def _infos(caplog):
    return [r.getMessage() for r in caplog.records
            if r.levelno == logging.INFO]


def test_suspended_routes_info_not_warning(caplog, empty_charts):
    caplog.set_level(logging.DEBUG)
    ok = report.build_and_push(
        _cfg(False), logging.getLogger("t"), _Notif(), user="u1")
    assert ok is False
    assert not any("暂无可画数据" in m for m in _warns(caplog)), \
        _warns(caplog)
    assert any("停用" in m for m in _infos(caplog)), _infos(caplog)


def test_active_routes_empty_charts_keeps_warning(caplog, empty_charts):
    caplog.set_level(logging.DEBUG)
    ok = report.build_and_push(
        _cfg(True), logging.getLogger("t"), _Notif(), user="u1")
    assert ok is False
    assert any("暂无可画数据" in m for m in _warns(caplog)), _warns(caplog)


def test_enabled_routes_single_source():
    # 单源钉：裸「enabled is not False」口径只许 helper 定义处 1 次，
    # 消费点（出图遍历/日报查价入口/空图归因）一律走 _enabled_routes
    src = open("report.py", encoding="utf-8").read()
    assert src.count('enabled") is not False') == 1, \
        "裸启用口径残留（绕过 _enabled_routes 单源）"
    assert src.count("def _enabled_routes") == 1
    # 消费 4 处：_chart_routes 出图遍历 / prepare_round_charts user 分支 /
    # 日报 _fr 查价入口 / build_and_push 空图归因，+定义处 1 = 5
    assert src.count("_enabled_routes(") == 5, "helper 消费点数量漂移"


# ---- 落地案2：总表空态归因词面按真约束成分拼装（推送审校 P3-①） ----

def test_transfer_empty_note_no_layover_no_zero_word():
    # 未配置衔接下限（lay_min=0）不出「衔接≥0 分钟」负信息段，
    # 到达约束在场时只归因到达段
    from report import _transfer_empty_note as note
    got = note(0, "02:00")
    assert "衔接" not in got, got
    assert got == "暂无满足约束的班次（02:00 前到达）", got


def test_transfer_empty_note_full_form_unchanged():
    # 双约束在场与「衔接+缺省到达兜底」两档与旧词面全等（零回归面）
    from report import _transfer_empty_note as note
    assert note(90, "02:00") == \
        "暂无满足约束的班次（衔接≥90 分钟·02:00 前到达）"
    assert note(90, "") == \
        "暂无满足约束的班次（衔接≥90 分钟·次日 02:00 前到达）"


def test_transfer_empty_note_no_constraint():
    # 双约束皆缺省归因渠道未回数（原语义不动）
    from report import _transfer_empty_note as note
    assert note(0, "") == "暂无数据（该轮渠道未回中转班次，下轮自动补上）"


def test_transfer_empty_note_single_source():
    # 渲染点消费纯函数：「衔接≥」模板只许纯函数定义处 1 次
    src = open("report.py", encoding="utf-8").read()
    assert src.count("衔接≥%d 分钟") == 1, "空态归因模板残留（绕过纯函数）"
