# -*- coding: utf-8 -*-
"""r243 推送层：趋势行异常可观测 + 缺图词面去归因化。

P1-1（_scratch/worker_r243_push.md）：_trend_line except 静默吞异常
返回空串，调用点按「无数据」省略——磁盘满窗（SQLITE_FULL）19 条
推送 📉 趋势行静默消失（2 半缺+17 全缺），7 天趋势无第二文本载体、
无任何缺标标注。修法：异常返回 None（区别于无数据空串）+ 日志留痕，
调用点补「⚠️ 近7天趋势暂缺」标注（异常才提示，常态零噪音——
LESSONS 十六§4）。

P2-1：缺图分支词面「走势图上传失败」是具体归因猜测——alerter 层
只知道「无图」，实因可能是生成失败（SQLITE_FULL）也可能是上传失败，
磁盘满窗 12 轮 ops 对账被朝图床/网络方向误导（监控日志本有精确
归因）。修法：词面中性化「走势图缺失」，归因以监控日志为准。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r243_push.py -q
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import report as _rep  # noqa: E402
from core.alerter import Alerter  # noqa: E402
from core.models import Route as _R  # noqa: E402

_LOG = logging.getLogger("r243")


def _route():
    return _R(from_code="SHA", to_code="URC", from_name="上海",
              to_name="乌鲁木齐", dates=["2026-09-25"],
              alert_direct=1900, alert_transfer=1700)


def _sections():
    s = {"date": "2026-09-25",
         "best_direct": {"price": 1950, "name": "MU8369",
                         "depTime": "19:55", "arrTime": "01:25",
                         "_platform": "qunar"},
         "best_transfer": None,
         "seen_plats": ["qunar"]}
    return [s]


class _FakeStor:
    db_path = ":memory:"


def _al(stor=None, charts=None):
    a = Alerter(_LOG, storage=stor, digest=True)
    a.round_charts = charts or {}
    return a


def _payload(a, **kw):
    kw.setdefault("fresh", False)
    kw.setdefault("with_tables", False)
    return a._digest_payload([(_route(), _sections())], **kw)


def test_trend_line_exception_marks_gap(monkeypatch):
    """P1-1：_rounds 查询异常（磁盘满窗实锤形态）→ desp 补
    「近7天趋势暂缺」标注，不再静默消失。"""
    def _boom(*_a, **_k):
        raise RuntimeError("database or disk is full")

    monkeypatch.setattr(_rep, "_rounds", _boom)
    p = _payload(_al(stor=_FakeStor()))
    assert "近7天趋势暂缺" in p["desp"], p["desp"][:600]


def test_trend_line_exception_logged(monkeypatch, caplog):
    """P1-1：异常必须留日志痕（本轮省略的事实与原因可对账）。"""
    def _boom(*_a, **_k):
        raise RuntimeError("database or disk is full")

    monkeypatch.setattr(_rep, "_rounds", _boom)
    with caplog.at_level(logging.WARNING, logger="r243"):
        _payload(_al(stor=_FakeStor()))
    assert any("趋势" in r.message for r in caplog.records), caplog.text


def test_trend_line_no_data_stays_silent(monkeypatch):
    """无数据（空窗合法形态）语义不变：整行省略，不出「暂缺」标注
    （异常才提示，常态零噪音）。"""
    monkeypatch.setattr(_rep, "_rounds", lambda *a, **k: [])
    p = _payload(_al(stor=_FakeStor()))
    assert "暂缺" not in p["desp"], p["desp"][:600]


def test_trend_line_ok_kept(monkeypatch):
    """正常趋势行回归锚：直飞 ↓16% 词面原样（修复不伤常态）。"""
    monkeypatch.setattr(
        _rep, "_rounds",
        lambda *a, **k: [["2026-09-19", 1900, 2100],
                         ["2026-09-25", 1600, 2000]])
    p = _payload(_al(stor=_FakeStor()))
    assert "近7天" in p["desp"] and "↓16%" in p["desp"], p["desp"][:600]


def test_missing_chart_neutral_word():
    """P2-1：缺图词面中性化「走势图缺失」——不再猜测「上传失败」
    具体归因（生成失败/上传失败在 alerter 层不可分辨，归因看日志）。"""
    p = _payload(_al())
    assert "走势图缺失" in p["desp"], p["desp"][:600]
    assert "上传失败" not in p["desp"], p["desp"][:600]


def test_missing_chart_word_absent_when_chart_ok():
    """图在时零假警告回归锚（test_core_units 既有语义跨改词面保留）。"""
    p = _payload(_al(charts={("SHA", "URC", "2026-09-25"):
                             "https://x/y.png"}))
    assert "走势图缺失" not in p["desp"], p["desp"][:600]


def test_kpi_l2_cross_parenthesized(monkeypatch):
    """P2-2：KPI 行2 跨天词面括注态「19:55→00:05(+1天)」——与 🔥 行
    base_seg 同贴法（同屏 bare/括注双形态收口）。"""
    monkeypatch.setattr(_rep, "_rounds", lambda *a, **k: [])
    a = _al(stor=_FakeStor())
    secs = _sections()
    secs[0]["best_direct"] = dict(
        secs[0]["best_direct"], arrTime="00:05",
        crossDayDesc="+1天")
    p = a._digest_payload([(_route(), secs)], fresh=False,
                          with_tables=False)
    assert "00:05(+1天)" in p["desp"], p["desp"][:700]
    assert "00:05+1天" not in p["desp"], p["desp"][:700]


def test_kpi_l2_cross_paren_kept_under_degrade(monkeypatch):
    """降级链连验：超宽身份行（长双名+跨天）降档后到达时刻+括注
    必须在位（括注 +2 半角不得把辨识信息挤丢失）。"""
    monkeypatch.setattr(_rep, "_rounds", lambda *a, **k: [])
    a = _al(stor=_FakeStor())
    secs = _sections()
    secs[0]["best_direct"] = dict(
        secs[0]["best_direct"], name="新海航｜海南航空 HU7849",
        arrTime="00:05", crossDayDesc="+1天")
    p = a._digest_payload([(_route(), secs)], fresh=False,
                          with_tables=False)
    assert "00:05(+1天)" in p["desp"], p["desp"][:700]


def test_daily_miss_chart_line_neutral():
    """P1-S1：日报缺图行与主推送同律中性化（同因两词面跨推送并存
    曾误导 ops 对账——生成失败/上传失败在消费层不可分辨）。"""
    from report import _miss_chart_line
    # 短名样本逼出首档（全名首档恒超宽走末档「本期无图」，本就中性）
    line = _miss_chart_line("乌→上", "2026-10-05")
    assert "走势图缺失" in line, line
    assert "上传失败" not in line, line
    # 全名降档路径回归锚：末档词面中性（日期+「本期无图」保辨识）
    line2 = _miss_chart_line("上海→乌鲁木齐", "2026-10-05")
    assert "上传失败" not in line2 and "10/05" in line2, line2


def test_summary_table_fallback_neutral(monkeypatch):
    """总表兜底头同律：render/上传失败在 alerter 层同表现为无图，
    词面去归因化「明细总表缺失」（完整明细见控制台的出口指引保留）。"""
    import logging as _lg
    # 总表缺失分支单元直调（十九§14：_flights_table_md_multi 整体返回
    # 空才触发 _fb_head，全链构造要绕过多级文字回退，直调锁分支输出）
    monkeypatch.setattr(Alerter, "_flights_table_md_multi",
                        lambda self, rs_list, ops_notes=None: "")
    a = Alerter(_lg.getLogger("r243"), storage=None, digest=True)
    p = a._digest_payload([(_route(), _sections())], fresh=False)
    assert "明细总表缺失" in p["desp"], p["desp"][-500:]
    assert "明细总表上传失败" not in p["desp"], p["desp"][-500:]


def test_table_miss_words_source_pin():
    """日报明细表缺图行同律（词面源码钉：日报组装构造重，锁出口词面）。"""
    src = open(os.path.join(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))),
        "report.py"), encoding="utf-8").read()
    assert "明细表缺失" in src
    assert "明细表上传失败" not in src
