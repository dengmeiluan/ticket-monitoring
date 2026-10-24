# -*- coding: utf-8 -*-
"""r339j 新智能筛选：最长飞行总时长（max_duration_h，OTA「时长 ≤ N」
范式）+ P3 速修钉（特价 0 价徽标门/到达窗跨零点宣传词面）。

- 门语义：totalDuration 含中转全程；_dur_min 不可解析的行按不满足
  （min_baggage fail-close 同律——时长是筛选目标本体，缺席放行会让
  门对薄行恒真形同虚设）；0=不限（门整体短路）；
- build_routes 漏传防线（配置键整体失效重演判例）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r339j_duration.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402


def _flt(**kw):
    d = {"price": 900, "airlineCode": "MU", "airline": "东方航空",
         "totalDuration": "2时30分"}
    d.update(kw)
    return d


def _route(**kw):
    d = {"from": "SHA", "from_name": "上海", "to": "HAK", "to_name": "海口",
         "dates": ["2027-01-29"], "alert_direct": 1000}
    d.update(kw)
    return main.build_routes([d])[0]


def test_duration_within_limit_passes():
    from core.alerter import Alerter
    rt = _route(max_duration_h=3)
    assert Alerter._route_filters([_flt()], rt)          # 2.5h ≤ 3h
    assert Alerter._route_filters(
        [_flt(totalDuration="3时")], rt)                  # 边界含端


def test_duration_over_limit_dropped():
    from core.alerter import Alerter
    rt = _route(max_duration_h=2)
    assert not Alerter._route_filters([_flt()], rt)       # 2.5h > 2h
    assert not Alerter._route_filters(
        [_flt(totalDuration="5时25分")], rt)
    # 小数小时（0.5 步进语义）：1.5h 门对 2h 行剔除
    rt2 = _route(max_duration_h=1.5)
    assert not Alerter._route_filters([_flt(totalDuration="2时")], rt2)
    assert Alerter._route_filters([_flt(totalDuration="1时20分")], rt2)


def test_duration_zero_is_off():
    from core.alerter import Alerter
    rt = _route()
    assert Alerter._route_filters([_flt(totalDuration="18时")], rt)


def test_duration_unparsable_fail_close():
    """不可解析的行按不满足（fail-close 同律）：门开着时薄行不放行。"""
    from core.alerter import Alerter
    rt = _route(max_duration_h=5)
    assert not Alerter._route_filters([_flt(totalDuration="")], rt)
    assert not Alerter._route_filters([_flt(totalDuration=None)], rt)
    assert Alerter._route_filters(
        [_flt(totalDuration="1时30分")], rt)              # 正常行不受累


def test_build_routes_wires_key():
    rt = _route(max_duration_h=4.5)
    assert rt.max_duration_h == 4.5
    # 漏传防线：缺键归 0（门关闭），不因 KeyError 整卡报废
    rt0 = _route()
    assert rt0.max_duration_h == 0


# ---- PAGE 词面钉 ----

def test_page_duration_row():
    import webui
    src = webui.PAGE
    assert "<b>最长飞行时长</b>" in src
    assert "setRoute(${i},${j},'max_duration_h',this.value)" in src
    assert "渠道未标注时长的班次按不满足剔除" in src
    # saveCfg 越界拦截词面
    assert "最长飞行时长须为 0-72 小时" in src
    # 折叠头 title 词面同步
    assert "最长飞行时长" in src.split("筛选与时段约束")[0] or \
        "价格上限/最长飞行时长" in src


def test_specials_badge_price_gate():
    """P3 速修钉：特价 0 价/缺价=配置未完形，徽标与卡头不得报「开」。"""
    import webui
    src = webui.PAGE
    assert src.count("_spOn=!!(_sp0&&_sp0.enabled!==false&&(_sp0.from||"
                     "_sp0.from_name)&&Number(_sp0.max_price)>0)") == 2
    # 到达窗 hint 跨零点宣传（与出发窗对称）
    assert "支持跨零点</b>，如 22:00–06:00" in src
