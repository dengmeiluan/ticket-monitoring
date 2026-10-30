# -*- coding: utf-8 -*-
"""r226 数据层三案：ctrip aset 地域中转权益词 + tuniu 舱位写入端清污
+ 恒空死键不落。

- aset 三词（调研 _scratch/r226_report_payload_A.md）：「享“豫转豫好”
  免费服务」G_2025CGOZZCS 5/191、「晚安长水」G_KMZZHZS 2/191、
  「经兰飞如意行权益」G_LHWZZJD 1/191——载体行 nt=10 中转住宿/aset
  「中转住宿」/nt=103 全部 0 并现（无既有出口承载，不收则权益词永久
  缺失），tagcnt 纯词无价格不随价 churn；qunar「郑州机场中转权益」
  同族先例在案。此前第八批「地域品牌词 churn 风险不收」的排除依据被
  0 并现实证推翻（带价 churn 词与本组纯词形态不同）。
- tuniu 舱位（观测 P1）：渠道下发的「公务舱」高档词与行内价位矛盾
  （DB 近 7 天 BAD 形态：cabin=公务舱 4039 行 price 中位 3310≈经济舱、
  bizPrice=8340 同行 100% 同现、cabinCode 在场），写入端照落 DB 脏值、
  消费端 cabin_clean 全挡——唯一真实暴露面是 alerter._propagate_fields
  跨渠道补全：假高档舱名作为补全源传给同物理班无 bizPrice 的行（渲染
  门「无 bizPrice 不可内证」放行）→ 推送假高档词。修法双层：写入端
  offer.cabin 过 cabin_clean（与消费端同判据单源，detail 层下发形态
  fixture 实锤旧码产脏值/新码置空）+ 补全源过 cabin_clean（阻断传染）。
- 恒空死键（观测 P2-E）：tuniu dTerminal 46/46 空串、tongcheng
  transferBaggage 直挂三态外的行恒空串——「无值不落键」族律（键
  在场零信息）；消费端全部 == 判定缺键等价，删空串键安全。
  fliggy _via 已收口存量结案注记（12:47 现行进程零新增，normalize
  pop 兜住），不属本案。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15126_fields.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.ctrip import CtripCrawler  # noqa: E402
from crawlers.tongcheng import TongchengCrawler  # noqa: E402
from crawlers.tuniu import TuniuCrawler  # noqa: E402

_LOG = logging.getLogger("t15126")
_CT = CtripCrawler({}, _LOG)


# ---- ctrip aset 地域中转权益词 ----

def _ct_item(aset_words):
    """最小 ctrip 行：单政策 + aset[].tagarea[].tagcnt 词组。"""
    return {"mutilstn": [{"basinfo": {"flgno": "MU1234"},
                          "dateinfo": {"ddate": "2026-10-05 08:30:00",
                                       "adate": "2026-10-05 11:20:00"},
                          "craftinfo": {"cdisname": "空客320(中)"}}],
            "policyinfo": [{"quantity": 1, "tprice": 1000.0,
                            "drate": 5.0}],
            "aset": [{"tagarea": [{"tcode": "G_X", "tagcnt": w}
                                   for w in aset_words]}]}


def _ct_run(item):
    resp = {"fltitem": [item]}
    rows = _CT._extract_ctrip_flights(
        json.dumps(resp, ensure_ascii=False))
    assert len(rows) == 1
    return rows[0]


def test_ctrip_aset_region_word_cgo():
    """郑州中转权益词「享“豫转豫好”免费服务」：纯词无价格不随价
    churn，白名单收编（0 并现实证不收则永久缺失）。"""
    row = _ct_run(_ct_item(['享“豫转豫好”免费服务']))
    assert '享“豫转豫好”免费服务' in row["labels"]


def test_ctrip_aset_region_word_kmg():
    """昆明长水中转住宿权益品牌词「晚安长水」同行仅既有「赠快速
    安检」出口，住宿权益词无承载。"""
    row = _ct_run(_ct_item(["晚安长水"]))
    assert "晚安长水" in row["labels"]


def test_ctrip_aset_region_word_lhw():
    """兰州「经兰飞如意行权益」稀疏 1 行（同结构槽同族推证链：
    纯词+0 并现+qunar 同族先例）。"""
    row = _ct_run(_ct_item(["经兰飞如意行权益"]))
    assert "经兰飞如意行权益" in row["labels"]


def test_ctrip_aset_churn_marketing_word_still_absent():
    """带价 churn 词不因白名单扩充而混入：「优质中转·耗时短」
    营销词维持不收。"""
    row = _ct_run(_ct_item(["优质中转·耗时短"]))
    assert "优质中转·耗时短" not in row.get("labels", "")


# ---- tuniu 舱位写入端清污 + 补全源过门 ----

def _tj_fare(policies):
    """fare 形态：policies=[(baseFare, cabinTypeName)]。"""
    fpl = []
    for base, cab in policies:
        pr = {"fareBreakdownList": [{"baseFare": base,
                                     "psgType": "ADT"}]}
        if cab:
            pr["priceJourneyCabinList"] = [
                {"priceFlightCabinList": [{"cabinTypeName": cab}]}]
        fpl.append(pr)
    return {"flightOptions": [{"flightNos": "3U1953"}],
            "flightPriceList": fpl}


def test_tuniu_cabin_write_side_clean():
    """渠道在 detail 层下发高档舱名（与低价政策错配——DB 近 7 天
    BAD 行形态同构：cabin=公务舱、price<bizPrice、cabinCode 在场，
    3U1953 price=3570 biz=8340）：写入端 offer.cabin 过 cabin_clean
    同判据清污（price<bizPrice 高档词置空），DB 不再落脏值（消费端
    渲染门已挡，此门管落库面）。"""
    fare = {"flightOptions": [{"flightNos": "3U1953"}],
            "flightPriceList": [
                {"fareBreakdownList": [{"baseFare": 3570,
                                        "psgType": "ADT"}]},
                {"fareBreakdownList": [{"baseFare": 8340,
                                        "psgType": "ADT"}],
                 "priceJourneyCabinList": [
                     {"priceFlightCabinList": [
                         {"cabinTypeName": "公务舱",
                          "cabinCode": "J"}]}]}]}
    raw = {"data": {"fareList": [fare],
                    "flightList": {"3U1953#2026-10-06#URC#SHA": {
                        "airlineCompany": "川航",
                        "departureTime": "10:10",
                        "arrivalTime": "15:00",
                        "departureDate": "2026-10-06",
                        "arrivalDate": "2026-10-06",
                        "flightTime": "290",
                        # 渠道 detail 层下发高档舱名（与选中低价政策
                        # 错配的串舱源）
                        "cabinTypeName": "公务舱"}}}}
    offers = TuniuCrawler._parse_offers(raw)
    assert len(offers) == 1
    assert offers[0]["cabin"] == ""
    assert offers[0]["bizPrice"] == 8340   # 高档舱参考价记账不受影响


def test_tuniu_cabin_genuine_business_kept():
    """真高档选中行（price==bizPrice）：cabin 原值保留——清污门
    只杀价位矛盾形态，不误杀真公务舱。"""
    fare = _tj_fare([(8340, "公务舱")])
    raw = {"data": {"fareList": [fare],
                    "flightList": {"3U1953#2026-10-06#URC#SHA": {
                        "airlineCompany": "川航",
                        "departureTime": "10:10",
                        "arrivalTime": "15:00",
                        "departureDate": "2026-10-06",
                        "arrivalDate": "2026-10-06",
                        "flightTime": "290"}}}}
    offers = TuniuCrawler._parse_offers(raw)
    assert offers[0]["cabin"] == "公务舱"


def test_propagate_cabin_source_cleaned():
    """补全源过清污门：tuniu 行假「公务舱」（价位矛盾）不得作为
    补全源传给同物理班无 bizPrice 的行（渲染门对无 bizPrice 行
    「不可内证放行」——传染即假高档词上推送）。"""
    from core.alerter import Alerter
    bad = {"code": "3U1953", "depDate": "2026-10-06",
           "depTime": "10:10", "arrTime": "15:00",
           "arrDate": "2026-10-06", "platform": "tuniu",
           "price": 3310.0, "cabin": "公务舱", "bizPrice": 8340.0}
    victim = {"code": "3U1953", "depDate": "2026-10-06",
              "depTime": "10:10", "arrTime": "15:00",
              "arrDate": "2026-10-06", "platform": "ctrip",
              "price": 3310.0}
    Alerter._propagate_fields([bad, victim])
    assert victim.get("cabin", "") == ""


def test_propagate_cabin_genuine_still_propagates():
    """真高档舱名（price==bizPrice）补全照常——补全物理属性的
    机制本身不受影响。"""
    from core.alerter import Alerter
    good = {"code": "MU1234", "depDate": "2026-10-06",
            "depTime": "08:30", "arrTime": "11:20",
            "arrDate": "2026-10-06", "platform": "ctrip",
            "price": 8340.0, "cabin": "公务舱", "bizPrice": 8340.0}
    victim = {"code": "MU1234", "depDate": "2026-10-06",
              "depTime": "08:30", "arrTime": "11:20",
              "arrDate": "2026-10-06", "platform": "qunar",
              "price": 8340.0}
    Alerter._propagate_fields([good, victim])
    assert victim.get("cabin") == "公务舱"


# ---- 恒空死键不落 ----

def test_tuniu_dterminal_empty_no_key():
    """dTerminal 渠道恒空串（46/46）：depTerminal 不落键（无值
    不落键族律）；有值照落。"""
    fare = _tj_fare([(1500, "经济舱")])
    det_base = {"airlineCompany": "川航",
                "departureTime": "10:10", "arrivalTime": "15:00",
                "departureDate": "2026-10-06",
                "arrivalDate": "2026-10-06", "flightTime": "290"}
    raw = {"data": {"fareList": [fare],
                    "flightList": {"3U1953#2026-10-06#URC#SHA":
                                   dict(det_base)}}}
    offers = TuniuCrawler._parse_offers(raw)
    assert "depTerminal" not in offers[0]

    raw2 = {"data": {"fareList": [fare],
                     "flightList": {"3U1953#2026-10-06#URC#SHA":
                                    dict(det_base, aTerminal="T2")}}}
    offers2 = TuniuCrawler._parse_offers(raw2)
    assert offers2[0].get("arrTerminal") == "T2"


def test_tuniu_terminal_empty_no_key_row_layer():
    """行层（DB extra 面）同守无值不落键：offer 层不落键后，行层
    str(o.get(...)) 恒产空串、空串键照落=卫生项半落地（审查 P2-1）。
    全链 _parse_offers→_offers_to_flights 断键不在；aTerminal 有值
    照落（同族对照：tongcheng transferBaggage 条件展开就在最终行）。"""
    fare = _tj_fare([(1500, "经济舱")])
    det_base = {"airlineCompany": "川航",
                "departureTime": "10:10", "arrivalTime": "15:00",
                "departureDate": "2026-10-06",
                "arrivalDate": "2026-10-06", "flightTime": "290"}
    raw = {"data": {"fareList": [fare],
                    "flightList": {"3U1953#2026-10-06#URC#SHA":
                                   dict(det_base)}}}
    rows = TuniuCrawler._offers_to_flights(TuniuCrawler._parse_offers(raw))
    assert rows
    assert "depTerminal" not in rows[0]
    assert "arrTerminal" not in rows[0]

    raw2 = {"data": {"fareList": [fare],
                     "flightList": {"3U1953#2026-10-06#URC#SHA":
                                    dict(det_base, aTerminal="T2")}}}
    rows2 = TuniuCrawler._offers_to_flights(
        TuniuCrawler._parse_offers(raw2))
    assert rows2[0].get("arrTerminal") == "T2"


def test_tc_transfer_baggage_empty_no_key():
    """transferBaggage 三态外的行恒空串：不落空串键（消费端
    ==direct 判定缺键等价，flightnorm setdefault 兜内存形态）。"""
    ss = [{"fn": "CZ6981", "dt": "2026-10-05 13:20",
           "at": "2026-10-05 16:05"},
          {"fn": "MU5700", "dt": "2026-10-05 18:20",
           "at": "2026-10-05 21:30"}]
    fp = {"dt": "2026-10-05 13:20", "at": "2026-10-05 21:30",
          "sd": "2h45m", "td": "8h10m", "sc": "张掖", "ss": ss,
          "lps": [{"atp": 1500, "brs": [{"al": 5}],
                   "pts": [{"td": "6.8折经济舱"}]}]}
    rows = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp]}}), "11")
    assert rows
    assert "transferBaggage" not in rows[0]
