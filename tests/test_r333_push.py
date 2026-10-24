# -*- coding: utf-8 -*-
"""r333 推送 P2-1（TDD 先行，审校报告 _scratch/worker_r333_push.md）：

日历最低价行（渠道日历聚合价：无航班号、dep/arr 时刻双空）流入
TOP5/渠道行情兜底文本时，「→ 当日达」假时刻骨架直出——r332 悬垂
箭头守卫（5edab95）只收口 KPI 行2+hits seg 两处，_fmt_flight_line/
_fmt_brief 零守卫漏网（同病姊妹收口不彻底，三十§3 镜像路径同轮
盘点漏了文本兜底族）。生产真实行 8/8 直调实证，最坏形态（5 位价）
宽 40 恰卡预算零降级；图挂兜底路径生产实发 16 轮可达。

修法（与 alerter:2580 判据同律）：时刻双空行箭头段与「当日达」
尾注整段缺席，名字+价格判据保留；有时刻行逐字不变。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r333_push.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

from core.alerter import Alerter  # noqa: E402


def _cal_row(**over):
    """生产日历最低价行真实形态（webui /api/state best 直飞=日历最低价
    实锤；dep/arr 空、无 code、stopover/transCity 全缺省）。"""
    row = {"_platform": "fliggy", "price": 2765, "name": "日历最低价",
           "code": "", "depTime": "", "arrTime": "", "date": "2026-11-16"}
    row.update(over)
    return row


def test_fmt_flight_line_calendar_row_no_arrow_skeleton():
    line = Alerter._fmt_flight_line(dict(_cal_row()), idx=1)
    assert "→" not in line, "悬垂箭头假骨架：" + line
    assert "当日达" not in line, "假到达时刻尾注：" + line
    assert "￥2765" in line and "日历最低价" in line, \
        "价格+名字判据保留：" + line


def test_fmt_brief_calendar_row_no_arrow_skeleton():
    brief = Alerter._fmt_brief(dict(_cal_row()), budget=40)
    assert "→" not in brief, "悬垂箭头假骨架：" + brief
    assert "当日达" not in brief, "假到达时刻尾注：" + brief
    assert "￥2765" in brief, "价格判据保留：" + brief


def test_fmt_brief_calendar_transfer_row_no_arrow_skeleton():
    """无时刻行的中转分支守卫（transCity 在场走 _trans_city 单源中转
    分支；直飞分支由上两钉覆盖）——时刻档整段缺席后仍须落名字档/
    地板价档，不产「→」。"""
    brief = Alerter._fmt_brief(
        dict(_cal_row(_platform="qunar", price=12345,
                      transCity="郑州")), budget=40)
    assert "→" not in brief, brief
    assert "当日达" not in brief, brief
    assert "￥12345" in brief, brief


def test_fmt_flight_line_timed_row_unchanged():
    """有时刻行骨架不变（防误杀回归）：时刻对照旧在产物（_fmt_flight_line
    常态价带本就超宽剥「当日达」尾注=既有降级设计，不锁尾注锁骨架；
    _fmt_brief 行短，尾注在 full 档存活一并锁）。"""
    row = dict(_cal_row(code="HO1108", name="HO1108", price=276,
                        depTime="08:30", arrTime="11:20"))
    line = Alerter._fmt_flight_line(dict(row), idx=1)
    assert "08:30→11:20" in line, line
    brief = Alerter._fmt_brief(dict(row), budget=40)
    assert "08:30→11:20" in brief and "当日达" in brief, brief


def test_fmt_brief_calendar_worst_width_stays_clean():
    """最坏形态（5 位价宽恰卡预算零降级）仍不含假词面——守卫缺席
    时降级链救不了它（审校实证形态）。"""
    brief = Alerter._fmt_brief(
        dict(_cal_row(price=12345, name="日历最低价")), budget=40)
    assert "→" not in brief and "当日达" not in brief, brief
    assert "￥12345" in brief, brief
