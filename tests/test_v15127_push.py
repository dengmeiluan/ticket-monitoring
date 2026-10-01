# -*- coding: utf-8 -*-
"""r227 推送层两案：

P3-5 KPI 档位 emoji 点位单源收口：tier_dot(qual_hit, diff, th)——
五处手抄散点（_kpi_block/_mini_kpi/_push_digest 直飞+中转分支/
report._kpi）统一走 TIER_EMOJI 投影（LESSONS 十六§3b 单源律；
r226 审校 P3-5 挂账收口）。改点位判定只动 tier_dot+图例。

P3-8 预览占位注行自身超宽：webui 预览器「（预览态不含明细总表
图——实发在此位置附整表 PNG）」整行 50/40 超 20 全角红线（r226
修 P3-1 引入时未量宽）——收窄词面 + 测试锁整行 ≤40。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15127_push.py -q
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import tier_dot  # noqa: E402
from core.alerter import _dw as _dw_line  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_tier_dot_tier_ladder():
    # 四档梯度同向：🎯=达标口径、🟩=行情破线（含恰达线 diff==0）、
    # 🟨=擦边（≤NEAR_RATIO）、超线默认态不加点
    assert tier_dot(True, -100, 2000) == "🎯 "
    assert tier_dot(True, 600, 2000) == "🎯 "     # qual 判定优先于 diff
    assert tier_dot(False, -100, 2000) == "🟩 "
    assert tier_dot(False, 0, 2000) == "🟩 "      # 恰达线非达标=行情档
    assert tier_dot(False, 60, 2000) == "🟨 "     # 3% 擦边
    assert tier_dot(False, 600, 2000) == ""       # 30% 超线不加点


def test_tier_dot_zero_threshold_safe():
    # th=0（未设线）：只认 qual，不做除法
    assert tier_dot(True, -100, 0) == "🎯 "
    assert tier_dot(False, -100, 0) == ""


def test_tier_dot_literal_purge():
    # 手抄字面串归零：带尾空格的档位 emoji 字面在两文件源码中只剩
    # _TIER_TABLE 定义（无尾空格）——全部消费点走 TIER_EMOJI 投影
    for rel in ("core/alerter.py", "report.py"):
        src = open(os.path.join(_ROOT, rel), encoding="utf-8").read()
        for ch in ("🎯", "🟩", "🟨"):
            hits = re.findall('"%s "|\'%s \'' % (ch, ch), src)
            assert hits == [], "%s 残留手抄 %s" % (rel, ch)


def test_report_kpi_mark_via_projection():
    # report._kpi 的加粗判定同步单源：不再比较 emoji 字面
    src = open(os.path.join(_ROOT, "report.py"), encoding="utf-8").read()
    assert 'mark == "🎯 "' not in src
    assert 'TIER_EMOJI["qual"] + " "' in src


def test_preview_placeholder_line_width():
    # P3-8：预览占位注整行（含 "> " 前缀）≤40 半角（20 全角）
    src = open(os.path.join(_ROOT, "webui.py"), encoding="utf-8").read()
    m = re.search(r'"> （(预览态[^）]*)）', src)
    assert m, "预览占位注词面不在场"
    line = "> （" + m.group(1) + "）"
    assert _dw_line(line) <= 40, "占位注整行 %s 宽=%d" % (
        line, _dw_line(line))
    # 旧超宽词面退场
    assert "实发在此位置附整表 PNG" not in src
