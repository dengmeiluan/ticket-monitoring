# -*- coding: utf-8 -*-
"""r239 数据层：qunar 空串落键收口（str 槽位无值不落，恒空键卫生律）。

r237 九段观测实锤 6 族空串平铺（「空串平铺键疑似新族」哨兵假火源）：
qunar PC shareAirline 直 233 / 中 254、discount 直 10、中转
layover/layoverSrc/totalDuration 各 8——渠道键缺席时写点无条件落空串，
消费端 falsy 门兜住属门欠账（源码注释自认）。收口形态与
stopTime/lay2dep/航站楼族同款条件展开：无值键缺席、有值照落，
layoverSrc 标记键缺席与空串在消费端 `.get() not in` 语义下等价。

样本形态取生产冻结 dump 同构。运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r239_data.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.qunar import QunarCrawler  # noqa: E402

_LOG = logging.getLogger("r239")
_QC = QunarCrawler({}, _LOG)

_EMPTY5 = ("shareAirline", "discount", "layover", "layoverSrc",
           "totalDuration")


def _pc_flight(b1=None, b2=None, **top):
    """PC wbdflightlist 行最小载体（data.flights 普通数组形态）。"""
    f = {"minPrice": 1200, "code": "MU2772",
         "binfo1": dict({"depTime": "08:00", "arrTime": "11:30",
                         "date": "2026-10-05", "shortCarrier": "MU",
                         "airCode": "2772"}, **(b1 or {})),
         "binfo2": b2 or {}}
    f.update(top)
    return f


def _pc_text(flights):
    return json.dumps({"data": {"flights": flights}}, ensure_ascii=False)


def test_pc_empty_str_keys_not_landed():
    """PC 直飞行（无共享/无折扣/无经停/无时长源）：5 键应缺席非空串。"""
    rows = QunarCrawler._parse_pc_flights(_pc_text([_pc_flight()]),
                                          "2026-10-05")
    assert rows, "样本应产出至少一行"
    for k in _EMPTY5:
        assert k not in rows[0], f"空串键 {k} 应不落库（无值不落）"


def test_pc_trans_empty_dur_and_layover_not_landed():
    """PC 中转行停留/全程组件缺失时同样不落（中转 8 条空串族）。"""
    b2 = {"arrTime": "15:30", "arrDate": "2026-10-05",
          "airCode": "2404"}
    rows = QunarCrawler._parse_pc_flights(
        _pc_text([_pc_flight(b2=b2, code="MU2772/MU2404")]), "2026-10-05")
    assert rows, "样本应产出至少一行"
    row = rows[0]
    for k in ("layover", "layoverSrc", "totalDuration"):
        assert k not in row, f"中转空组件键 {k} 应不落库"


def test_pc_valued_still_landed():
    """有值照落（门不得误杀真值）：共享/折扣/经停停留/全程时长。"""
    rows = QunarCrawler._parse_pc_flights(
        _pc_text([_pc_flight(
            b1={"mainCarrierShortName": "上航", "stopTime": "1小时5分",
                "flightTime": "3h30m", "codeShare": 1,
                "mainCarrier": "FM9224"},
            b2={"depTime": "14:30", "arrTime": "16:00",
                "arrDate": "2026-10-05", "airCode": "2404",
                "flightTime": "1h20m"},
            code="MU2772/MU2404", discountStr="9折")]),
        "2026-10-05")
    assert rows, "样本应产出至少一行"
    row = rows[0]
    assert row.get("shareAirline") == "上航", row
    assert row.get("discount") == "9折", row
    assert row.get("layoverSrc") == "times", row
    assert row.get("totalDuration") == "7时50分", row
    assert row.get("layover"), "经停停留有值应照落"


def test_pc_direct_flighttime_totalduration_still_landed():
    """直飞行 flightTime 换算的全程时长有值照落。"""
    rows = QunarCrawler._parse_pc_flights(
        _pc_text([_pc_flight(b1={"flightTime": "5h30m"})]), "2026-10-05")
    assert rows and rows[0].get("totalDuration") == "5时30分", rows


def _h5_text(flight):
    return json.dumps({"data": {"flights": [flight]}}, ensure_ascii=False)


def test_h5_empty_str_keys_not_landed():
    """H5 直飞行最小载体：totalDuration/layover/layoverSrc/discount 缺席。"""
    text = _h5_text({
        "minPrice": 2889, "code": "FM9223",
        "binfo": {"depTime": "19:55", "arrTime": "01:25",
                  "depDate": "2026-09-25", "arrDate": "2026-09-26"}})
    rows = QunarCrawler._parse_response_flights(text)
    assert rows, "样本应产出至少一行"
    for k in ("totalDuration", "layover", "layoverSrc", "discount"):
        assert k not in rows[0], f"H5 空串键 {k} 应不落库"


def test_h5_valued_still_landed():
    """H5 有值照落：transTime→totalDuration、transInfo→layoverSrc。"""
    text = _h5_text({
        "minPrice": 2692, "code": "CZ6976",
        "transTime": "2时10分",
        "extparams": "{\"stopFlight\":true}",
        "binfo": {"depTime": "08:00", "arrTime": "11:30",
                  "depDate": "2026-09-25", "arrDate": "2026-09-25",
                  "transInfo": {"transCity": "郑州",
                                "transTime": "2时10分"}},
        "binfo2": {"depTime": "14:15"}})
    rows = QunarCrawler._parse_response_flights(text)
    assert rows, "样本应产出至少一行"
    row = rows[0]
    assert row.get("totalDuration") == "2时10分", row
    assert row.get("layoverSrc") == "transInfo", row


# ---- 同族排查（六.5 同族一次排查完）：tongcheng / ctrip 同形空串 ----
# DB 观测 before 基线：tongcheng cabin 空串 7 天 8,374 元素（近 48h
# 流入 2,148，五渠道唯一 cabin 空串在产族）；tongcheng 中转
# layover/layoverSrc 伴生 7 条；ctrip discount direct 574；
# ctrip 直飞行 layover 恒空串（与 qunar 直飞行同形语义常态）

def _tc_text(fp):
    import json as _json
    return _json.dumps({"data": {"fl": [fp]}}, ensure_ascii=False)


def _tc_fps_text(fp):
    import json as _json
    return _json.dumps({"data": {"fps": [fp]}}, ensure_ascii=False)


def test_tongcheng_cabin_empty_not_landed():
    """tongcheng 直飞行：政策文本无舱位词且无 cabinlevel → cabin 缺席。"""
    from crawlers.tongcheng import TongchengCrawler
    text = _tc_text({
        "fn": "GS7587", "asn": "天津航空",
        "dt": "2026-10-06 07:00", "at": "2026-10-06 13:45",
        "td": "6h45m", "afn": "空客A320(中)",
        "lps": [{"atp": 3200, "brs": [{"al": 4}],
                 "pts": [{"tt": 2, "td": "6.8折"}]}],
    })
    rows = TongchengCrawler._extract_flights(text)
    assert rows, "样本应产出至少一行"
    assert "cabin" not in rows[0], "cabin 空串应不落库"


def test_tongcheng_cabin_valued_still_landed():
    """tongcheng cabin 有值照落（门不得误杀真值）。"""
    from crawlers.tongcheng import TongchengCrawler
    text = _tc_text({
        "fn": "GS7587", "asn": "天津航空",
        "dt": "2026-10-06 07:00", "at": "2026-10-06 13:45",
        "td": "6h45m", "afn": "空客A320(中)",
        "lps": [{"atp": 3200, "brs": [{"al": 4}],
                 "pts": [{"tt": 2, "td": "6.8折经济舱"}]}],
    })
    rows = TongchengCrawler._extract_flights(text)
    assert rows and rows[0].get("cabin") == "经济舱", rows


def test_tongcheng_trans_layover_empty_not_landed():
    """tongcheng 中转行：停留组件缺失 → layover/layoverSrc 缺席。"""
    from crawlers.tongcheng import TongchengCrawler
    fp = {"dt": "2026-10-05 13:20", "at": "2026-10-05 21:30",
          "td": "8h10m", "sc": "张掖",
          "ss": [{"fn": "CZ6981", "dt": "2026-10-05 13:20",
                  "at": "2026-10-05 16:05"},
                 {"fn": "MU5700", "dt": "2026-10-05 18:20",
                  "at": "2026-10-05 21:30"}],
          "lps": [{"atp": 1500, "brs": [{"al": 5}],
                   "pts": [{"td": "6.8折经济舱"}]}]}
    rows = TongchengCrawler._extract_transfer_flights(
        _tc_fps_text(fp), "")
    assert rows, "样本应产出至少一行"
    row = rows[0]
    assert "layover" not in row and "layoverSrc" not in row, row


def test_tongcheng_trans_layover_valued_still_landed():
    """tongcheng 中转停留有值照落 + layoverSrc=transInfo 标记。"""
    from crawlers.tongcheng import TongchengCrawler
    fp = {"dt": "2026-10-05 13:20", "at": "2026-10-05 21:30",
          "sd": "2h45m", "td": "8h10m", "sc": "张掖",
          "ss": [{"fn": "CZ6981", "dt": "2026-10-05 13:20",
                  "at": "2026-10-05 16:05"},
                 {"fn": "MU5700", "dt": "2026-10-05 18:20",
                  "at": "2026-10-05 21:30"}],
          "lps": [{"atp": 1500, "brs": [{"al": 5}],
                   "pts": [{"td": "6.8折经济舱"}]}]}
    rows = TongchengCrawler._extract_transfer_flights(
        _tc_fps_text(fp), "")
    assert rows, "样本应产出至少一行"
    row = rows[0]
    assert row.get("layover") == 165, row
    assert row.get("layoverSrc") == "transInfo", row


def test_tongcheng_trans_cabin_empty_not_landed():
    """tongcheng 中转行 cabin 无值不落（Soldier P2-1：中转出口补钉）。"""
    from crawlers.tongcheng import TongchengCrawler
    fp = {"dt": "2026-10-05 13:20", "at": "2026-10-05 21:30",
          "sd": "2h45m", "td": "8h10m", "sc": "张掖",
          "ss": [{"fn": "CZ6981", "dt": "2026-10-05 13:20",
                  "at": "2026-10-05 16:05"},
                 {"fn": "MU5700", "dt": "2026-10-05 18:20",
                  "at": "2026-10-05 21:30"}],
          "lps": [{"atp": 1500, "brs": [{"al": 5}],
                   "pts": [{"td": "6.8折"}]}]}
    rows = TongchengCrawler._extract_transfer_flights(
        _tc_fps_text(fp), "")
    assert rows, "样本应产出至少一行"
    assert "cabin" not in rows[0], rows[0]


def test_tongcheng_trans_cabin_valued_still_landed():
    """tongcheng 中转行 cabin 有值照落（防误杀对钉）。"""
    from crawlers.tongcheng import TongchengCrawler
    fp = {"dt": "2026-10-05 13:20", "at": "2026-10-05 21:30",
          "sd": "2h45m", "td": "8h10m", "sc": "张掖",
          "ss": [{"fn": "CZ6981", "dt": "2026-10-05 13:20",
                  "at": "2026-10-05 16:05"},
                 {"fn": "MU5700", "dt": "2026-10-05 18:20",
                  "at": "2026-10-05 21:30"}],
          "lps": [{"atp": 1500, "brs": [{"al": 5}],
                   "pts": [{"td": "6.8折经济舱"}]}]}
    rows = TongchengCrawler._extract_transfer_flights(
        _tc_fps_text(fp), "")
    assert rows, "样本应产出至少一行"
    assert rows[0].get("cabin") == "经济舱", rows[0]


def _ctrip_text(items):
    import json as _json
    return _json.dumps(items, ensure_ascii=False)


def _ctrip_item(segs, policies):
    return {"mutilstn": segs, "policyinfo": policies}


def _ctrip_seg(dd, ad, flgno="CZ5640"):
    return {"dateinfo": {"ddate": dd, "adate": ad},
            "basinfo": {"flgno": flgno},
            "dportinfo": {"bsname": "", "aport": "URC"},
            "aportinfo": {"bsname": "T3", "aport": "SHA"}}


def _ctrip_policy(price=1200, drate=None, qty=5):
    p = {"tprice": price, "quantity": qty, "classinfor": [
        {"cgrd": 0, "classNoteList": [{"notetype": 2, "notecnt": "Y"}]}]}
    if drate is not None:
        p["drate"] = drate
    return p


def _ctrip_one(item):
    from crawlers.ctrip import CtripCrawler
    rows = CtripCrawler({}, _LOG)._extract_ctrip_flights(
        _ctrip_text([item]))
    assert rows, "样本应产出至少一行"
    return rows[0]


_D1 = ("2026-10-06 08:30:00", "2026-10-06 13:50:00")


def test_ctrip_direct_layover_empty_not_landed():
    """ctrip 直飞行（无衔接）：layover 缺席（直飞行恒空串平铺收口）。"""
    row = _ctrip_one(_ctrip_item([_ctrip_seg(*_D1)],
                                 [_ctrip_policy()]))
    assert "layover" not in row, row


def test_ctrip_discount_empty_not_landed():
    """ctrip 最低价政策无折扣率（drate 缺席）→ discount 缺席。"""
    row = _ctrip_one(_ctrip_item([_ctrip_seg(*_D1)],
                                 [_ctrip_policy()]))
    assert "discount" not in row, row


def test_ctrip_discount_valued_still_landed():
    """ctrip discount 有值照落（drate=5.2 → 5.2折）。"""
    row = _ctrip_one(_ctrip_item([_ctrip_seg(*_D1)],
                                 [_ctrip_policy(drate=5.2)]))
    assert row.get("discount") == "5.2折", row
