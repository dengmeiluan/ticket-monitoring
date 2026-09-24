# -*- coding: utf-8 -*-
"""推送层回归：总表图共享缩档数字头航班号（P0）+ ops_notes
回退行前缀入量纲（P1）+ 持续达标标题分隔符（P1）+ 标题 60 超限
「另监控」段整段降级（P2）+ _alert_body 装饰清单补缺口（P2）+
日报缺图行前缀入量纲（P2）+ 钉钉 desp 尾空段收口（P2）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v162_push.py -q
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.notifier import _alert_body  # noqa: E402

_ALERTER = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "core", "alerter.py")
_REPORT = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "report.py")
_NOTIFIER = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "core", "notifier.py")


def _src(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ----：总表图 _plan_sub 缩共享产出错误航班号（数字头二字码被
# 吞首位：9C8845→C8845，3U/8L 同病）——错误值违反宁缺勿错 ----

def test_plan_sub_share_short_digit_head_code():
    src = _src(_REPORT)
    # 旧正则不得回潮（[A-Z] 开头吞掉 9C/3U/8L 的数字头）
    assert '([A-Z][A-Z0-9]*\\d{3,4})$' not in src
    assert '([A-Z0-9]{2}\\d{3,4})$' in src
    # 同式功能钉：数字头二字码/常规二字码全还原
    pat = re.compile(r"([A-Z0-9]{2}\d{3,4})$")
    for full, want in (("共享·春秋航空9C8845", "9C8845"),
                       ("共享·四川航空3U8845", "3U8845"),
                       ("共享·祥鹏航空8L9888", "8L9888"),
                       ("共享·吉祥航空HO1108", "HO1108"),
                       ("共享·南方航空CZ6798", "CZ6798")):
        m = pat.search(full)
        assert m and m.group(1) == want, full


# ----：ops_notes 文本回退行「> ⚠️ 」前缀未入 _fit_line 量纲
# （重放实测 41 半角超宽行， 同病漏网）----

def test_ops_notes_fallback_prefix_in_quantity():
    src = _src(_ALERTER)
    assert '"> ⚠️ " + _fit_line(' not in src


# ----：持续达标标题与航线缩写粘连（生产实发
# 「🔔 持续达标上→乌 09/25」扫读歧义）----

def test_sticky_title_separator():
    src = _src(_ALERTER)
    assert '"🔔 持续达标·"' in src
    assert 'else "🔔 持续达标"' not in src


# ----：标题 60 半角硬截断曾静默丢尾（push_history 62 字符
# 实发实证）——超限「另监控」段整段降级 ----

def test_title_overflow_drops_other_monitor_segment():
    src = _src(_ALERTER)
    assert 'split("｜另监控 ")' in src


# ----：_alert_body 装饰剥离清单补 🔔/📲/👉（达标主路径
# 直达 TTS/短信；💰/⚖️ 图挂兜底路径可达）----

def test_alert_body_strips_missing_decorations():
    body = _alert_body("#### 🔔 持续达标（电话已提醒过）\n\n"
                       "[📲 完整详情（点击直达）](x)\n\n"
                       "[👉 在去哪儿查看详情](y)\n\n💰⚖️")
    for e in ("🔔", "📲", "👉", "💰", "⚖️"):
        assert e not in body, e
    # 档位转写词不受影响（勿动已转写的 🎯🟩🟨🔥）
    assert "持续达标（电话已提醒过）" in body


# ----：日报缺图对账行「> 」前缀未入量纲（同家族）----

def test_daily_noline_prefix_in_quantity():
    src = _src(_REPORT)
    assert '"> " + _fit_line(' not in src


# ----：钉钉 desp 尾空段收口（图片行后「\n\n」尾随空段全量
# 存在，零信息损失仅末尾留白）----

def test_dingtalk_desp_trailing_blank_stripped():
    src = _src(_NOTIFIER)
    assert '(desp or title or "").rstrip()' in src
