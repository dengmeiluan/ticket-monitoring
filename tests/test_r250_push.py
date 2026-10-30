# -*- coding: utf-8 -*-
"""r250 推送 P2-1r（TDD 先行，审计报告 _scratch/r250_push_audit.md）：

三处 _trim 剥括号 while 循环 else:break 早停——「末个「（」右侧有
    任一「）」即 break」在双层开括号名（北京（首都（T3）区）形）
    截断窗跨「内闭外开」时不收敛：剥掉内层残段后外层开括号仍悬垂
    （r249 P2-1 验收口径「地板档输出不含未配对全角括号」在双层域
    未闭合）。修法：剥档判据改计数式（开括号数>闭括号数即继续从
    末个开括号剥），三处同轮。现实城市名单层形态输出不变（平衡时
    循环体一次都不进）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r250_push.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.alerter import Alerter, _dw
import report


def _balanced(s: str) -> bool:
    return s.count("（") == s.count("）")


# ---------- alerter._section_title ----------

def test_section_title_double_nest_parens_balanced():
    """现实双层括号名的零回归钉（该输入未落病灶窗，抓旧 else:break
    bug 的复现钉是下方 pure-nest 直调钉；Soldier M1 变异定位）。"""
    out = Alerter._section_title(
        "北京（首都（T3）区）", "上海（虹桥+浦东）", "10/06~10/08", "")
    assert out, "无输出"
    assert _balanced(out), (
        "双层括号城市名截断窗产出未配对括号：%r——剥档判据须计数式"
        "（开>闭即继续剥），else:break 在「内闭外开」窗早停" % out)
    for ln in out.split("\n"):
        assert _dw(ln) <= 40, "标题行超宽 %r (%d)" % (ln, _dw(ln))


def test_section_title_single_layer_zero_regression():
    out = Alerter._section_title(
        "乌鲁木齐（地窝堡）", "上海（虹桥+浦东）", "10/06~10/08", "")
    assert _balanced(out), "单层形态产出未配对括号 %r" % out


# ---------- report._route_section_title ----------

def test_route_section_title_double_nest_parens_balanced():
    out = report._route_section_title(
        ["北京（首都（T3）区）", "上海（虹桥+浦东）"], "2026-10-06")
    assert _balanced(out), "双层括号名产出未配对括号 %r" % out
    for ln in out.split("\n"):
        if ln:
            assert report._dw_line(ln) <= 40, "标题行超宽 %r" % ln


# ---------- report._miss_chart_line ----------

def test_miss_chart_line_double_nest_parens_balanced():
    """现实双层括号名的零回归钉（复现钉=下方 pure-nest 直调钉）。"""
    out = report._miss_chart_line(
        "北京（首都（T3）区）→上海（虹桥+浦东）", "2026-10-06")
    assert _balanced(out), (
        "缺图行双层括号名产出未配对括号（审计直调实锤形态）：%r" % out)
    for ln in out.split("\n"):
        if ln:
            assert report._dw_line(ln) <= 40, "缺图行超宽 %r" % ln


def test_miss_chart_line_pure_nest_truncation_balanced():
    """审计直调最小复现：入参括号串 room 内截断于「内闭外开」窗，
    现行输出 3 开 1 闭。"""
    out = report._miss_chart_line("（（（）））→（（））", "2026-10-06")
    assert _balanced(out), "纯嵌套截断产出未配对括号 %r" % out


def test_miss_chart_line_single_layer_zero_regression():
    out = report._miss_chart_line("乌鲁木齐（地窝堡）→上海（虹桥+浦东）",
                                  "2026-10-06")
    assert _balanced(out), "单层形态产出未配对括号 %r" % out
    assert "乌鲁木齐" in out, "单层形态城市名丢失 %r" % out
