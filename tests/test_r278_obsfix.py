# -*- coding: utf-8 -*-
"""r278 观测修复批：notifier 未启用时日志词面诚实度。

r278 观测 C[3]（P2）：推送通道未启用的实例词面仍打「-> 推送」，
`if should_push and self.notifier` 短路一条未发——「词面推送、实际
静默」=排查误导（词面与行为不符家族）。词面收口三分支：推送 /
跳过(原因) / 跳过(未启用推送)。日报同根：notifier=None 一路构建到
.send 抛 NoneType 异常栈——入口守卫 INFO 跳过（配置面预期静默打
INFO，异常才 WARNING）。
"""

import json
import logging

from core.alerter import Alerter
from core.models import Route


def _fp(price=1000, plat="qunar"):
    return {"price": price, "name": "国航CA1234", "code": "国航CA1234",
            "depTime": "08:00", "arrTime": "11:00", "depDate": "2027-01-29",
            "arrDate": "2027-01-29", "transCity": "", "crossDayDesc": "",
            "totalDuration": "3时", "_platform": plat}


def test_notifier_none_wording_category(caplog):
    """分类提醒路径：should_push=True 而 notifier=None 时，词面必须
    打「跳过(未启用推送)」，禁止「-> 推送」（词面推送实际静默）。"""
    log = logging.getLogger("r278_probe_cat")
    a = Alerter(log, notifier=None, storage=None, digest=True,
                at_mobile="", storm_repeat=1, user="词面演练")
    route = Route(from_code="SHA", to_code="HAK", from_name="上海",
                  to_name="海口", dates=["2027-01-29"],
                  alert_direct=1500, alert_transfer=1500)
    with caplog.at_level(logging.WARNING, logger="r278_probe_cat"):
        a._category_alert(route, "2027-01-29", _fp(), "direct", 1500,
                          1, "qunar")
    recs = [r for r in caplog.records if "低价-直飞" in r.getMessage()]
    assert recs, "分类提醒词面未落日志"
    msg = recs[-1].getMessage()
    assert "跳过(未启用推送)" in msg, msg
    assert "-> 推送" not in msg, msg


def test_notifier_none_wording_agg_source_pin():
    """直飞聚合路径同构词面（镜像块）：源码钉锁两处消费点全部走
    三分支形态，防只改一处（镜像同构块批量替换判例）。"""
    src = open("core/alerter.py", encoding="utf-8").read()
    n = src.count('"推送" if self.notifier else "跳过(未启用推送)"')
    assert n == 2, "三分支词面消费点期望 2 处，实为 %d" % n


def test_daily_report_notifier_none_guard(caplog, monkeypatch, tmp_path):
    """日报路径：notifier=None 入口守卫 INFO「日报跳过」早退，不落
    NoneType 异常栈词面（配置面预期静默打 INFO，异常才 WARNING）。"""
    import report
    monkeypatch.setattr(report, "_ROOT", str(tmp_path))
    log = logging.getLogger("r278_probe_daily")
    cfg = {"users": [{"name": "日报演练",
                      "notifier": {"report_hour": 9, "digest": True},
                      "routes": []}]}
    with caplog.at_level(logging.INFO, logger="r278_probe_daily"):
        report.maybe_daily_report(cfg, log, None, user="日报演练")
    msgs = [r.getMessage() for r in caplog.records]
    assert any("日报跳过" in m for m in msgs), msgs
