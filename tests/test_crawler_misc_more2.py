# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1736_guard_behaviour.py
- tests/test_r239_data.py
- tests/test_r661_detail_rows_real_layout.py
- tests/test_r703_browser_channel_round_trip_calibration.py
- tests/test_r723_sms_code_is_login_wall.py
- tests/test_r726_empty_dump_not_a_predicate.py
- tests/test_r971_boundary_single_source.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import crawlers
import crawlers.captcha as captcha
import crawlers.slider as slider
import inspect
import io
import json
import logging
import os
import pytest
import sys

from core.channels import CHANNEL_DIMENSIONS, dim_state
from crawlers import APP_CHANNELS, app_zhixing_nav as nav
from crawlers.app_base import AppCrawler
from crawlers.app_tongcheng import AppTongchengCrawler as _TC
from crawlers.app_tongcheng_parse import is_form
from crawlers.app_zhixing_parse import parse_flight_rows
from crawlers.qunar import QunarCrawler


# ---- merged from tests/test_r1736_guard_behaviour.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIN = os.path.join(ROOT, "tests", "fixtures", "tongcheng_train_page.xml")


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, fmt, *a):
        self.lines.append(fmt % a if a else fmt)

    warning = info
    debug = info


class _Dev:
    def __init__(self, xml):
        self._xml = xml

    def dump(self):
        return self._xml


def _crawler(xml):
    c = _TC({}, _Log())
    c.paths = []
    c.user_data_root = os.path.join(ROOT, "_scratch", "_u")
    c._last_dev = _Dev(xml)
    return c


def _train_xml():
    return io.open(TRAIN, encoding="utf-8", errors="replace").read()


def test_guard_stops_on_train_page():
    xml = _train_xml()
    assert is_form(xml) is False, "fixture 本身不该被当成机票表单"
    c = _crawler(xml)
    ok = c._on_flight_form(dev=c._last_dev, entry="app-city")
    assert ok is False, "停在火车票页时守卫没有拦住"
    notes = [p for p in c.paths if p.get("path") == "app-city"]
    assert notes, "守卫没有记账"
    detail = notes[-1].get("detail") or ""
    assert "偏离机票表单" in detail, detail
    assert "火车票" in detail, detail
    assert notes[-1].get("status") == "timeout", notes[-1]


def test_guard_allows_flight_form():
    """机票表单页要放行（用同一份 dump 的伪造版：加一个「机票查询」节点）。"""
    xml = _train_xml().replace("查询火车票", "机票查询")
    c = _crawler(xml)
    ok = c._on_flight_form(dev=c._last_dev, entry="app-city")
    assert ok is True, "机票表单被误拦"
    assert not [p for p in c.paths if p.get("path") == "app-city"], \
        "放行时不该记账"


# ---- merged from tests/test_r239_data.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


# ---- merged from tests/test_r661_detail_rows_real_layout.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _n(text, x1, y1, x2, y2, idx=0):
    return ('<node index="%d" text="%s" resource-id="" class="android.widget.TextView"'
            ' bounds="[%d,%d][%d,%d]" />' % (idx, text, x1, y1, x2, y2))


def _card(idx, dep, arr, code, price, top):
    """一张真实形态的航班卡片：时刻行(top..top+38) / 城市行 / 航班号行。"""
    return "".join([
        # 时刻行：左=起飞、右=到达（同一排，cy 相同）
        _n(dep, 34, top, 245, top + 38),
        _n(arr, 460, top, 544, top + 38),
        # 价格：￥ 与数字拆成两个节点，且数字可能排在若干节点之后
        _n("￥", 796, top + 5, 809, top + 22),
        _n("虹桥T2", 34, top + 29, 245, top + 54),
        _n("白云T3", 487, top + 29, 544, top + 54),
        _n("331", 809, top, 865, top + 19),
        _n("东航", 54, top + 68, 90, top + 91),
        _n(code, 92, top + 68, 160, top + 93),
    ])


def _xml(cards):
    return ('<?xml version="1.0" encoding="UTF-8"?><hierarchy rotation="0">'
            + "".join(cards) + "</hierarchy>")


def test_arrival_pairs_with_departure_on_same_row():
    """到达必须与起飞同排，不得被下一行"更近"的到达抢走。"""
    xml = _xml([_card(0, "22:30", "01:15", "CZ3832", "376", 1294),
                _card(1, "16:50", "19:25", "MU5311", "380", 1444)])
    rows = {r["flight_no"]: r for r in parse_flight_rows(xml)}
    assert rows["CZ3832"]["depart_time"] == "22:30"
    assert rows["CZ3832"]["arrive_time"] == "01:15", \
        "到达取成了别的卡片：%s" % rows["CZ3832"]
    assert rows["MU5311"]["arrive_time"] == "19:25"


def test_arrival_never_earlier_than_departure_by_mistake():
    """近似取值会造出「22:30→19:25」这种跨卡片的假行。"""
    xml = _xml([_card(0, "22:30", "01:15", "CZ3832", "376", 1294),
                _card(1, "16:50", "19:25", "MU5311", "380", 1444)])
    for r in parse_flight_rows(xml):
        dep_h, dep_m = r["depart_time"].split(":")
        arr_h, arr_m = r["arrive_time"].split(":")
        span = (int(arr_h) * 60 + int(arr_m)) - (int(dep_h) * 60 + int(dep_m))
        assert span > 0 or span < -600, \
            "%s 起飞 %s 到达 %s 相差 %.0f 分钟，明显跨卡片" % (
                r["flight_no"], r["depart_time"], r["arrive_time"], span)


def test_price_found_when_digits_are_not_adjacent_in_document_order():
    """￥ 与数字之间夹着别的节点时，价格仍要取到（当日低价卡片实测形态）。"""
    xml = _xml([_card(0, "22:30", "01:05", "MU5319", "331", 297)])
    rows = parse_flight_rows(xml)
    assert len(rows) == 1
    assert rows[0]["price"] == 331, "价格丢了：%r" % rows[0]


def test_price_still_none_when_absent():
    """没有价格节点时不得瞎猜（宁缺勿错）。"""
    xml = ('<?xml version="1.0"?><hierarchy>'
           + _n("22:30", 34, 297, 245, 335)
           + _n("01:05", 460, 297, 544, 335)
           + _n("MU5319", 92, 372, 160, 397)
           + "</hierarchy>")
    rows = parse_flight_rows(xml)
    assert rows and rows[0]["price"] is None


# ---- merged from tests/test_r703_browser_channel_round_trip_calibration.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _src(plat):
    cls = crawlers.REGISTRY[plat]
    return inspect.getsource(inspect.getmodule(cls))


def test_every_channel_declares_round_trip():
    """七家都要表态，不能有空白——空白会被界面当成「未知」还是「没有」两可。"""
    for plat in CHANNEL_DIMENSIONS:
        assert dim_state(plat, "round_trip") in ("y", "n", ""), plat


def test_round_trip_y_has_real_ret_date_path():
    """声明 y 的渠道，源码里必须真的把 ret_date 用进了请求或解析。"""
    for plat, row in CHANNEL_DIMENSIONS.items():
        if row.get("round_trip") != "y":
            continue
        src = _src(plat)
        assert "ret_date" in src, "%s 声明支持往返，源码里没有 ret_date" % plat
        # 只出现一次（函数签名）说明「收了但没用」——那是假支持
        uses = src.count("ret_date")
        assert uses >= 2, \
            "%s 只在签名里出现 ret_date（%d 次），没有真实使用" % (plat, uses)


def test_fliggy_turn_trip_ticket_is_wired():
    src = _src("fliggy")
    assert "tripType" in src and "backDate" in src


def test_tongcheng_rt_flag_and_back_date_are_wired():
    src = _src("tongcheng")
    assert '"RT"' in src, "同程 RT 标记缺失"
    assert "backDate" in src, "同程回程日字段缺失"


def test_round_trip_n_refuses_explicitly():
    """声明 n 的渠道：必须在 ret_date 在场时**显式落账**再返回空。

    静默忽略 ret_date 会把单程价当成往返总价（推送/走势据此报警），
    所以判据是「有 unsupported 落账」，不是「函数返回空」。
    """
    for plat, row in CHANNEL_DIMENSIONS.items():
        if row.get("round_trip") != "n":
            continue
        src = _src(plat)
        assert "unsupported" in src, \
            "%s 声明不支持往返，但没有 unsupported 落账（会静默吞掉）" % plat
        if plat == "qunar":
            continue
        assert "往返明细暂不支持" in src, \
            "%s 缺少往返不支持的用户可读文案" % plat


def test_tuniu_round_trip_is_native_not_fake():
    """途牛往返：r769 实测确认真能拿到渠道自算总价，声明随之是 y。

    历史两轮：
      * 曾留 ""（未验证）而实际「没做」——`_hoop` 只带去程日，单程价被
        当成往返总价落库；
      * r900 收敛为 n（显式 unsupported）；
      * r769 实测推翻「做不到」：`listFlight` 放两段（去程 + 反向回程日）
        时返回价就是往返总价（209 个航班 202 个满足 B = A + 反向最低价，
        B−A 中位数恰等于该最低价，无一条 B ≈ A），已接线 → y。

    这里守两件事：声明是 y 时**必须**真有 back_date 的两段构造；
    国际仍 unsupported（productList 单段，没实测过两段）。
    """
    st = dim_state("tuniu", "round_trip")
    assert st == "y", "途牛国内往返已实测可用，声明应与实现一致"
    src = _src("tuniu")
    assert "back_date" in src and "segmentList" in src, \
        "声明 y 却没有两段 segment 构造"
    assert "_fetch_intl_rt" in src and "avgTotalPrice" in src, (
        "国际往返已接，但代码里没有 H5 queryFlight/avgTotalPrice 通路")


def test_browser_supported_round_trip_reflects_reality():
    """浏览器端「有往返」必须来自**真的取到过往返价**的渠道。

    r740 实测把同程从 y 改成"未验证"（渠道产品支持往返，但 TT=RT/AD
    只对站点自身签名请求生效，裸打恒 444，窗历只有单程——本通路一行
    返程数据都没拿到），r815h 才由 book1/roundtrips 重新接通。携程
    r815i 由 PC 往返列表接通；浏览器端三家已验证 y。
    """
    from core.channels import BROWSER_CHANNELS, browser_supported
    assert browser_supported("round_trip")
    assert "fliggy" in BROWSER_CHANNELS
    assert dim_state("fliggy", "round_trip") == "y"
    assert dim_state("ctrip", "round_trip") == "y", (
        "携程 PC round-...&containstax=1 已实测出「往返含税价」"
        "（r815i 上海→东京 6 条），应记 y")
    assert dim_state("qunar", "round_trip") == "n", (
        "去哪儿网页版 PC/H5 均已停服（2026-11），矩阵记停")
    assert dim_state("tongcheng", "round_trip") == "y", (
        "同程国内往返已由 book1/roundtrips 接口接通（atp 产品总价），"
        "应记 y；国际往返仍走页面两步流，卡点写在 DIMENSION_NOTES")


# ---- merged from tests/test_r723_sms_code_is_login_wall.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SMS_CODE_PAGE = """<hierarchy>
<node index="0" text="请输入验证码" resource-id="" class="android.widget.TextView"
      bounds="[40,600][400,650]" clickable="false" />
<node index="1" text="验证码已发送到 +86 199****8573" resource-id=""
      class="android.widget.TextView" bounds="[40,700][600,740]" clickable="false" />
<node index="2" text="46秒后重发" resource-id=""
      class="android.widget.TextView" bounds="[40,780][300,820]" clickable="false" />
</hierarchy>"""

PHONE_PAGE = """<hierarchy>
<node index="0" text="请输入手机号" resource-id="" class="android.widget.EditText"
      bounds="[40,600][600,660]" clickable="true" />
<node index="1" text="获取验证码" resource-id=""
      class="android.widget.TextView" bounds="[600,700][860,760]" clickable="true" />
</hierarchy>"""

FLIGHT_LIST = """<hierarchy>
<node index="0" text="上海" resource-id="" class="android.widget.TextView"
      bounds="[40,200][200,260]" clickable="false" />
<node index="1" text="¥1360" resource-id="" class="android.widget.TextView"
      bounds="[600,400][860,460]" clickable="false" />
<node index="2" text="01.27" resource-id="" class="android.widget.TextView"
      bounds="[40,300][200,340]" clickable="false" />
</hierarchy>"""


def _base():
    import logging
    return AppCrawler({"user_data_dir": "_scratch/r723_data"},
                      logging.getLogger("r723"))


def test_sms_code_page_counts_as_login_wall():
    """输入验证码的页面必须判成登录墙（否则会被当成普通页继续操作）。"""
    assert _base().is_login_wall(SMS_CODE_PAGE) is True


def test_phone_entry_page_still_counts():
    assert _base().is_login_wall(PHONE_PAGE) is True


def test_normal_page_is_not_login_wall():
    """负控：普通列表页不能判成登录墙，否则每轮都被当成掉登录。"""
    assert _base().is_login_wall(FLIGHT_LIST) is False
    assert _base().is_login_wall("") is False


@pytest.mark.parametrize("plat", list(APP_CHANNELS))
def test_each_app_channel_uses_same_login_judgement(plat):
    """各 App 渠道的 `_is_login_page` 必须与基类同源。

    子类各写一份判据，就会出现「基类加了验证码页、子类没跟」的漂移——
    r723 的缺陷正是这样产生的。
    """
    from crawlers import REGISTRY
    cls = REGISTRY.get(plat)
    assert cls is not None, "渠道 %s 未注册" % plat
    inst = cls({"user_data_dir": "_scratch/r723_data"},
               __import__("logging").getLogger("r723"))
    if type(inst).__dict__.get("_is_login_page") is None:
        # 子类没有私有判据：直接走基类 is_login_wall，这本身即同源。
        # 仍要证明「验证码页是登录墙、普通列表不是」在它身上成立。
        assert inst.is_login_wall(SMS_CODE_PAGE) is True
        assert inst.is_login_wall(FLIGHT_LIST) is False
        return
    # 验证码页：两份判据必须给同一个答案
    assert inst._is_login_page(SMS_CODE_PAGE) == inst.is_login_wall(SMS_CODE_PAGE), (
        "%s 的 _is_login_page 与基类登录墙判据不一致（验证码页）" % plat)
    assert inst._is_login_page(PHONE_PAGE) == inst.is_login_wall(PHONE_PAGE), (
        "%s 的 _is_login_page 与基类登录墙判据不一致（手机号页）" % plat)


# ---- merged from tests/test_r726_empty_dump_not_a_predicate.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

@pytest.fixture(autouse=True)
def _fake_clock(monkeypatch):
    """这些用例只测判据，不该真等 30s。

    只 patch `sleep` 不够：`_await_home` 的 deadline 用 `time.time()` 算，
    真时钟不动就仍然会空转满 30 秒（实测本文件跑了 30.5s）。所以换成
    一个「sleep 即前进」的假时钟。
    """
    class _Clock:
        def __init__(self):
            self.now = 1000.0

        def time(self):
            return self.now

        def sleep(self, s=0):
            self.now += float(s or 0)

        def __getattr__(self, name):
            import time as _t
            return getattr(_t, name)

    clock = _Clock()
    monkeypatch.setattr(nav, "time", clock)
    return clock


class FakeDev:
    """按帧序列返回 dump；`tap` 之后切到另一组帧（模拟页面变化）。"""

    def __init__(self, frames, after_tap=None):
        self.frames = list(frames)
        self.after_tap = list(after_tap or [])
        self.taps = []

    def dump(self, *a, **k):
        if self.frames:
            return self.frames.pop(0)
        return ""

    def tap(self, x, y):
        self.taps.append((x, y))
        if self.after_tap:
            self.frames = list(self.after_tap)
            self.after_tap = []
        return True

    def keyevent(self, *a, **k):
        return True


def _home_xml(intl=False, from_city="上海", to_city="北京"):
    """最小可用的智行首页 dump（含「机票查询」；国际档带舱位行）。"""
    parts = [
        '<node text="机票查询" bounds="[400,700][500,800]" />',
        '<node text="%s" bounds="[60,460][90,484]" />' % from_city,
        '<node text="%s" bounds="[810,460][850,484]" />' % to_city,
        '<node text="国内" bounds="[100,330][150,360]" />',
        '<node text="国际" bounds="[260,330][310,360]" />',
    ]
    if intl:
        parts.append(
            '<node text="经济/超级经济舱" bounds="[700,600][860,630]" />')
    return "<hierarchy>" + "".join(parts) + "</hierarchy>"


def test_empty_dump_is_not_treated_as_domestic():
    """空帧之后才是国际档：必须切到国内，而不是跳过切档。

    负控：修复前 `select_mode` 拿第一帧空串算出 `is_intl_form("")==False`
    → 判「已是国内档」直接返回 ok，`taps` 为空，本用例红。
    """
    dev = FakeDev(["", "", "", _home_xml(intl=True), _home_xml(intl=True)],
                  after_tap=[_home_xml(intl=False)])
    ok, detail = nav.select_mode(dev, intl=False)
    assert ok, detail
    assert dev.taps, "没点「国内」标签，说明把空帧判成了「已是国内档」"
    assert "已是" not in detail, detail


def test_await_home_reports_failure_when_never_ready():
    """一直拿不到页面要如实返回未就绪，不能当成「页面里没有该控件」。"""
    dev = FakeDev(["", "", ""])
    xml, ready = nav._await_home(dev, timeout_s=0.2)
    assert ready is False
    assert xml == ""


def test_select_mode_fails_loudly_on_no_page():
    dev = FakeDev([])
    ok, detail = nav.select_mode(dev, intl=False)
    assert ok is False
    assert "没取到首页" in detail, detail


def test_await_home_ignores_calendar_overlay():
    """停在「选择日期」弹层上不算首页（否则会在弹层上找城市行）。"""
    cal = ('<hierarchy><node text="Search_Calendar_Dialog_Title" />'
           '<node text="机票查询" bounds="[0,0][10,10]" /></hierarchy>')
    dev = FakeDev([cal, cal, _home_xml()])
    xml, ready = nav._await_home(dev, timeout_s=5)
    assert ready is True
    assert "Search_Calendar_Dialog_Title" not in xml


def test_route_setup_never_decides_on_a_bare_dump():
    """守卫：设航线路径上「dump → 立刻下找不到的结论」的写法不许再出现。

    不是样式检查——上面几条测行为，这条防后来者在新加的分支里重新引入
    同一个坑：`xml = dev.dump()` 紧跟 `ns = nodes(xml)` 就等于「空帧 ⇒
    找不到控件」。一律走 `_await_home`（它会区分没取到和真没有）。
    """
    src = io.open(os.path.join(ROOT, "crawlers", "app_zhixing_nav.py"),
                  encoding="utf-8").read()
    start = src.index("def set_flight_route")
    end = src.index("def _city_row", start)
    body = src[start:end]
    lines = body.splitlines()
    bad = []
    for i, line in enumerate(lines):
        if line.strip() != "xml = dev.dump()":
            continue
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if nxt.startswith("ns = nodes(xml)"):
            bad.append(i + 1)
    assert not bad, (
        "set_flight_route 第 %s 行还是裸 dump→nodes：空帧会被读成「页面没有"
        "该控件」，应改用 _await_home" % bad)


# ---- merged from tests/test_r971_boundary_single_source.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _read(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8").read()


# ---------------------------------------------------------------------------
# 1. 文档：权威节存在，且两类清单都写清
# ---------------------------------------------------------------------------
def test_authoritative_section_exists():
    if not os.path.exists(os.path.join(ROOT, "docs",
                                       "YIELD_AND_SESSION_STRATEGY.md")):
        pytest.skip("YIELD_AND_SESSION_STRATEGY 已删（W7 docs 二次精简），本门禁失去检查对象")
    s = _read("docs/YIELD_AND_SESSION_STRATEGY.md")
    assert "## 6.51" in s, "权威边界节丢了"
    sec = s[s.find("## 6.51"):]
    sec = sec[:sec.find("\n## 7. ")] if "\n## 7. " in sec else sec[:8000]
    # 必须写明"自动解"和"不做"两栏
    assert "自动解" in sec
    assert "不做" in sec
    # 自动解一侧的代表项
    for kw in ("滑块", "拼图", "算数", "文字", "ddddocr"):
        assert kw in sec, "自动解清单缺 %s" % kw
    # 不做一侧的代表项（文档里 recaptcha 写作小写，比较时统一大小写）
    low = sec.lower()
    for kw in ("极验", "recaptcha", "点选", "人脸"):
        assert kw.lower() in low, "不做清单缺 %s" % kw


def test_historical_doc_is_marked_superseded():
    """历史指南里"不绕过验证码/滑块"必须带「已被取代」并指回 §6.51。

    不是删掉原文（那会篡改历史决定），而是明确它已过期——
    否则后来的代理会照着它**一次都不试**。
    """
    if not os.path.exists(os.path.join(ROOT, "docs",
                                       "SESSION_EXPERIENCE_GUIDE_2026-11-02.md")):
        pytest.skip("历史指南已删（W2b 文档工程），本门禁失去检查对象")
    s = _read("docs/SESSION_EXPERIENCE_GUIDE_2026-11-02.md")
    assert "已被取代" in s or "不再是一律停手" in s, "历史文案没有标注已过期"
    assert "§6.51" in s, "没指回权威节"


# ---------------------------------------------------------------------------
# 2. 代码：强/简标记表必须与文档一致
# ---------------------------------------------------------------------------
def test_strong_marks_keep_semantic_and_behavioral_types():
    """强人机必须继续被 upcast：极验/天御/recaptcha/人脸。

    注：点选题自 r1063 T21 起属于**可解图像题**（`captcha.classify_kind`
    判 click，有检测后端时可尝试），不再放强人机表——这里同步收紧，
    避免旧断言把已实现的能力重新判死。
    """
    strong = " ".join(slider._STRONG_MARKS).lower()
    for kw in ("geetest", "tcaptcha", "recaptcha", "人脸"):
        assert kw in strong, "强人机标记缺 %s（会被误判成简单题去解）" % kw


def test_simple_marks_keep_slider_and_puzzle():
    """简单侧必须包含通用滑块与**携程拼图**（不含"滑块"字样的那种）。"""
    simple = " ".join(slider._SIMPLE_MARKS)
    for kw in ("拖动滑块", "滑动验证", "拼图验证"):
        assert kw in simple, "简单滑块标记缺 %s" % kw


def test_classify_upcasts_strong_before_simple():
    """顺序即安全侧：两个标记同时出现时必须判 strong，不许去解。"""
    t = slider.classify("极验 gt4 拖动滑块 slide-verify", "")
    assert t.name == "strong", t.name


def test_click_captcha_is_reported_but_not_solved():
    """点选题要单独报出来（对操作员有信息量），但不提供解法。"""
    kind = captcha.classify_kind("请按顺序点击【天】【安】【门】")
    assert kind.name == "click", kind.name
    assert not hasattr(captcha, "solve_click"), "不该有解点选题的实现"


def test_empty_page_is_unknown_not_simple():
    """空页面不能默认成"可以试"——那是最容易把强人机当简单题的时刻。"""
    assert slider.classify("", "").name == "unknown"
