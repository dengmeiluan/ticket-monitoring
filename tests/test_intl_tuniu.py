# -*- coding: utf-8 -*-
"""r325 途牛国际分支（A 级直连，调研 _scratch/intl/report_tuniu.md）。

实证基线：国际整条产品线跑在 m2015 老应用，与国内 SPA 分家
（systemId 63/错误族 710000）——国内 710114 登录墙不连坐。本钉锁：

- token 门算法（三层混淆 JS 还原：Σ(charCode×(i+1)) 过程中 >80 则
  -=80，实测错 token=「403 token error」/对 token=正常出询）；
- productList 行 → 统一元素 schema 映射（report §4 页面模板+model
  双重实证：avgTotalPrice 含税口径/avgTax 拆分/跨天日期差自推导/
  transferCity 中转/codeShare 共享）；
- 价带国际宽带（商务舱 >5 万合法）；
- 元素戳 _stamp_intl：intl=1 + 跨区时区对（同区对不落键零污染）。

网络面（列表页 GUID 提取/queryFlight 轮询/needLogin 观察哨）无法
离线钉，按报告 §7 灰度顺序生产 profile 首采定谳。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_intl_tuniu.py
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.tuniu import TuniuCrawler  # noqa: E402

_LOG = logging.getLogger("t_intl_tuniu")
_TN = TuniuCrawler({}, _LOG)


def _row(**over):
    row = {
        "dCityName": "上海", "aCityName": "东京",
        "dPortName": "虹桥国际机场", "aPortName": "成田国际机场",
        "dTerminal": "T1", "aTerminal": "T1",
        "dTime": "2026-11-16 09:30", "aTime": "2026-11-16 14:00",
        "airlineName": "东方航空", "flightNos": "MU523",
        "cabinName": "经济舱", "cabinClass": 1,
        "avgTotalPrice": 2380.0, "avgBasePrice": 1860.0, "avgTax": 520.0,
        "seat": 5, "totalMin": 270,
        "transferCity": "", "stopCity": "", "codeShare": "",
        "tagList": [], "vendorId": "v1",
    }
    row.update(over)
    return row


def _parse(rows):
    return _TN._parse_offers_intl({"productList": rows})


# ---- token 门算法 ----

def test_token_secret_wrap_semantics():
    # 手算钉「>80 则 -=80」逐字符回绕：A(65×1)=65 → +B(66×2)=197>80
    # →117 → +C(67×3)=318>80 → 238
    assert TuniuCrawler._token_secret("ABC") == 238
    assert TuniuCrawler._token_secret("") == 0
    # 报文样本 GUID（report §6）形态可算且稳定
    v = TuniuCrawler._token_secret("E44995ED-31BA-4EF9-A024-7A37C55CBDD1")
    assert isinstance(v, int) and 0 <= v <= 10 ** 9


def test_intl_query_body_request_side_fields():
    # 校准 R1 定谳钉：请求面字段=dCityCode/aCityCode（误用响应回显
    # 字段 dCityIataCode 服务端静默忽略→回显 null→聚合永不完结）
    d = TuniuCrawler._intl_query_body("SHA", "NRT", "2026-11-16", 3, 238)
    assert d["segmentList"][0]["dCityCode"] == "SHA"
    assert d["segmentList"][0]["aCityCode"] == "NRT"
    assert d["segmentList"][0]["departDate"] == "2026-11-16"
    assert "dCityIataCode" not in d["segmentList"][0]
    assert "aCityIataCode" not in d["segmentList"][0]
    # 空槽必带（probe7 成功样本同构）+ 拍号/token 透传
    assert d["selectFlightNos"] == "" and d["distributeId"] == ""
    assert d["pollTag"] == 3 and d["token"] == 238 and d["systemId"] == 63


# ---- productList 行映射 ----

def test_parse_row_mapping():
    rows = _parse([_row()])
    assert len(rows) == 1
    r = rows[0]
    # 含税口径（avgTotalPrice）+ 税费拆分透传
    assert r["price"] == 2380.0
    assert r["tax"] == 520.0
    assert r["barePrice"] == 1860.0
    assert r["code"] == "MU523"
    assert r["name"] == "东方航空MU523"
    assert r["airline"] == "东方航空"
    assert r["airlineCode"] == "MU"
    assert r["depTime"] == "09:30" and r["arrTime"] == "14:00"
    assert r["depDate"] == "2026-11-16" and r["arrDate"] == "2026-11-16"
    assert r["cabin"] == "经济舱"
    assert r["leftTickets"] == 5
    assert r["totalDuration"] == "4时30分"
    assert r["depTerminal"] == "T1" and r["arrTerminal"] == "T1"
    assert r["depAirport"] == "虹桥国际机场"
    # 直飞行不落中转/经停/跨天键（无值不落键同族律）
    assert "transCity" not in r and "stopCitys" not in r
    assert "crossDayDesc" not in r and "shareCarrier" not in r


def test_parse_intl_wide_band():
    # 商务舱 >5 万国际合法（宽带 200000）；下界不放宽（垃圾价剔）
    assert _parse([_row(avgTotalPrice=60000.0)])[0]["price"] == 60000.0
    assert _parse([_row(avgTotalPrice=99.0)]) == []
    # 非法价行剔（宁缺勿错）
    assert _parse([_row(avgTotalPrice=None)]) == []


def test_parse_transfer_and_multiseg():
    rows = _parse([_row(transferCity="东京", flightNos="MU523-NH960",
                        dPortName="虹桥国际机场")])
    assert rows[0]["transCity"] == "东京"
    assert rows[0]["code"] == "MU523/NH960"
    multi = _parse([_row(transferCity="东京|首尔")])[0]
    assert multi["transCity"] == "东京/首尔"


def test_parse_cross_day_derived():
    # 渠道无跨天字段（report §4）：dTime/aTime 日期差自推导
    r = _parse([_row(aTime="2026-11-17 02:10")])[0]
    assert r["crossDayDesc"] == "+1天"
    r2 = _parse([_row(aTime="2026-11-21 02:10")])[0]
    assert r2["crossDayDesc"] == "+5天"


def test_parse_stop_and_codeshare():
    r = _parse([_row(stopCity="烟台")])[0]
    assert r["stopCitys"] == "烟台"


# ---- r326 国际四增量（channel_tuniu_tc_fliggy.md §2，dump 62 行 +
#      DB 253 元素双源实证）----

def test_intl_layover_from_transmin():
    # transMin 按段结构化真值：段[0] 恒 '0'、段[i]=第 i 跳衔接停留
    # （dump 3 段行 [0,485,570] 与 transferCity 分段逐一对应定谳）；
    # 形状门=段数-1==转点数 且全数字（国内 transferPoints 同门），
    # 求和落 layover + layoverSrc=transInfo 真值源标（豁免族同标）
    r = _parse([_row(transferCity="开罗", flightNos="MU523-MS917",
                     segmentList=[
                         {"flightNo": "MU523", "transMin": "0"},
                         {"flightNo": "MS917", "transMin": "485"}])])[0]
    assert r["layover"] == 485
    assert r["layoverSrc"] == "transInfo"
    # 整数 0 形态（冻结 dump 实证：段[0].transMin=0 整数非 '0' 串）：
    # None 门放行 0 真值，truthy 门会吞成空串令形状门恒败
    r0 = _parse([_row(transferCity="开罗", flightNos="MU523-MS917",
                      segmentList=[
                          {"flightNo": "MU523", "transMin": 0},
                          {"flightNo": "MS917", "transMin": 485}])])[0]
    assert r0["layover"] == 485


def test_intl_layover_multiseg_sum_and_shape_gate():
    # 3 段行求和（485+570）；转点数≠段数-1 或非数字形态不落（宁缺勿错）
    r = _parse([_row(transferCity="曼谷|马斯喀特",
                     flightNos="MU547-WY818-WY407",
                     segmentList=[
                         {"flightNo": "MU547", "transMin": "0"},
                         {"flightNo": "WY818", "transMin": "485"},
                         {"flightNo": "WY407", "transMin": "570"}])])[0]
    assert r["layover"] == 1055
    bad_shape = _parse([_row(transferCity="曼谷",
                             flightNos="MU547-WY818-WY407",
                             segmentList=[
                                 {"flightNo": "MU547", "transMin": "0"},
                                 {"flightNo": "WY818", "transMin": "485"},
                                 {"flightNo": "WY407", "transMin": "570"}])])
    assert "layover" not in bad_shape[0]
    bad_form = _parse([_row(transferCity="开罗", flightNos="MU523-MS917",
                            segmentList=[
                                {"flightNo": "MU523", "transMin": "0"},
                                {"flightNo": "MS917", "transMin": ""}])])
    assert "layover" not in bad_form[0]
    # 直飞行（无 segmentList/transMin）不落
    assert "layover" not in _parse([_row()])[0]


def test_intl_planesize_from_craftwidth():
    # seg0 craftWidthType 有值才落（渠道间歇下发，'' 不落不做推断）
    r = _parse([_row(segmentList=[
        {"flightNo": "MU523", "craftWidthType": "大型机"}])])[0]
    assert r["planeSize"] == "大型机"
    assert "planeSize" not in _parse([_row(segmentList=[
        {"flightNo": "MU523", "craftWidthType": ""}])])[0]
    assert "planeSize" not in _parse([_row()])[0]


def test_intl_plane_detail_first_chain():
    # craftTypeDetail 主源（dump 62/62 在场且更细'波音777-300ER'），
    # 缺时落 craftTypeName 旧源（65%，同槽兜底）
    r = _parse([_row(segmentList=[
        {"flightNo": "MU523", "craftTypeName": "波音777",
         "craftTypeDetail": "波音777-300ER"}])])[0]
    assert r["plane"] == "波音777-300ER"
    r2 = _parse([_row(segmentList=[
        {"flightNo": "MU523", "craftTypeName": "波音777"}])])[0]
    assert r2["plane"] == "波音777"
    assert "plane" not in _parse([_row()])[0]


def test_intl_sharecarrier_direct_landing():
    # 门型错配修复：codeShare 真值=执飞航班号串（dump 'MS917'×7，
    # 非 '1/TRUE/Y/T' 布尔）——照国内 codeShare or sAirComName 直落
    r = _parse([_row(codeShare="MS917", sAirComName="埃及航空")])[0]
    assert r["shareCarrier"] == "MS917"
    # 旧布尔门对 '1' 串恒假=共享信息永久丢失（0/253 实锤）——直落后
    # 同串照落（值域哨盯渠道改版，不重设布尔门）
    r2 = _parse([_row(codeShare="1", segmentList=[
        {"flightNo": "MU523", "airComName": "东方航空"}])])[0]
    assert r2["shareCarrier"] == "1"
    # codeShare 缺 → sAirComName 兜底（国内同款互补）
    r3 = _parse([_row(codeShare="", sAirComName="埃及航空")])[0]
    assert r3["shareCarrier"] == "埃及航空"
    assert "shareCarrier" not in _parse([_row()])[0]


# ---- 元素戳 ----

def test_stamp_intl_flags_and_tz():
    flights = [{}]
    _TN._stamp_intl(flights, "SHA", "NRT")
    assert flights[0]["intl"] == 1
    assert flights[0]["tz_dep"] == 480 and flights[0]["tz_arr"] == 540


def test_stamp_intl_same_zone_no_tz_keys():
    # 同区对（SHA→HKG 均 UTC+8）：朴素差本就正确，不落键零污染
    flights = [{}]
    _TN._stamp_intl(flights, "SHA", "HKG")
    assert flights[0]["intl"] == 1
    assert "tz_dep" not in flights[0] and "tz_arr" not in flights[0]


# ---- R40b ret_date 签名钉（98081b0 半链 TypeError 生产实锤）----

def test_intl_fetch_accepts_ret_date():
    """fetch→_fetch_intl 传 ret_date=（R15 往返一期调用形态），签名
    缺参=每轮 TypeError：unexpected keyword argument 'ret_date'
    （生产 21:02/21:24/21:46/22:00 四连实锤）。"""
    import inspect
    assert "ret_date" in inspect.signature(
        TuniuCrawler._fetch_intl).parameters
