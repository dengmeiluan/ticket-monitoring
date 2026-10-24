# -*- coding: utf-8 -*-
"""r324 推送地板档三案钉（审校 P2-1/P3-1/P3-2）：

- P2-1 slim 心跳裸身份地板：双侧 8+ 全角自定义城市名域（机场全称
  级），best 链末档实测 49/40、补位/无明细链实测 64/40（无剥窗档）
  ——`_bare_identity_floor` 头侧逐字截（浮点累计，日期段恒在），
  补位/无明细链补剥窗档与 best 链同律。
- P3-1 日报比价兜底保险丝自身 NameError：_daily_compare_fallback
  的 except 引用模块不存在的 logger（logger 是 build_and_push 形参
  非模块级）——logger 形参透传，触发返回空串不抛。
- P3-2 建议行 fallback 与基档逐字同一（零降级，实证 fb==full）：
  pad>0 旋钮域 41/40——去税注档先行（次要信号先丢）+ 截名地板。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r324_push_floor.py -q
"""
import logging as _lg
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.alerter as alerter  # noqa: E402
from core.alerter import (Alerter, _bare_identity_floor, _clip_dw,  # noqa: E402
                          _disp_dw, _fit_line)
from core.models import Route  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 审校实测越界样本：双侧 8+ 全角（49/40 与 64/40 的名字本体）
_LONG_HEAD = "阿拉善左旗超长名测试→乌鲁木齐地窝堡国际"
_LONG_HEAD_WIN = _LONG_HEAD + "（19:00后出发）"


def test_bare_floor_fits_long_names():
    """6 组长名输入全过 40 线，日期段恒在、无未配对「（」。"""
    for head in (_LONG_HEAD, _LONG_HEAD_WIN):
        for d in ("01/29", "01/30"):
            out = _bare_identity_floor(head, d)
            assert _disp_dw(out) <= 40, (head, d, out, _disp_dw(out))
            assert out.endswith(" " + d), out
            assert out.count("（") <= out.count("）"), out


def test_bare_floor_current_domain_verbatim():
    """现行 OD 域（2 全角城市词）不触发截名：逐字等于裸身份行。"""
    assert _bare_identity_floor("上海→海口", "01/29") == "> 上海→海口 01/29"


def test_suggest_taxpad_near_line_fits(monkeypatch):
    """pad>0 × fliggy × 擦边不足1% 组合域：基档确越界（41/40 族），
    去税注档承接后 ≤40（装配语义与源码钉互锁）。"""
    route = Route(from_code="SHA", to_code="URC", from_name="上海",
                  to_name="乌鲁木齐", dates=["2026-09-25"],
                  alert_direct=1000, alert_transfer=900)
    s = {"date": "2026-09-25",
         "best_direct": {"price": 1005, "name": "HO1251",
                         "depTime": "08:00", "arrTime": "10:35",
                         "_platform": "fliggy"},
         "best_transfer": None, "seen_plats": ["fliggy"]}
    a = Alerter(_lg.getLogger("t324f"), storage=None)
    monkeypatch.setattr(alerter, "FLIGGY_TAX_PAD", 100)
    sg = a._suggest_line(route, s)
    assert sg and "（税前价）" in sg, sg
    sg_line = f"> 💡 {sg}"
    assert _disp_dw(sg_line) > 40, (sg, _disp_dw(sg_line))
    fixed = _fit_line(sg_line, fallbacks=[
        sg_line.replace("（税前价）", ""), _clip_dw(sg_line, 40)])
    assert _disp_dw(fixed) <= 40, (fixed, _disp_dw(fixed))
    assert "税前价" not in fixed, fixed   # 次要信号先丢，判据词保全


def test_report_compare_fallback_survives_crash(monkeypatch):
    """保险丝自证：_cross_compare 抛任何异常，兜底返回空串不抛
    （旧码 except 引用未定义 logger=NameError 二次上抛）。"""
    import report

    def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(Alerter, "_cross_compare",
                        staticmethod(_boom))
    assert report._daily_compare_fallback([], [], "2026-01-01") == ""
    assert report._daily_compare_fallback(
        [], [], "2026-01-01", _lg.getLogger("t324f")) == ""


def test_source_pins_floor_wiring():
    """源码钉：地板档三链接线 + 去税注档 + 兜底 logger 透传。"""
    asrc = open(os.path.join(ROOT, "core", "alerter.py"),
                encoding="utf-8").read()
    assert asrc.count("_bare_identity_floor(") >= 4, (
        "def + 三链调用点应齐（best/补位/无明细）")
    assert "sg_line.replace(\"（税前价）\", \"\")" in asrc, (
        "建议行去税注档应在案")
    rsrc = open(os.path.join(ROOT, "report.py"), encoding="utf-8").read()
    assert rsrc.count(
        "_daily_compare_fallback(directs, mkt_t, date, logger)") == 2, (
        "两处调用点应透传 logger")
