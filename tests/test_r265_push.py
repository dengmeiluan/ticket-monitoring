# -*- coding: utf-8 -*-
"""r265 推送：日报图挂兜底补运维对账注（推送审校 P3-1，能力对称）。

证据（_scratch/audit_r265_push.md P3-1 + LESSONS 三十§3）：日报明细
表图挂时（上传失败/渲染异常两分支）文本兜底只有 KPI+TOP5——
_daily_ops_notes 的对账注（渠道缺勤/直挂标注缺失/孤低价拦截）随图
沉没整篇消失；告警路径同场景 ops 注随兜底在场（alerter 预算内竞争）。
日报是每日唯一综合视图，图挂日恰是渠道故障日（高发同时），对账注
缺席=读者无法区分「没有便宜班次」与「班次被守卫剔除」。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r265_push.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import _disp_dw  # noqa: E402
from report import _daily_ops_fallback  # noqa: E402

_NOTES = [
    "乌鲁木齐→上海 10/15 当轮无数据：途牛、同程",
    "乌鲁木齐→上海 10/15 孤低价拦截×2：飞猪￥9900、去哪儿￥9500",
]


def test_daily_ops_fallback_renders_notes():
    """非空对账注逐条进兜底：告警路径同构词面（> ⚠️ 前缀），每行
    过 40 半角渲染宽守卫（_disp_dw 口径，含前缀整行计量）；宽头注
    按 _ops_fallbacks 地板档保头段（航线+日期+事由，与告警路径
    完全同构——渠道清单在 40 预算下装不下是单源定版行为）。"""
    out = _daily_ops_fallback(_NOTES)
    assert out
    assert out.count("> ⚠️ ") == 2
    assert "乌鲁木齐→上海 10/15" in out
    assert "当轮无数" in out and "孤低价拦" in out
    for ln in out.strip().split("\n\n"):
        assert _disp_dw(ln) <= 40, (ln, _disp_dw(ln))


def test_daily_ops_fallback_overwide_note_demoted():
    """超宽注（2+ 渠道缺失常态）走 _ops_fallbacks 降级链落位，不超
    红线也不整条蒸发（头段=对账起点恒在场）。"""
    wide = "乌鲁木齐→上海 10/15 当轮无数据：途牛、同程、飞猪、智行、美团"
    out = _daily_ops_fallback([wide])
    assert out and "> ⚠️ " in out
    assert "乌鲁木齐→上海 10/15" in out
    for ln in out.strip().split("\n\n"):
        assert _disp_dw(ln) <= 40, (ln, _disp_dw(ln))


def test_daily_ops_fallback_empty():
    """空注返空串：全勤无拦截时兜底区零占位（_daily_ops_notes 同律）。"""
    assert _daily_ops_fallback([]) == ""
    assert _daily_ops_fallback(None) == ""


def test_daily_both_image_fail_branches_consume():
    """源码钉：明细表图挂的两分支（上传失败 else / 渲染异常 except）
    同接 _daily_ops_fallback——能力对称只修一分支=另一分支图挂日
    对账注照旧蒸发（LESSONS 十九§14 空分支/兜底分支漏盘点判例）。"""
    src = open("report.py", encoding="utf-8").read()
    assert src.count("_daily_ops_fallback(") >= 3   # 定义 + 2 消费点
