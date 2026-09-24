# -*- coding: utf-8 -*-
"""r191 推送面回归（审校 P1×2 + P2 demo 演示面）。

- P1-1：图挂兜底比价头行降级第二档「- …航班号」含 U+2026——钉钉
  渲染成「。。。。」（LESSONS 十§2 确定安全字符集律），该 desp 同源
  进 ntfy/短信/弹窗三处剥除链均不含 U+2026。修法=去省略号（去航司
  名保航班号的降级本就是词面缩减，无需符号标记）。
- P1-2：KPI 行2 降级链优先级倒挂——旧链先丢跨天保涨跌，超宽加剧时
  跨天与涨跌双双丢失；跨天班「21:10→02:35」读不出 +1 天=读者误判
  当日达（决策级信息），修法=跨天档优先于涨跌档（十九§4 日期=跨天
  辨识信息同律）。
- P2-1：demo 演示数据补「有餐食」正向行（fliggy 双态值域的演示
  目检面，此前只合成「无餐食」）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v191_push.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import Alerter, _disp_dw, _fit_line, _l2_fallbacks  # noqa: E402,E501

_LOG = logging.getLogger("t1591p")


# ---- P1-1：图挂兜底头行 U+2026 ----

def test_cross_compare_fallback_no_ellipsis():
    """跨渠道共享航班双侧航司长名（28 半角名+结论尾 42/40 超宽）触发
    头行降级第二档（去航司名保航班号）：输出不含 U+2026（钉钉渲染
    。。。。），航班号与结论保留。"""
    long_name = "奥凯航空｜中国联合航空KN1234"
    pool = []
    for plat, price in (("qunar", 1000), ("fliggy", 1350),
                        ("tongcheng", 1700)):
        pool.append({"price": price, "name": long_name, "code": "GS7728",
                     "depTime": "08:20", "arrTime": "13:40",
                     "transCity": "", "crossDayDesc": "",
                     "stopover": False, "_platform": plat})
    txt = Alerter._cross_compare([{"date": "2026-10-10", "pool": pool}])
    assert txt
    assert "\u2026" not in txt, "图挂兜底头行残留 U+2026（钉钉渲染。。。）"
    assert "KN1234" in txt, "降级档丢航班号（地板档语义受损）"


def test_kpi_l2_call_site_uses_fallbacks_helper():
    """调用点源码钉：KPI 行2 降级走 _l2_fallbacks 单源（档序修复
    不被调用点内联链回退）。"""
    import core.alerter as al
    with open(al.__file__, encoding="utf-8") as f:
        src = f.read()
    assert "fallbacks=_l2_fallbacks(" in src, \
        "KPI 行2 调用点未走 _l2_fallbacks 单源"


# ---- P1-2：KPI 行2 跨天优先于涨跌 ----

def test_l2_fallbacks_cross_day_before_delta():
    """降级链档序：跨天括注档在涨跌档之前（跨天=决策辨识信息，
    涨跌=次要信号）。"""
    fb = _l2_fallbacks("BASE", "+1天", " ｜ 较上轮 ↓￥133")
    assert fb[0] == "BASE+1天", "跨天档不在首位"
    assert fb[1] == "BASE ｜ 较上轮 ↓￥133", "涨跌档不在次位"
    assert fb[-1] == "BASE", "地板档缺失"


def test_kpi_l2_cross_day_survives_narrow_fit():
    """生产可达输入（42 半角行基+跨天+涨跌）：fit 结果必须保留
    +1 天（旧链在跨天档也超时与涨跌双丢）。"""
    base = "新海航｜海南航空HU7849 21:10→02:35"
    cross, d = "+1天", " ｜ 较上轮 ↓￥133"
    full = base + cross + d
    assert _disp_dw(full) > 40, "样本未触发降级（判据失效）"
    l2 = _fit_line(full, fallbacks=_l2_fallbacks(base, cross, d))
    assert "+1天" in l2, f"跨天括注被降级丢弃 {l2!r}"
    assert _disp_dw(l2) <= 40, f"行2 超宽 {l2!r}"


# ---- P2-1：demo 演示面覆盖「有餐食」 ----

def test_demo_covers_meal_positive(tmp_path):
    """fliggy 演示行 meal 值域含「有餐食」与「无餐食」双态（演示
    目检面与生产值域对齐）。"""
    import core.demo as demo
    db = str(tmp_path / "demo.db")
    demo.build_demo_db(db)
    import sqlite3
    conn = sqlite3.connect(db)
    meals = set()
    for (extra,) in conn.execute(
            "SELECT extra FROM flight_prices WHERE platform='fliggy' "
            "AND extra != ''"):
        for f in json.loads(extra):
            if f.get("meal"):
                meals.add(f["meal"])
    conn.close()
    assert "无餐食" in meals, "负向演示行丢失"
    assert "有餐食" in meals, "「有餐食」正向值域无演示目检面"
