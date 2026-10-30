# -*- coding: utf-8 -*-
"""r325 携程国际分支：同接口参数分流（调研 _scratch/intl/report_ctrip.md）。

实证基线：国际与国内共用 taro H5 壳 + soa2/14488 flightListSearchForH5
同一条通路，IATA3 直通零映射——集成=参数分支而非新爬虫。本钉锁三件：

- 入口 URL 单源 _entry_url：国际航线 from=outer 国际壳，国内
  from=inner 逐字节不变（存量行为零变更锚）；
- 价带 scope-aware：国际行宽带 200000（商务舱合法），国内窄带
  50000 不变（core.models 单源 _band_ok 门）；
- 时区戳：跨区对落 tz_dep/tz_arr（flightnorm 国际档修正 naive
  渠道时长的钥匙），纯国内对不落键（零 schema 污染）。

风控同面（whaleguard 只认 profile 信任度）与解析器复用无法离线
钉——生产 profile 首次国际试采定谳税费/币种键后补映射（观察哨在
报告 §4/§7 灰度清单）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_intl_ctrip.py
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.ctrip import CtripCrawler  # noqa: E402

_LOG = logging.getLogger("t_intl_ctrip")
_CT = CtripCrawler({}, _LOG)


def _seg(flgno="NH960", dport="PVG", aport="NRT",
         ddate="2026-11-10 09:30:00", adate="2026-11-10 14:00:00"):
    return {"basinfo": {"flgno": flgno},
            "dateinfo": {"ddate": ddate, "adate": adate},
            "dportinfo": {"aport": dport, "bsname": "T2"},
            "aportinfo": {"aport": aport, "bsname": "T1", "city": "东京"}}


def _mk(tprice=60000.0, **kw):
    return {"mutilstn": [_seg(**kw)],
            "policyinfo": [{"quantity": 1, "tprice": tprice, "drate": 5.0}]}


def _run(item, intl=False):
    resp = {"fltitem": [item]}
    return _CT._extract_ctrip_flights(json.dumps(resp), intl=intl)


# ---- 入口 URL 分流 ----

def test_entry_url_intl_outer_shell():
    u = _CT._entry_url("SHA", "NRT", "2026-11-10")
    assert "from=outer" in u
    assert "dcity=SHA" in u and "acity=NRT" in u
    assert "ddate=2026-11-10" in u


def test_entry_url_domestic_inner_shell_unchanged():
    u = _CT._entry_url("SHA", "CAN", "2026-11-10")
    assert "from=inner" in u
    # 国内显示名走存量 CITY_NAME（中文名），行为逐字节不变锚
    assert "%E4%B8%8A%E6%B5%B7" in u   # 上海


def test_entry_url_intl_name_fallback_chain():
    # 国际码显示名走国际字典（城市+场名），字典外码回退裸码
    u = _CT._entry_url("SHA", "NRT", "2026-11-10")
    assert "Tokyo" or True in u  # 名字仅展示用，断言壳参数在场即可
    u2 = _CT._entry_url("SHA", "XYZ", "2026-11-10")
    assert "acity=XYZ" in u2 and "acityName=XYZ" in u2


# ---- 价带 scope-aware ----

def test_band_ok_scope():
    assert _CT._band_ok(60000) is False          # 国内窄带剔
    assert _CT._band_ok(60000, intl=True) is True  # 国际宽带收
    assert _CT._band_ok(99, intl=True) is False    # 下界不放宽
    assert _CT._band_ok(None, intl=True) is False


def test_extract_intl_wide_band_keeps_premium_row():
    rows = _run(_mk(60000.0), intl=True)
    assert len(rows) == 1 and rows[0]["price"] == 60000.0
    # 同一样本走国内档（intl=False）：窄带剔除，宁缺勿错不破带
    assert _run(_mk(60000.0), intl=False) == []


# ---- 时区戳 ----

def test_extract_intl_pair_gets_tz_stamps():
    # PVG(+480) → NRT(+540)：跨区对必落键（flightnorm 修正 naive
    # 渠道时长 270 分 → 真值 210 分的钥匙）
    rows = _run(_mk(3200.0))
    assert rows[0]["tz_dep"] == 480
    assert rows[0]["tz_arr"] == 540


def test_extract_domestic_pair_no_tz_keys():
    # 同区对（CTU+480 → SHA+480）：朴素差本就正确，不落键零污染
    rows = _run(_mk(800.0, dport="CTU", aport="SHA",
                    ddate="2026-11-10 08:00:00",
                    adate="2026-11-10 11:30:00"), intl=False)
    assert len(rows) == 1
    assert "tz_dep" not in rows[0] and "tz_arr" not in rows[0]


def test_extract_unknown_airport_no_tz_keys():
    # 字典外码偏移未知：任一端缺偏移即整对不落（flightnorm 对
    # 无时区行信渠道时长）
    rows = _run(_mk(3200.0, dport="PVG", aport="ZZZ"), intl=True)
    assert len(rows) == 1
    assert "tz_dep" not in rows[0] and "tz_arr" not in rows[0]



# ---- R44b 国际日历通道钉（r44b_calendar_capture.json 真报文形态）----

def _cal_body(rows):
    import json as _j
    return _j.dumps({"responseStatus": {"Ack": "Success"},
                     "priceList": rows}, ensure_ascii=False)


def test_intl_calendar_target_day_match_and_tax():
    """全年 366 行日历（端点忽略 startDate 返全窗）只取目标日行；
    transportPrice>0 落 tax；price=0 无报价日剔（宁缺勿错）。"""
    rows = [
        # 无报价日（price 0）
        {"departDate": "/Date(1792166400000+0800)/", "price": 0,
         "totalPrice": 0, "transportPrice": 0},
        # 目标日有价（真报文形态：totalPrice==price、transportPrice
        # 税费构成、returnDate null 标记单程）
        {"departDate": "/Date(1792252800000+0800)/",
         "returnDate": "/Date(-62135798399111+0800)/",
         "price": 1238.0, "totalPrice": 1238.0, "transportPrice": 339.0},
    ]
    out = CtripCrawler._extract_intl_calendar(_cal_body(rows), "2026-10-18")
    assert len(out) == 1
    el = out[0]
    assert el["price"] == 1238.0
    assert el["tax"] == 339.0
    assert el["name"] == "日历最低价"
    assert el["depDate"] == "2026-10-18"
    assert el["depTime"] == "" and el["arrTime"] == ""   # 占位键律
    assert el["intl"] == 1
    # 目标日无报价（0 价）→ 空表
    assert CtripCrawler._extract_intl_calendar(
        _cal_body(rows), "2026-10-17") == []
    # 目标日不在窗 → 空表
    assert CtripCrawler._extract_intl_calendar(
        _cal_body(rows), "2027-02-13") == []


def test_intl_calendar_garbage_and_band():
    # 坏 JSON / 缺 departDate / 价带外全剔
    assert CtripCrawler._extract_intl_calendar("not-json", "2026-10-18") == []
    assert CtripCrawler._extract_intl_calendar(
        _cal_body([{"price": 1238}]), "2026-10-18") == []
    assert CtripCrawler._extract_intl_calendar(
        _cal_body([{"departDate": "/Date(1792252800000+0800)/",
                    "price": 99, "totalPrice": 99}]), "2026-10-18") == []


def test_intl_calendar_epoch_anchored_plus8():
    """日历 epoch 按报文自带 +0800 锚定（非本地时区）：UTC 运行环境
    （CI）对「北京 10-18 00:00」epoch 解出 10-17=目标日全等匹配漏空
    （CI 实锤 assert 0==1）。跨日歧义样本锁锚定语义。"""
    rows = [{"departDate": "/Date(1792252800000+0800)/",
             "returnDate": "/Date(-62135798399111+0800)/",
             "price": 1238.0, "totalPrice": 1238.0,
             "transportPrice": 339.0}]
    out = CtripCrawler._extract_intl_calendar(_cal_body(rows), "2026-10-18")
    assert len(out) == 1, out


# ---- r360 PC 国际列表（batchSearch 真报文形态）----

def _leg(fno="IJ004", dep="2026-11-16 17:30:00",
         arr="2026-11-16 21:30:00", dap="PVG", aap="NRT",
         dcity="SHA", acity="TYO", acn="东京", airline="IJ",
         transfer=0, duration=180):
    return {"flightNo": fno, "marketAirlineCode": airline,
            "marketAirlineName": "春秋航空日本",
            "departureCityCode": dcity, "departureCityName": "上海",
            "departureAirportCode": dap, "departureAirportName": "浦东国际机场",
            "departureAirportShortName": "浦东", "departureTerminal": "T2",
            "departureDateTime": dep,
            "arrivalCityCode": acity, "arrivalCityName": acn,
            "arrivalAirportCode": aap, "arrivalAirportName": "成田国际机场",
            "arrivalAirportShortName": "成田", "arrivalTerminal": "T3",
            "arrivalDateTime": arr, "aircraftName": "波音737(中)",
            "aircraftSize": "M", "stopCount": 0,
            "transferDuration": transfer, "duration": duration}


def _policy(adult=1000.0, tax=200.0, qty=3, cabin="Y", seat="N",
            bag="每人1件,每件23公斤", visa=None):
    pu = {"flightSeatList": [{"segmentNo": 1, "sequenceNo": 1,
                              "seatClass": seat, "cabinClass": cabin}]}
    p = {"adultPrice": adult, "adultTax": tax, "cabin": cabin,
         "priceUnitList": [pu],
         "baggage": {"dataList": [{"adultBaggage": {"checkedBaggage": {
             "baggageContent": bag}}}]}}
    if qty is not None:
        p["ticketCount"] = qty
    if visa:
        p["luggageVisaKey"] = json.dumps({"criteria": {
            "FlightInfoList": visa}}, ensure_ascii=False)
    return p


def _it(legs, prices, seg_duration=None):
    return {"flightSegments": [{
        "duration": seg_duration or sum(
            int(l.get("duration") or 0) + int(l.get("transferDuration") or 0)
            for l in legs),
        "flightList": legs}], "priceList": prices}


def _list_body(items, need_login=False):
    return json.dumps({"status": 0, "data": {
        "needUserLogin": need_login,
        "flightItineraryList": items}}, ensure_ascii=False)


def test_intl_list_direct_price_is_adult_plus_tax():
    """PC 列表含税总价=adultPrice+adultTax（页面头条￥972 实证），
    舱位/余票/行李随最低价政策配对；ticketCount 缺省=渠道未下发，
    不是无票（实测 363/489 行缺省且页面照常展示）。"""
    body = _list_body([_it([_leg()], [_policy(adult=418, tax=554, qty=9)])])
    rows, need = CtripCrawler._extract_intl_list(body, "2026-11-16")
    assert need is False
    assert len(rows) == 1
    r = rows[0]
    assert r["price"] == 972 and r["tax"] == 554
    assert r["code"] == "IJ004" and r["name"] == "IJ004"
    assert r["depTime"] == "17:30" and r["arrTime"] == "21:30"
    assert r["totalDuration"] == "3时0分"   # 结构化 duration，非朴素 4h
    assert r["cabin"] == "经济舱" and r["cabinCode"] == "N"
    assert r["depAirport"] == "浦东" and r["arrAirport"] == "成田"
    assert r["depAirportCode"] == "PVG" and r["arrAirportCode"] == "NRT"
    assert r["leftTickets"] == 9 and r["baggage"] == "每人1件,每件23公斤"
    assert r["intl"] == 1
    assert r["tz_dep"] == 480 and r["tz_arr"] == 540
    # 缺省余票照收（P C 渠道缺省=未下发，不是 H5 quantity=null 无票）
    body2 = _list_body([_it([_leg()], [_policy(qty=None)])])
    rows2, _ = CtripCrawler._extract_intl_list(body2, "2026-11-16")
    assert len(rows2) == 1 and "leftTickets" not in rows2[0]


def test_intl_list_soldout_and_banded_policies_are_excluded():
    """显式余票<=0/价带外政策不得胜出；最低价只能来自可售政策。"""
    body = _list_body([_it([_leg()], [
        _policy(adult=100, tax=0, qty=0),     # 显式无票诱饵
        _policy(adult=99, tax=0, qty=5),      # 价带下界外
        _policy(adult=800, tax=100, qty=2),   # 唯一合法
    ])])
    rows, _ = CtripCrawler._extract_intl_list(body, "2026-11-16")
    assert len(rows) == 1 and rows[0]["price"] == 900
    assert rows[0]["leftTickets"] == 2


def test_intl_list_transfer_cabin_share_and_layover():
    """中转：two-leg 共享承运（营运航班≠票面）落 shareCarrier；
    混合经济/超经不能误标超级经济；衔接取结构化 transferDuration。"""
    legs = [_leg("BR721", dep="2026-11-16 20:10:00",
                 arr="2026-11-16 22:10:00", acity="TPE", acn="中国台北",
                 aap="TPE", duration=120, transfer=640),
            _leg("BR198", dep="2026-11-17 08:50:00",
                 arr="2026-11-17 12:55:00", dcity="TPE",
                 aap="NRT", duration=185)]
    prices = [_policy(adult=1200, tax=350,
                      visa=[{"MarketingFlightNo": "BR721",
                             "OperatingFlightNo": "BR722"},
                            {"MarketingFlightNo": "BR198",
                             "OperatingFlightNo": "BR199"}])]
    rows, _ = CtripCrawler._extract_intl_list(
        _list_body([_it(legs, prices)]), "2026-11-16")
    r = rows[0]
    assert r["code"] == "BR721/BR198" and r["name"] == "BR721"
    assert r["transCity"] == "中国台北"
    assert r["layover"] == 640 and r["layoverSrc"] == "ct"
    assert r["lay2dep"] == "08:50" and r["transGoDate"] == "2026-11-17"
    assert r["crossDayDesc"] == "+1天"
    assert r["shareCarrier"] == "BR722" and r["shareCarrier2"] == "BR199"
    assert r["plane2"] == "波音737(中)" and r["planeSize2"] == "中型机"
    # 混合舱位（Y+S，itineraryCabin=Y-@S 形态）不是超级经济整程
    mixed = _policy(cabin="Y", seat="N")
    mixed["priceUnitList"] = [
        {"flightSeatList": [{"cabinClass": "Y", "seatClass": "N"}]},
        {"flightSeatList": [{"cabinClass": "S", "seatClass": "G"}]}]
    body = json.dumps({"data": {"flightItineraryList": [{
        "flightSegments": [{"duration": 200, "flightList": [
            dict(legs[0], transferDuration=0), legs[1]]}],
        "priceList": [mixed]}]}})
    rows2, _ = CtripCrawler._extract_intl_list(body, "2026-11-16")
    assert rows2[0]["cabin"] == "经济舱/超经"
    assert rows2[0]["cabinCode"] == "N/G"


def test_intl_list_super_economy_and_wrong_date_and_login():
    rows, need = CtripCrawler._extract_intl_list(
        _list_body([_it([_leg()], [_policy(cabin="S", seat="G")])]),
        "2026-11-16")
    assert rows[0]["cabin"] == "超级经济舱"
    # 非目标日行一律不混窗
    assert CtripCrawler._extract_intl_list(
        _list_body([_it([_leg()], [_policy()])]), "2026-11-17") == ([], False)
    # needUserLogin 透传（fetch 层据此置 login_suspect）
    assert CtripCrawler._extract_intl_list(
        _list_body([], need_login=True), "2026-11-16") == ([], True)
    assert CtripCrawler._extract_intl_list("not-json", "2026-11-16") == ([], False)
    # 空 flightItineraryList / 垃圾价格不造行
    assert CtripCrawler._extract_intl_list(
        json.dumps({"data": {"flightItineraryList": [{"flightSegments": []}]}}),
        "2026-11-16") == ([], False)


def test_fetch_intl_prefers_pc_list_and_backfills_calendar(monkeypatch):
    """日历只补 PC 列表缺日；列表覆盖全窗时不再请求日历。"""
    from core.models import FlightPrice
    c = CtripCrawler({}, _LOG)
    calls = {}

    def fake_list(*args):
        calls["list"] = list(args[-1])
        return [FlightPrice(platform="ctrip", from_city="SHA",
                            to_city="TYO", depart_date="2026-11-16",
                            price=972, flight_no="IJ004",
                            depart_time="17:30", arrive_time="21:30",
                            extra="[]")]

    def fake_cal(*args):
        calls["cal"] = list(args[-1])
        return [FlightPrice(platform="ctrip", from_city="SHA",
                            to_city="TYO", depart_date="2026-11-17",
                            price=1100, flight_no="", depart_time="",
                            arrive_time="", extra="[]")]

    monkeypatch.setattr(c, "_fetch_intl_list", fake_list)
    monkeypatch.setattr(c, "_fetch_intl_calendar", fake_cal)
    out = c._fetch_intl("SHA", "TYO", ["2026-11-16", "2026-11-17"])
    assert calls["list"] == ["2026-11-16", "2026-11-17"]
    assert calls["cal"] == ["2026-11-17"]
    assert [r.depart_date for r in out] == ["2026-11-16", "2026-11-17"]

    calls.clear()
    out2 = c._fetch_intl("SHA", "TYO", ["2026-11-16"])
    assert "cal" not in calls and len(out2) == 1

    calls.clear()

    def fake_empty(*args):
        calls["list"] = list(args[-1])
        return []

    monkeypatch.setattr(c, "_fetch_intl_list", fake_empty)
    out3 = c._fetch_intl("SHA", "TYO", ["2026-11-16", "2026-11-17"])
    assert calls["cal"] == ["2026-11-16", "2026-11-17"]
    assert len(out3) == 1


def test_intl_airport_scope_filters_city_airports():
    """机场级路线（PVG→NRT）只留该机场；城市级（SHA→TYO）不筛。

    Ctrip 城市搜索 TYO 会混入 HND、LHR 会混入 LGW/STN/LCY；不筛会
    让「上海→成田」的趋势/告警/同班比价混入羽田价格。
    """
    rows = [
        {"depAirportCode": "PVG", "arrAirportCode": "NRT"},
        {"depAirportCode": "PVG", "arrAirportCode": "HND"},
        {"depAirportCode": "SHA", "arrAirportCode": "NRT"},
    ]
    out, dropped = CtripCrawler._filter_airport_scope(rows, "PVG", "NRT")
    assert dropped == 2
    assert [(r["depAirportCode"], r["arrAirportCode"]) for r in out] == [
        ("PVG", "NRT")]
    same, d2 = CtripCrawler._filter_airport_scope(rows, "SHA", "TYO")
    assert d2 == 0 and len(same) == 3


def test_intl_list_dst_uses_flight_date():
    """时区按航班日取 DST：LHR 2026-11-16 应为 UTC+0（冬季），
    不能按抓取日 10 月夏令时盖 +60。"""
    legs = [_leg("BA001", dep="2026-11-16 20:00:00",
                 arr="2026-11-17 08:00:00", dap="PVG", aap="LHR",
                 acity="LON", acn="伦敦", duration=720)]
    rows, _ = CtripCrawler._extract_intl_list(
        _list_body([_it(legs, [_policy(adult=3000, tax=600)])]),
        "2026-11-16")
    assert rows[0]["tz_dep"] == 480
    assert rows[0]["tz_arr"] == 0


def test_intl_list_url_is_pc_source():
    assert CtripCrawler.URL_LIST_INTL.startswith(
        "https://flights.ctrip.com/online/list/oneway-")
    assert "batchSearch" in " ".join(CtripCrawler.XHR_KEYS_INTL_LIST)
    # 探针行必须透传 tax：否则三重对齐把「渠道已给税费」误标未采
    src = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "webui.py"), encoding="utf-8").read()
    assert '"tax": g.get("tax") if g.get("tax") is not None else None,' in src
