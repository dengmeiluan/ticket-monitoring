# -*- coding: utf-8 -*-
"""推送回归钉：

 _fmt_brief 降级链中档恒死修复：fallback1 曾复用 arrive 尾巴带
「 当日达」/「（cross达）」7 半角，常规行恒 41/40 超宽直落末档——
图挂兜底行的出发/到达时刻在任何常规行都进不了文本；中档改裸
arrTime 剥尾注（中转/直飞两分支同修，执行级钉）。
 ops 回退截断保渠道清单（_ops_fallbacks 模块级纯函数，真执行级）：
原「冒号后清零+（截）」在 2+ 渠道缺失常态下渠道对账价值归零成病句；
降级链逐渠道剥尾保名单头，末档地板分叉——冒号形态保前缀、无冒号
形态截前 18 字符（终审：直挂标注缺失等无冒号形态若末档
仅存「（截）」则路由/日期/事由全灭，恢复 地板语义）。
钉输入均取生产四形态字面（alerter ops_notes 产出点：无数据/直挂
标注缺失/孤低价拦截/全渠道无数据）。

背景（矩阵）：11 定律全过 P0=P1=0；五路调研缩波全 PASS
（渠道关案第六轮维持）；上轮零立案后无词面/档位/字节限回归。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v170_push.py -q
"""
from core.alerter import Alerter, _disp_dw, _fit_line, _ops_fallbacks


# ---- _fmt_brief 降级链 ----------

def test_brief_mid_tier_keeps_times_normal_row():
    """常规行（东航短名）中档须携双时刻且 ≤40——修复前恒 41 落末档。"""
    f = {"price": 990, "name": "东航 MU5801", "depTime": "08:00",
         "arrTime": "12:30", "transCity": "西安", "layoverT": "2:15"}
    line = Alerter._fmt_brief(f)
    mid = "￥990 中转东航 MU5801 08:00→12:30"
    assert _disp_dw(mid) <= 40
    assert line == mid, "中档时刻仍死: %r" % line


def test_brief_direct_mid_tier_strips_daynote():
    """直飞分支中档剥「当日达」尾注：短名行入选，长名行安全落末档。"""
    f = {"price": 990, "name": "东航 MU5801", "depTime": "08:00",
         "arrTime": "12:30", "stopover": False}
    assert Alerter._fmt_brief(f) == "￥990 直飞东航 MU5801 08:00→12:30"
    long_f = dict(f, name="中国联合航空 KN5901", price=9900)
    out = Alerter._fmt_brief(long_f)
    assert _disp_dw(out) <= 40 and "12:30" not in out, \
        "长名行应落末档保价与航司: %r" % out


# ---- ops 回退降级链（_ops_fallbacks 真执行级） ----------

def test_ops_multi_channel_keeps_head():
    """生产形态「无数据：」短名渠道在首（platforms 顺序去哪儿常态靠前）：
    降级档保首渠道名（原冒号后清零）。"""
    n = "上→乌 09/25 无数据：去哪儿、飞猪(维护中)、携程"
    out = _fit_line("> ⚠️ " + n, fallbacks=_ops_fallbacks(n))
    assert _disp_dw(out) <= 40
    assert "去哪儿" in out, "首渠道名被清零: %r" % out


def test_ops_fliggy_note_first_falls_to_floor():
    """「飞猪(维护中)」12 半角在首：k 档超预算塌前缀地板——与旧版
    同地板无回归（实算在案），词面前缀+留痕仍保。"""
    n = "上→乌 09/25 无数据：飞猪(维护中)、去哪儿"
    out = _fit_line("> ⚠️ " + n, fallbacks=_ops_fallbacks(n))
    assert _disp_dw(out) <= 40 and "（截）" in out and "无数据：" in out


def test_ops_no_colon_keeps_head18_floor():
    """M1 地板：无冒号形态（直挂标注缺失）末档截前 18 字符，
    路由/日期/事由保留——修复前该形态曾塌「> ⚠️ （截）」全灭。"""
    n = "北→上 09/22 中转直挂标注缺失·达标判定失效"
    out = _fit_line("> ⚠️ " + n, fallbacks=_ops_fallbacks(n))
    assert _disp_dw(out) <= 40
    assert "北→上" in out and "中转直挂标注缺失" in out, \
        "无冒号地板退化: %r" % out


def test_ops_isolated_lowprice_floor():
    """生产形态「孤低价拦截×N：」（head 26 半角）：渠道名超预算塌前缀
    地板（与旧版同地板），词面前缀+留痕保，渠道全量对账循控制台。"""
    n = "上→乌 09/25 孤低价拦截×3：飞猪￥9900、去哪儿￥9500"
    out = _fit_line("> ⚠️ " + n, fallbacks=_ops_fallbacks(n))
    assert _disp_dw(out) <= 40
    assert "孤低价拦截×3：" in out and "（截）" in out


def test_ops_all_missing_no_degrade():
    """「本轮全渠道无数据」28 半角：不超宽原样入选零损失。"""
    n = "上→乌 本轮全渠道无数据"
    assert _disp_dw("> ⚠️ " + n) <= 40
    assert _fit_line("> ⚠️ " + n,
                     fallbacks=_ops_fallbacks(n)) == "> ⚠️ " + n
