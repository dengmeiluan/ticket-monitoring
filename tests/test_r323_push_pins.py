# -*- coding: utf-8 -*-
"""r323 推送层钉（TDD 先行，审校报告 _scratch/r323_wave3_push.md）：

- P2-2 日报「近7天趋势行」查询异常静默吞（except: pass）——告警路径
  同场景补「⚠️ 近7天趋势暂缺」对账注在案，两侧能力对称收口；
- P2-1 备案钉：日报单发零重试是用户终局裁决（-1=幽灵送达实锤），
  对账注常量单源在 core.alerter，日报侧零手抄词面；
- P3-2 中转衔接第二行 token 链单源 _transfer_layover_line：跨航站楼
  （到/出楼齐且相异）落「T1→T2」token——「需转运」行的跨楼地面
  转运成本此前图上不可见（已采键零消费）；
- P3-3 总表图例补「未必可出手」购买性语义（r318 slim 撤 💡 建议行
  后，行情破线档的动作语义在图内零承载）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r323_push_pins.py -q
"""
import logging as _lg
import sys
from datetime import datetime

import pytest

sys.path.insert(0, __import__("os").path.dirname(
    __import__("os").path.dirname(__import__("os").path.abspath(__file__))))

import report as rep  # noqa: E402
from core.alerter import _TREND_MISSING_NOTE  # noqa: E402
from report import _transfer_layover_line, _TBL_TIER_LEGEND  # noqa: E402

_DATE = "2026-09-25"
_ROUTES = [
    {"from": "SHA", "to": "URC", "from_name": "上海",
     "to_name": "乌鲁木齐", "dates": [_DATE],
     "alert_direct": 2000, "alert_transfer": 1800,
     "transfer_arrival_max": "02:00"},
]


def _cfg(routes):
    return {"notifier": {"image_host": {"provider": "freeimage"}},
            "users": [{"name": "u", "routes": routes,
                       "platforms": ["qunar", "ctrip"],
                       "notifier": {"image_host": {"provider": "freeimage"}}}]}


class FakeN:
    def __init__(self):
        self.sent = {}

    def send(self, title, desp="", **kw):
        self.sent["title"], self.sent["desp"] = title, desp
        return True


def test_transfer_layover_line_tokens():
    """token 链（单源）：停[·二段]。跨楼 token 不在此链（挂到达列，
    挤进本链会随中转列宽截断面常态被吃——目检实录）。"""
    f = {"layoverT": "2:05", "lay2dep": "14:30",
         "transGoDate": "2027-01-30",
         "transTerminal": "T1", "transDepTerminal": "T2"}
    assert _transfer_layover_line(f) == "停2:05·二段01-30 14:30"
    assert _transfer_layover_line({"layoverT": "2:05"}) == "停2:05"
    assert _transfer_layover_line(
        {"layoverT": "1:10", "lay2dep": "16:30"}) == "停1:10·二段16:30"
    assert _transfer_layover_line({"transTerminal": "T1"}) == ""
    assert _transfer_layover_line({}) == ""


def test_terminal_key_consumed_in_table_render():
    """transTerminal 落图消费点在案（已采键零消费回归面）。"""
    with open("report.py", encoding="utf-8") as f:
        src = f.read()
    assert "transTerminal" in src and "transDepTerminal" in src
    assert "_tt}→{_tdt}" in src


def test_daily_trend_exception_reconciled(monkeypatch):
    """日报趋势查询异常补对账注（告警路径同场景同词面，能力对称）。"""
    monkeypatch.setattr(rep, "_rounds",
                        lambda db, fc, tc, d, am, **kw:
                        [(datetime(2026, 9, 20, 8, 0), 576.0, None)])
    monkeypatch.setattr(rep, "prepare_round_charts",
                        lambda c, lg, *a, **k: {})
    monkeypatch.setattr(rep, "render_flights_table", lambda *a, **k: None)
    monkeypatch.setattr(rep, "upload_freeimage",
                        lambda p, lg: "http://x/f.png")
    monkeypatch.setattr(rep, "_route_latest_flights",
                        lambda db, fc, tc, d, **kw:
                        [{"price": 2690, "transCity": "",
                          "_platform": "qunar"}])
    def _boom(*a, **k):
        raise RuntimeError("db 满窗异常")
    monkeypatch.setattr(rep, "_trend_line_str", _boom)
    n = FakeN()
    ok = rep.build_and_push(_cfg(_ROUTES), _lg.getLogger("t"), n, user="u")
    assert ok and n.sent["desp"]
    assert "近7天趋势暂缺" in n.sent["desp"], n.sent["desp"]


def test_trend_missing_note_single_source():
    """对账注词面单源在 alerter（日报 import 消费，零手抄第二份）。"""
    assert _TREND_MISSING_NOTE == "> ⚠️ 近7天趋势暂缺"
    with open("core/alerter.py", encoding="utf-8") as f:
        assert f.read().count("近7天趋势暂缺") == 1
    with open("report.py", encoding="utf-8") as f:
        assert "近7天趋势暂缺" not in f.read()


def test_tbl_tier_legend_purchasability_note():
    """图例带「未必可出手」购买性语义（行情破线档动作语义入图）。"""
    assert "未必可出手" in _TBL_TIER_LEGEND
