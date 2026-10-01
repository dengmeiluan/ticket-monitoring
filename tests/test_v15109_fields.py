# -*- coding: utf-8 -*-
"""渠道五新键（渠道调研移交）：qunar distance/airlineCode/shareAirline +
tuniu airlineCode/stdFare，三端同轮（爬虫读层 → webui 透传白名单 →
渲染门/CSV）+ _propagate_fields 物理属性列表扩展。

样本形态取自生产 dump 实证（渠道调研 B 报告：qunar binfo.distance
73/73+66/66 全场「3649」串、binfo.shortCarrier 二字码全场、
mainCarrierShortName 与 codeShare 行精确同步；tuniu
detail.airlineIataCode 45/45+46/46 全场、fareBreakdownList
.bcTaxExclusiveFare ADT 正值 56%/-1 占位 44%，baseFare=bcTax×1.01
恒系数互证）。debug/ 不入库，测试在无该文件的干净环境可跑。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15109_fields.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.base import iata2  # noqa: E402
from crawlers.qunar import QunarCrawler  # noqa: E402
from crawlers.tuniu import TuniuCrawler  # noqa: E402


# ---- iata2 航司二字码守卫（iata3 同款，qunar/tuniu 跨渠道统一键） ----

def test_iata2_guard():
    assert iata2("MU") == "MU"
    assert iata2("3U") == "3U"
    # 小写/三位/空/非字母数字一律挡（宁缺勿错）
    assert iata2("mu") == ""
    assert iata2("MUU") == ""
    assert iata2("") == ""
    assert iata2(None) == ""
    assert iata2("M1") == "M1"


# ---- qunar PC：distance / airlineCode / shareAirline ----

def _pc_sample(binfo_extra=None, codeshare=False):
    b1 = {"airCode": "FM9223", "shortName": "上航", "shortCarrier": "FM",
          "depTime": "19:55", "arrTime": "01:25",
          "date": "2026-10-04", "arrDate": "2026-10-05",
          "distance": "3649"}
    if binfo_extra:
        b1.update(binfo_extra)
    row = {"code": "FM9223", "minPrice": "2472", "transCity": "",
           "extparams": {}, "binfo": b1}
    if codeshare:
        row["code"] = "FM9223"
        b1["codeShare"] = True
        b1["mainCarrier"] = "FM9224"
        b1["mainCarrierShortName"] = "上航"
    return json.dumps({"ret": True, "code": 0,
                       "data": {"flights": [row]}})


def test_qunar_pc_distance_and_airline_code():
    fl = QunarCrawler._parse_pc_flights(_pc_sample(), "2026-10-04")
    assert fl and fl[0]["distance"] == 3649          # int 协议
    assert fl[0]["airlineCode"] == "FM"


def test_qunar_pc_distance_guards():
    # "0"/负数/非数字不落键（数值协议无值不落键律，同 avgDelay）
    for bad in ("0", "-5", "abc", ""):
        fl = QunarCrawler._parse_pc_flights(
            _pc_sample({"distance": bad}), "2026-10-04")
        assert fl and "distance" not in fl[0], bad
    # 键缺席同口径
    fl = QunarCrawler._parse_pc_flights(
        _pc_sample({"distance": None}), "2026-10-04")
    assert fl and "distance" not in fl[0]


def test_qunar_pc_airline_code_guard():
    # 非二字码形态（小写/超长）守卫落空串（str 协议同 depAirportCode）
    fl = QunarCrawler._parse_pc_flights(
        _pc_sample({"shortCarrier": "mu"}), "2026-10-04")
    assert fl and fl[0]["airlineCode"] == ""
    fl2 = QunarCrawler._parse_pc_flights(
        _pc_sample({"shortCarrier": "MUU"}), "2026-10-04")
    assert fl2 and fl2[0]["airlineCode"] == ""


def test_qunar_pc_share_airline_gate():
    # 共享承运航司名：与 shareCarrier 同门（codeShare + mainCarrier≠airCode）
    fl = QunarCrawler._parse_pc_flights(_pc_sample(codeshare=True),
                                        "2026-10-04")
    assert fl and fl[0]["shareAirline"] == "上航"
    assert fl[0]["shareCarrier"] == "FM9224"
    # 非共享行：shareAirline 无值不落键（r239 空串落键收口），
    # shareCarrier 同门仍空串直落（留观）
    fl2 = QunarCrawler._parse_pc_flights(_pc_sample(), "2026-10-04")
    assert (fl2 and "shareAirline" not in fl2[0]
            and "shareCarrier" not in fl2[0])


# ---- tuniu：airlineCode / stdFare（同 breakdown 配对） ----

def _tuniu_raw(breakdowns, airline_iata="MU"):
    """breakdowns: [(baseFare, bcTax, discount)]，每个元组一条
    flightPriceList（各自 fareBreakdownList 单 ADT 条目）。"""
    fpl = [
        {"fareBreakdownList": [
            {"baseFare": bf, "psgType": "ADT",
             **({"bcTaxExclusiveFare": bc} if bc is not None else {}),
             **({"discount": d} if d else {})}],
         "priceJourneyCabinList": [
             {"priceFlightCabinList": [{"cabinTypeName": "经济舱"}]}]}
        for bf, bc, d in breakdowns]
    fare = {"flightOptions": [{"flightNos": "MU8370"}],
            "flightPriceList": fpl}
    flight_list = {
        "MU8370#2026-10-06#URC#SHA": {
            "airlineCompany": "东航", "airlineIataCode": airline_iata,
            "departureTime": "20:20", "arrivalTime": "01:15",
            "departureDate": "2026-10-06", "arrivalDate": "2026-10-07",
            "flightTime": "295"}}
    return {"data": {"fareList": [fare], "flightList": flight_list}}


def test_tuniu_airline_code_offer_to_row():
    offers = TuniuCrawler._parse_offers(_tuniu_raw([(3600, 2900, "7.7折")]))
    assert offers and offers[0]["airlineCode"] == "MU"
    rows = TuniuCrawler._offers_to_flights(offers)
    # 决策字段必须随 offer 透传（两次在案的教训，逐行断言防再犯）
    assert rows and rows[0]["airlineCode"] == "MU"
    # 守卫：非二字码落空串
    bad = TuniuCrawler._parse_offers(
        _tuniu_raw([(3600, 2900, "")], airline_iata="muu"))
    assert bad and bad[0]["airlineCode"] == ""


def test_tuniu_std_fare_paired_with_selected_adt():
    # stdFare 必须与所选最低 ADT 价同一 breakdown（跨政策错配先例）：
    # 两政策各带 bcTax，最低价 2871 的公布运价 2900 随行
    offers = TuniuCrawler._parse_offers(
        _tuniu_raw([(2871, 2900, "6.2折"), (3000, 3100, "5.9折")]))
    assert offers[0]["price"] == 2871
    assert offers[0]["stdFare"] == 2900
    rows = TuniuCrawler._offers_to_flights(offers)
    assert rows and rows[0]["stdFare"] == 2900


def test_tuniu_std_fare_guards():
    # -1/0 占位不落键（调研实证 ADT 负值/零占位 44%）
    for bad in (-1, 0):
        offers = TuniuCrawler._parse_offers(
            _tuniu_raw([(2871, bad, "6.2折")]))
        assert offers and "stdFare" not in offers[0], bad
    # 键缺席同口径
    offers = TuniuCrawler._parse_offers(
        _tuniu_raw([(2871, None, "6.2折")]))
    assert offers and "stdFare" not in offers[0]
    rows = TuniuCrawler._offers_to_flights(offers)
    assert rows and "stdFare" not in rows[0]


# ---- _propagate_fields：物理属性列表扩展（airlineCode/distance/
#      shareAirline 同航班全渠道同值可补；stdFare 是报价属性不补） ----

def test_propagate_physical_fields():
    from core.alerter import Alerter
    base = {"code": "MU8370", "depDate": "2026-10-06",
            "depTime": "20:20", "arrTime": "01:15",
            "arrDate": "2026-10-07", "price": 2200}
    full = dict(base, _platform="qunar", airlineCode="MU", distance=3649,
                shareAirline="东航")
    blank = dict(base, _platform="ctrip")
    Alerter._propagate_fields([full, blank])
    assert blank["airlineCode"] == "MU"
    assert blank["distance"] == 3649
    assert blank["shareAirline"] == "东航"
    # 值冲突不补（宁缺勿错，与 cabin 同律）：两个不同非空值在场时
    # 第三行保持空（单值在场会按机制正常补——传播的语义就是「组内
    # 恰一个非空值才补」）
    conflict = dict(base, _platform="tuniu", airlineCode="CZ")
    other = dict(base, _platform="qunar", airlineCode="MU")
    blank2 = dict(base, _platform="fliggy")
    Alerter._propagate_fields([conflict, other, blank2])
    assert "airlineCode" not in blank2


# ---- webui 三端：透传白名单 + 渲染门/CSV（源码钉，行为面归 uitest） ----

def test_webui_payload_and_gates_pins():
    import webui
    src = open(os.path.join(os.path.dirname(webui.__file__), "webui.py"),
               encoding="utf-8").read()
    # 透传白名单（载荷协议四键）
    assert '"airlineCode": (f.get("airlineCode") or "").strip().upper(),' in src
    assert '"shareAirline": (f.get("shareAirline") or "").strip(),' in src
    assert '"distance": _int_or_none(f.get("distance")),' in src
    assert '"stdFare": _num_or_none(f.get("stdFare")),' in src
    # 渲染门：共享承运名+号组合（有名列合成，无名单独号）
    assert "f.shareAirline?f.shareAirline+f.shareCarrier:f.shareCarrier" in src
    # CSV 列：航程/航司码/公布运价/实际承运
    assert "航程" in src and "航司码" in src
    assert "公布运价" in src and "实际承运" in src


def test_webui_audit_fixes_pins():
    """WebUI 审计三修源码钉（行为面归 uitest/探针）：
    P2-1 比价链锚 nowrap（防锚内折行价与 ↗ 分离）/
    P2-2 弹层底注三入口各回设（pvFoot id + 三处 textContent）/
    Minor-1 读数档位后缀与环标图例逐字同形（●真达标）。"""
    import webui
    src = open(os.path.join(os.path.dirname(webui.__file__), "webui.py"),
               encoding="utf-8").read()
    # P2-1：锚本体 nowrap（td 折行放开规则的残留面）
    assert "#ftable tr.xrow td a.vw{white-space:nowrap}" in src
    # P2-2：底注入口化（id + 三入口显式回设——静态初始值是假单源）
    assert 'id="pvFoot"' in src
    assert "轮日志为原文直读" in src
    assert "推送历史本地存档回放" in src
    assert "$('pvFoot').innerHTML='本地近似渲染" in src
    # Minor-1：读数后缀 ●真达标（曾 🎯 与图例 ● 同档三字面）
    assert "q===2?' ●真达标'" in src


def test_dingtalk_at_tail_space_preserved(monkeypatch):
    """@手机号 段尾随空格是钉钉 @ 高亮的组成部分（alerter 三处有意
    追加「@xxx 」带尾空格）；rstrip() 曾把它连同尾空段一并吞掉（实发
    历史 09-29 起 @ 段失空格，推送审校 P1-1）——只剥尾部换行，
    有意尾随空格必须存活。"""
    import logging
    import core.notifier as N
    cap = {}
    monkeypatch.setattr(N, "_append_push_history",
                        lambda t, d, ok, ch="serverchan", img=None,
                        errcode=None: cap.update(desp=d))

    class _Resp:
        status_code = 200
        text = '{"errcode":0,"errmsg":"ok"}'

        def json(self):
            return {"errcode": 0}

    monkeypatch.setattr(N.httpx, "post", lambda *a, **kw: _Resp())
    n = N.DingTalkNotifier(
        "https://oapi.dingtalk.com/robot/send?access_token=x",
        logging.getLogger("t"))
    n.send("t", "正文\n\n@13800138000 ")
    assert cap["desp"] == "正文\n\n@13800138000 ", \
        "尾随空格被吞（@ 高亮意图回退）"
    # v162 契约不回退：尾空段仍剥（图片行后「\n\n」尾随空段）
    n.send("t2", "图片行\n\n![x](https://a/b.png)\n\n")
    assert cap["desp"] == "图片行\n\n![x](https://a/b.png)"
