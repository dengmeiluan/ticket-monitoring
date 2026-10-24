# -*- coding: utf-8 -*-
"""运维对账注的国际零供给面豁免（推送审校 P2-1）。

_ops_notes / _daily_ops_notes 的缺勤判定无平台×域门：国际航线段把
「国际面全库史零供给」的渠道逐轮判缺勤（同程 19 条国际段全量在场
实录），真缺勤信号被恒真注稀释——违背供给基线定性律（窗口诞生起
恒零是 never-supplied 特征非断链）。豁免面=静态零供给面表单源
（c330 渠道调研定谳，渠道国际面恢复出数即撤）；国内域不豁免、
国际面有供给的渠道不豁免（守卫不误杀）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r331_push_ops.py
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import Alerter, Route  # noqa: E402
from report import _daily_ops_notes  # noqa: E402

_LOG = logging.getLogger("t_r331_ops")


def _mk_alerter():
    class FakeN:
        def send(self, t, d, at_mobiles=None, is_at_all=False, launch=""):
            return True
    return Alerter(_LOG, notifier=FakeN(), storage=None, digest=True)


def _route(**kw):
    d = dict(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
             to_name="上海", dates=["2026-11-16"],
             alert_direct=1900, alert_transfer=1700)
    d.update(kw)
    return Route(**d)


def _sec(seen=("qunar",)):
    return {"date": "2026-11-16",
            "top_direct": [], "top_transfer": [],
            "best_direct": None, "best_transfer": None,
            "best_transfer_mkt": None,
            "seen_plats": list(seen),
            "all_flights": [],
            "xphans": [], "qd": [], "qt": []}


# ---- P2-1：国际段零供给渠道豁免 ----

def test_ops_notes_intl_zero_supply_exempt():
    """国际航线缺勤注豁免零供给面渠道；国际面有供给的渠道照注。"""
    a = _mk_alerter()
    intl = _route(from_code="SHA", to_code="NRT",
                  from_name="上海", to_name="东京")
    # 全渠道缺席：同程豁免不出注，其余四渠道照注
    notes = a._ops_notes([(intl, [_sec(seen=())])])
    joined = "；".join(notes)
    assert "当轮无数据：去哪儿、飞猪、携程、途牛" in joined, joined
    assert "同程" not in joined, joined
    # 对照：途牛国际面有供给，缺席照注
    assert "途牛" in joined, joined


def test_ops_notes_domestic_no_exempt():
    """国内航线豁免不射：同程国内面有供给，缺席照注（守卫不误杀）。"""
    a = _mk_alerter()
    notes = a._ops_notes([(_route(), [_sec(seen=("qunar",))])])
    assert any("当轮无数据" in n and "同程" in n for n in notes), notes


def test_daily_ops_notes_intl_exempt():
    """日报姊妹路径同律（能力对称）：国际段缺同程无注。"""
    notes = _daily_ops_notes(
        ["qunar", "ctrip", "fliggy", "tongcheng"],
        seen={"qunar", "ctrip", "fliggy"},
        names=("上海", "东京"), date="2026-11-16",
        codes=("SHA", "NRT"))
    joined = "；".join(notes)
    assert "同程" not in joined, joined
    # 国内域对照：缺同程照注
    notes_dom = _daily_ops_notes(
        ["qunar", "tongcheng"], seen={"qunar"},
        names=("乌鲁木齐", "上海"), date="2026-11-16",
        codes=("URC", "SHA"))
    assert any("同程" in n for n in notes_dom), notes_dom
