# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r253_fields.py
- tests/test_v225_fields.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import base64
import json
import logging
import os
import sys
import zstandard

from crawlers.ctrip import CtripCrawler
from crawlers.qunar import QunarCrawler
from crawlers.tongcheng import TongchengCrawler


# ---- merged from tests/test_r253_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t253")
_CT = CtripCrawler({}, _LOG)


def _mk_pid_payload(payload):
    blob = zstandard.ZstdCompressor().compress(
        json.dumps(payload).encode("utf-8"))
    return "__Zstd__|" + base64.b64encode(blob).decode("ascii")


def _ctrip_seg(dd, ad, flgno="GS7529"):
    return {"dateinfo": {"ddate": dd, "adate": ad},
            "basinfo": {"flgno": flgno},
            "dportinfo": {"bsname": "", "aport": "URC"},
            "aportinfo": {"bsname": "T2", "aport": "SHA"}}


def _ctrip_policy(price=2457, ci=None, qty=5):
    p = {"tprice": price, "quantity": qty, "drate": 5.2}
    if ci is not None:
        p["classinfor"] = [ci]
    return p


def _ctrip_item(pid, policies, transfer=False):
    segs = ([_ctrip_seg("2026-10-08 16:40:00", "2026-10-08 21:30:00")]
            if not transfer else
            [_ctrip_seg("2026-10-08 16:40:00", "2026-10-08 19:10:00",
                        "GS7529"),
             _ctrip_seg("2026-10-08 20:30:00", "2026-10-08 23:30:00",
                        "MU5700")])
    return {"pid": pid, "mutilstn": segs, "policyinfo": policies}


def _ctrip_one(item):
    rows = _CT._extract_ctrip_flights(json.dumps([item]))
    assert rows, "样本应产出至少一行"
    return rows[0]


_CI_Y = {"cgrd": 0, "classNoteList": [{"notetype": 2, "notecnt": "Y"}]}


def _pid_with_std(std="4350.0,BusinessPriority", **items_extra):
    payload = {"trlinfos": [
        {"policies": {"price": 2457, "grade": "Y",
                      "tag": ["freeLuggageAmount_20"]}}],
        "items": dict({"L_Y_Price": std}, **items_extra)}
    return _mk_pid_payload(payload)


class TestCtripStdFare:
    """r254 撤采定谳（观测双源 raw 对照）：L_Y_Price 实为卖价镜像
    （近 48h 172/172 行 stdFare==price 恒等，1.6 折深折行也不含全价），
    与 tuniu bcTaxExclusiveFare（税前公布价）跨渠道不对等——「公布运价
    列跨渠道对等」承诺失真，恒等镜像零信息增量撤采（词面配对判据），
    CSV「公布运价」列回归 tuniu 纯口径；存量行随 40 分钟滚动窗自然
    老化出列（extra 内 stdFare 在窗内仍显示，消费端空值不占位）。
    _pid_free_kgs 行李额同门消费不受牵连（回归钉保留）。"""

    def test_direct_row_no_stdfare(self):
        """直飞行撤采：L_Y_Price 卖价镜像不再落 stdFare。"""
        r = _ctrip_one(_ctrip_item(_pid_with_std(),
                                   [_ctrip_policy(ci=_CI_Y)]))
        assert "stdFare" not in r

    def test_transfer_row_not_landed(self):
        """中转组合行不落（维持原判）。"""
        r = _ctrip_one(_ctrip_item(_pid_with_std(),
                                   [_ctrip_policy(ci=_CI_Y)],
                                   transfer=True))
        assert "stdFare" not in r

    def test_free_kgs_regressor(self):
        """pid 解码单源重构不回归：行李额同门照常（_pid_free_kgs
        既有行为，trlinfos 与 items 双消费并存）。"""
        r = _ctrip_one(_ctrip_item(_pid_with_std(),
                                   [_ctrip_policy(ci=_CI_Y)]))
        assert r.get("baggage") == "免费托运20KG"


def _h5_trans(**top):
    """H5 中转行最小形态（r244 样板同构）。"""
    f = {
        "minPrice": 1200, "code": "3U1599/MU2161",
        "transTime": "25h40m",
        "binfo1": {"depTime": "08:00", "arrTime": "11:30",
                   "depDate": "2026-10-05", "arrDate": "2026-10-05",
                   "carrierSimpleName": "南航｜东航"},
        "binfo2": {"arrTime": "18:20", "arrDate": "2026-10-05"},
        "extparams": "{}",
    }
    f.update(top)
    return f


def _h5_direct(**top):
    """H5 直飞行最小形态：单段 code、无 binfo2。"""
    f = {
        "minPrice": 900, "code": "CZ6981",
        "transTime": "4h30m",
        "binfo": {"depTime": "08:00", "arrTime": "12:30",
                  "depDate": "2026-10-05", "arrDate": "2026-10-05",
                  "carrierSimpleName": "南航"},
        "extparams": "{}",
    }
    f.update(top)
    return f


def _h5_one(f):
    rows = QunarCrawler._extract_flights_obj([f])
    assert rows, "样本应产出至少一行"
    return rows[0]


class TestQunarShareAirline:
    def test_trans_row_lands_normalized(self):
        """中转行落 shareAirline，全角分隔符归一半角。"""
        r = _h5_one(_h5_trans())
        assert r.get("shareAirline") == "南航|东航"

    def test_direct_row_not_landed(self):
        """直飞行不落（单段无「各段承运」语义；PC 出口同键=
        共享行专属，直飞非共享两侧皆无源）。"""
        r = _h5_one(_h5_direct())
        assert "shareAirline" not in r

    def test_null_garbage_not_landed(self):
        """「null」垃圾串不落（H5 mainCarrier 家族曾现字符串 null）。"""
        f = _h5_trans()
        f["binfo1"]["carrierSimpleName"] = "null"
        assert "shareAirline" not in _h5_one(f)

    def test_shared_row_not_landed(self):
        """共享行（codeShare 主源在场）不落——承运信息由 shareCarrier
        词面承载，防两键同屏语义混淆。"""
        f = _h5_trans(binfo1={"depTime": "08:00", "arrTime": "11:30",
                              "depDate": "2026-10-05",
                              "arrDate": "2026-10-05",
                              "carrierSimpleName": "南航｜东航",
                              "codeShare": True,
                              "mainCarrierSimpleNameAndNo": "川航3U1599"})
        r = _h5_one(f)
        assert r.get("shareCarrier") == "川航3U1599"
        assert "shareAirline" not in r


# ---- merged from tests/test_v225_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t225")


# ---- D1: qunar PC ptripNote 无值不落键 ----

def _pc_flight(**extra):
    f = {"minPrice": 1200, "code": "MF8266",
         "binfo": {"depTime": "12:05", "arrTime": "16:40",
                   "depDate": "2026-10-04", "arrDate": "2026-10-04",
                   "shortName": "厦航", "airCode": "MF8266"},
         "extparams": {}}
    f.update(extra)
    return f


def _pc_rows(f):
    return QunarCrawler._parse_pc_flights(json.dumps(
        {"data": {"flights": [f]}}), "2026-10-04")


def test_qunar_pc_ptripnote_present():
    """pTrip=true 且 Note 非空 → 键落值（特惠产品权益正文）。"""
    f = _pc_flight(binfo={"depTime": "12:05", "arrTime": "16:40",
                          "depDate": "2026-10-04", "arrDate": "2026-10-04",
                          "shortName": "厦航", "airCode": "MF8266",
                          "pTrip": True,
                          "pTripNote": "航变免费改、20Kg免费行李"})
    assert _pc_rows(f)[0]["ptripNote"] == "航变免费改、20Kg免费行李"


def test_qunar_pc_ptripnote_absent_no_key():
    """pTrip 非 true（全场绝大多数）→ 不落键。旧平铺落键使 60,021 行
    extra 恒挂空串 ptripNote（真值率 0）——无值不落键家族律
    （avgDelay/refundChange 同族）。"""
    rows = _pc_rows(_pc_flight())
    assert "ptripNote" not in rows[0], rows[0].get("ptripNote")


def test_qunar_pc_ptripnote_true_but_empty_no_key():
    """pTrip=true 但 Note 空串 → 同样不落键（空值不落）。"""
    f = _pc_flight(binfo={"depTime": "12:05", "arrTime": "16:40",
                          "depDate": "2026-10-04", "arrDate": "2026-10-04",
                          "shortName": "厦航", "airCode": "MF8266",
                          "pTrip": True, "pTripNote": ""})
    assert "ptripNote" not in _pc_rows(f)[0]


# ---- D2: ctrip bridgeRate 无值不落键 ----

class _CtripDirect:
    """最小直飞 fltitem（test_v1552_regress 同款骨架）。"""

    def _parse(self, item):
        obj = {"fltitem": [item]}
        return CtripCrawler._extract_ctrip_flights(
            CtripCrawler, json.dumps(obj, ensure_ascii=False))

    @staticmethod
    def _ci(**over):
        ci = {"cgrd": 0, "prate": 96, "meal": "", "extendinfos": []}
        ci.update(over)
        return ci

    def _direct(self, quantity=3, ci=None):
        return {"mutilstn": [{"basinfo": {"flgno": "MU5137"},
                              "dateinfo": {"ddate": "2026-10-05 08:00:00",
                                           "adate": "2026-10-05 11:30:00"},
                              "aportinfo": {"city": "上海"}}],
                "policyinfo": [{"tprice": 1200, "quantity": quantity,
                                "classinfor": [ci or self._ci()]}]}


def test_ctrip_bridge_rate_present_int():
    rows = _CtripDirect()._parse(_CtripDirect()._direct(ci=_CtripDirect._ci(
        extendinfos=[{"content": "连廊率93%"}])))
    assert rows[0]["bridgeRate"] == 93


def test_ctrip_bridge_rate_absent_no_key():
    """extendinfos 无连廊率词 → 不落键。旧空串落键 ~180 行/日存量
    （int 真值占 99.3%）——与 ptripNote 同批载荷卫生。"""
    rows = _CtripDirect()._parse(_CtripDirect()._direct())
    assert "bridgeRate" not in rows[0], rows[0].get("bridgeRate")


# ---- D3: tongcheng atpt「余票紧张」→ fewTicket 补源 ----

def _tc_flight(**extra):
    f = {"fn": "MF2370", "asn": "厦航", "dt": "2026-10-06 10:10",
         "at": "2026-10-06 14:55", "td": "4h45m", "amt": "中",
         "lps": [{"atp": 4350, "brs": {"al": 20},
                  "atpt": {"tt": 1, "td": "余1张"},
                  "pts": [{"tt": 2, "td": "全价经济舱"}]}]}
    f.update(extra)
    return f


def _tc_rows(f):
    obj = {"success": True, "data": {"ec": 0, "fl": [f]}}
    return TongchengCrawler._extract_flights(
        json.dumps(obj, ensure_ascii=False))


def test_tongcheng_fewticket_tense_direct():
    """atpt.td=「余票紧张」→ fewTicket=「紧张」（既有出口键，fliggy
    值域白名单已含该词，webui 明细次行 few 槽原样透传）；fresh dump
    1/288 行稀疏在场。"""
    f = _tc_flight()
    f["lps"][0]["atpt"] = {"tt": 1, "td": "余票紧张"}
    r = _tc_rows(f)[0]
    assert r["fewTicket"] == "紧张"
    assert "leftTickets" not in r


def test_tongcheng_fewticket_numeric_arm_unchanged():
    """数字臂照常：「余3张」→ leftTickets=3，不落 fewTicket（两臂
    互斥，数字形态语义更精确）。"""
    f = _tc_flight()
    f["lps"][0]["atpt"] = {"tt": 1, "td": "余3张"}
    r = _tc_rows(f)[0]
    assert r["leftTickets"] == 3
    assert "fewTicket" not in r


def test_tongcheng_fewticket_reset_on_lower_policy():
    """随最低价政策复位防脏携带：先高价新政带「余票紧张」、后低价政
    无 atpt → fewTicket 不落（与 leftTickets 复位同律）。"""
    f = _tc_flight(lps=[
        {"atp": 4600, "brs": {"al": 20},
         "atpt": {"tt": 1, "td": "余票紧张"}},
        {"atp": 4350, "brs": {"al": 20}}])
    r = _tc_rows(f)[0]
    assert r["price"] == 4350
    assert "fewTicket" not in r


def test_tongcheng_fewticket_tense_transfer():
    """中转路径同臂：book1 fps 形态 atpt.td=「余票紧张」→ fewTicket
    （两处解析点同收，注释「本轮 connection 未现样本，出现即采」）。"""
    fp = {"dt": "2026-10-06 08:00", "at": "2026-10-07 18:00",
          "sd": "2h15m", "td": "9h30m", "sc": "西安",
          "dasn": "天山", "aasn": "浦东", "dat": "", "aat": "T2",
          "ss": [{"fn": "CZ6981", "amn": "空客320(中)"},
                 {"fn": "MU5700", "amn": "波音787(大)"}],
          "lps": [{"atp": 1800, "brs": [{"al": 3}],
                   "atpt": {"tt": 1, "td": "余票紧张"},
                   "pts": [{"td": "5.2折经济舱"}]}]}
    rows = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [fp]}}, ensure_ascii=False))
    assert rows[0]["fewTicket"] == "紧张"
