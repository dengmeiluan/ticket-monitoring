# -*- coding: utf-8 -*-
"""r341 航线卡智能筛选四门 + 航司排除语法 + 全局配置透明化钉：
① price_max 价格上限（fail-open：票价不可解析保留——票价是行主体，
   缺席剔除会整渠道误杀，与 min_baggage fail-close 异律）
② no_cross 排除跨天（crossDayN 由 normalize 恒落键，全渠道普适）
③ arr_time_min/max 到达时段窗（与出发窗同构；arrTime 缺席保留）
④ airlines `!` 排除语法（先排除后白名单，两表独立判定）
+ _OPEN_KEYS bdir（空=系统默认位→None）+ PAGE 绝对路径展示消费面。
"""
import main
import webui
from core.alerter import Alerter


def _flt(**kw):
    d = {"price": 900, "airlineCode": "MU", "airline": "东方航空",
         "lcc": False, "baggage": "免费托运20kg", "planeSize": "大型机",
         "crossDayN": 0, "depTime": "08:00", "arrTime": "11:00"}
    d.update(kw)
    return d


def _route(**kw):
    d = {"from": "SHA", "from_name": "上海", "to": "PEK", "to_name": "北京",
         "dates": ["2027-01-29"], "alert_direct": 1000}
    d.update(kw)
    return main.build_routes([d])[0]


# ---- ① price_max ----

def test_price_max_filters_above_and_keeps_unparsable():
    rt = _route(price_max=1000)
    assert Alerter._route_filters([_flt(price=999)], rt)
    assert not Alerter._route_filters([_flt(price=1001)], rt)
    assert Alerter._route_filters([_flt(price=1000)], rt)   # 恰等保留
    # fail-open：票价不可解析的行保留（缺席剔除=整渠道误杀）
    assert Alerter._route_filters([_flt(price="")], rt)
    assert Alerter._route_filters([_flt(price=None)], rt)
    rt0 = _route()
    assert Alerter._route_filters([_flt(price=99999)], rt0)  # 0=不限
    # build_routes 从 dict 键透传（配置链同源）
    assert _route(price_max="800").price_max == 800.0


# ---- ② no_cross ----

def test_no_cross_filters_crossday():
    rt = _route(no_cross=True)
    assert not Alerter._route_filters([_flt(crossDayN=1)], rt)
    assert not Alerter._route_filters([_flt(crossDayN=2)], rt)
    assert Alerter._route_filters([_flt(crossDayN=0)], rt)
    assert Alerter._route_filters([_flt()], rt)             # 缺席=0
    assert Alerter._route_filters([_flt(crossDayN=1)], _route())


# ---- ③ 到达时段窗 ----

def test_arr_window():
    rt = _route(arr_time_min="06:00", arr_time_max="12:00")
    assert Alerter._route_filters([_flt(arrTime="09:30")], rt)
    assert not Alerter._route_filters([_flt(arrTime="23:40")], rt)  # 红眼
    # 跨午夜窗（22:00–02:00）：环形判定
    rt2 = _route(arr_time_min="22:00", arr_time_max="02:00")
    assert Alerter._route_filters([_flt(arrTime="23:30")], rt2)
    assert Alerter._route_filters([_flt(arrTime="01:10")], rt2)
    assert not Alerter._route_filters([_flt(arrTime="12:00")], rt2)
    # arrTime 缺席保留（与 widebody 同律：薄行无从判定不误杀）
    assert Alerter._route_filters([_flt(arrTime="")], rt)
    # 单端窗
    assert not Alerter._route_filters(
        [_flt(arrTime="05:00")], _route(arr_time_min="06:00"))
    assert Alerter._route_filters(
        [_flt(arrTime="23:00")], _route(arr_time_max="23:59"))


# ---- ④ airlines `!` 排除语法 ----

def test_airlines_bang_exclusion():
    rt = _route(airlines="!9C,!春秋")
    assert Alerter._route_filters([_flt()], rt)                       # 非排除项保留
    assert not Alerter._route_filters(
        [_flt(airlineCode="9C", airline="春秋航空")], rt)             # 码命中排除
    assert not Alerter._route_filters(
        [_flt(airlineCode="HO", airline="春秋航空")], rt)             # 名称片段命中排除
    # 排除+白名单并存：先排除后白名单
    rt2 = _route(airlines="MU,!9C")
    assert Alerter._route_filters([_flt()], rt2)
    assert not Alerter._route_filters(
        [_flt(airlineCode="9C", airline="春秋航空")], rt2)
    assert not Alerter._route_filters(
        [_flt(airlineCode="CZ", airline="南方航空")], rt2)            # 白名单仍生效
    # 纯排除=其余全保（无白名单语义）
    assert Alerter._route_filters(
        [_flt(airlineCode="CZ", airline="南方航空")], rt)


# ---- 全局配置透明化：_OPEN_KEYS bdir + 绝对路径消费面 ----

def test_open_keys_bdir_none_when_empty():
    # 空=系统默认 playwright 缓存位（非本仓可控路径）→ None，
    # 端点按「未自定义」回执，防打开仓库根误导
    assert webui._open_folder_target("bdir", {"crawler": {"browser_dir": ""}}) is None
    assert webui._open_folder_target("bdir", {"crawler": {"browser_dir": "D:/pw-cache"}})
    assert webui._OPEN_KEYS["bdir"]({"crawler": {}}) is None
    # 既有三键不回退
    assert webui._open_folder_target("db", {"output": {"db_path": "data/prices.db"}})


def test_page_consumes_globals_abs_and_route_gates():
    # PAGE 词面钉：绝对路径展示/新增筛选行/快捷挡/卡头摘要词面防回退
    for token in ("globals_abs", "glAbs(", "→ 绝对路径：",
                  "价格上限", "排除跨天", "到达时段窗口",
                  "quickArr", "customArrWin",
                  "到达':'", "!9C,!春秋", 'data-which="bdir"',
                  "系统默认 playwright 缓存位"):
        assert token in webui.PAGE, token
