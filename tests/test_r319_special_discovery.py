# -*- coding: utf-8 -*-
"""r319 特价监控 P2：双源发现解析/过滤/配对/去抖/核实决策（纯函数面）。

夹具按调研实证形态构造（_scratch/worker_r319_special_{ctrip,others}.md）：
- 途牛 queryCheapTickets：cityFlightInfo.singleTrip/roundTrip + beginCity
  （priceBase 裸价、orgCityIata/dstCityIata、departureDate、discount、returnDate）
- 携程 15380 低价日历：priceList[].departDate=/Date(ms+0800)/、price（=列表
  有票 tprice 同口径）、尾部 0 元填充（381 天实测）

宁缺勿错三线：0 元尾过滤、PRICE_MIN/MAX 带、过期日/越窗过滤；
推送口径=跨渠道核实价（源价只做触发器——tuniu 裸价/ctrip 含税混源）。"""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.models import PRICE_MIN  # noqa: E402
from core.specials import (  # noqa: E402
    SPECIAL_DEST_POOL, SpecialDeal, SpecialWatch, build_special_push,
    ctrip_calendar_deals, deals_from_ctrip_board, deals_from_fliggy_board,
    deals_from_tuniu, pair_ctrip_returns, select_for_verify, should_push,
    special_due, tuniu_link, verify_verdict,
)

_TODAY = date(2026, 10, 16)


def _watch(**kw):
    base = {"enabled": True, "from": "SHA", "from_name": "上海",
            "max_price": 400}
    base.update(kw)
    return parse_watch(base)


def parse_watch(d):
    from core.specials import parse_specials
    return parse_specials([d], _TODAY)[0]


# ---------- 途牛榜单解析 ----------

def _tuniu_payload():
    return {"success": True, "data": {"cityFlightInfo": {
        "singleTrip": [
            {"priceBase": 450, "orgCityIata": "SHA", "dstCityIata": "BJS",
             "orgCityName": "上海", "dstCityName": "北京",
             "arlineCompany": "东航", "airCompanyIatacode": "MU",
             "departureDate": "2026-10-20", "discount": 2.1,
             "returnDate": None},
            # 异出发地（airCom 分组泄漏形态）：出发地闸必须挡
            {"priceBase": 370, "orgCityIata": "PEK", "dstCityIata": "SHA",
             "orgCityName": "北京", "dstCityName": "上海",
             "arlineCompany": "东航", "departureDate": "2026-10-21",
             "discount": 1.7, "returnDate": None},
            # 0/垃圾价：价带挡
            {"priceBase": 0, "orgCityIata": "SHA", "dstCityIata": "KMG",
             "orgCityName": "上海", "dstCityName": "昆明",
             "departureDate": "2026-10-22", "discount": 0,
             "returnDate": None},
            # 越窗（days=30 之外）：日期窗挡
            {"priceBase": 300, "orgCityIata": "SHA", "dstCityIata": "URC",
             "orgCityName": "上海", "dstCityName": "乌鲁木齐",
             "departureDate": "2026-12-01", "discount": 1.5,
             "returnDate": None},
            # 烂日期形态：解析失败跳过不炸
            {"priceBase": 300, "orgCityIata": "SHA", "dstCityIata": "XMN",
             "orgCityName": "上海", "dstCityName": "厦门",
             "departureDate": "2026-13-99", "discount": 1.5,
             "returnDate": None},
            # 缺机场码：iata3 守卫挡
            {"priceBase": 300, "orgCityIata": "", "dstCityIata": "SYX",
             "orgCityName": "上海", "dstCityName": "三亚",
             "departureDate": "2026-10-23", "discount": 1.6,
             "returnDate": None},
        ],
        "roundTrip": [
            {"priceBase": 880, "orgCityIata": "SHA", "dstCityIata": "CAN",
             "orgCityName": "上海", "dstCityName": "广州",
             "arlineCompany": "南航", "departureDate": "2026-10-21",
             "discount": 2.0, "returnDate": "2026-10-25"},
        ],
        "airComName": None},
        "beginCityCode": "2500", "beginCityName": "上海"}}


class TestTuniuBoard(unittest.TestCase):
    def test_filters_and_fields(self):
        w = _watch(max_price=900)   # 榜单价 ≤ 心理线才算候选（450/880 进）
        deals = deals_from_tuniu(_tuniu_payload(), w, _TODAY)
        keys = [(d.to_code, d.date) for d in deals]
        self.assertIn(("BJS", "2026-10-20"), keys)
        # 异出发地/垃圾价/越窗/烂日期/缺码 全数被挡
        self.assertEqual(len(deals), 2)
        by_key = {d.to_code: d for d in deals}
        self.assertEqual(by_key["BJS"].src_price, 450)
        self.assertEqual(by_key["BJS"].airline, "东航")
        self.assertEqual(by_key["BJS"].discount, "2.1折")
        self.assertEqual(by_key["CAN"].ret_date, "2026-10-25")
        self.assertEqual(by_key["CAN"].ret_price, 880)

    def test_over_line_dropped(self):
        """榜单价 > 心理线：不算候选（触发器语义）。"""
        w = _watch(max_price=400)
        deals = deals_from_tuniu(_tuniu_payload(), w, _TODAY)
        self.assertEqual(deals, [])

    def test_origin_gate(self):
        """出发地闸：只放行 orgCityIata=订阅出发地的行（SHA 订阅不吃
        PEK→SHA 那条；PEK 订阅恰好吃它）。"""
        w = parse_watch({"enabled": True, "from": "PEK", "from_name": "北京",
                         "max_price": 900})
        deals = deals_from_tuniu(_tuniu_payload(), w, _TODAY)
        self.assertEqual([d.from_code for d in deals], ["PEK"])
        self.assertEqual(deals[0].to_code, "SHA")

    def test_deep_links(self):
        # 单程=TuniuCrawler.list_url 单源直用（同源铁律，校准轮对齐
        # 现役推送链接口径）；往返=cheapList.js 官方 round 模板
        self.assertEqual(
            tuniu_link("SHA", "BJS", "2026-10-20", ""),
            "https://m.tuniu.com/flight/domestic/new/"
            "SHA_BJS_OW_1_0_0?deptDate=2026-10-20&isGo=0")
        self.assertEqual(
            tuniu_link("SHA", "CAN", "2026-10-21", "2026-10-25"),
            "http://flight.tuniu.com/city_SHA_CAN/round/"
            "?start=2026-10-21&back=2026-10-25")
        d = deals_from_tuniu(_tuniu_payload(), _watch(max_price=900),
                             _TODAY)
        d = [x for x in d if x.to_code == "BJS"][0]
        self.assertTrue(d.link.startswith("https://m.tuniu.com/flight/"))

    def test_price_floor_band(self):
        """价带下限（99 元超特事件价按项目带挡，宁缺勿错与爬虫带同律）。"""
        self.assertGreater(PRICE_MIN, 0)
        payload = _tuniu_payload()
        payload["data"]["cityFlightInfo"]["singleTrip"].append(
            {"priceBase": PRICE_MIN - 1, "orgCityIata": "SHA",
             "dstCityIata": "HGH", "orgCityName": "上海", "dstCityName": "杭州",
             "departureDate": "2026-10-20", "discount": 0.9,
             "returnDate": None})
        deals = deals_from_tuniu(payload, _watch(), _TODAY)
        self.assertFalse(any(d.to_code == "HGH" for d in deals))


# ---------- 携程日历解析 ----------

def _ctrip_payload():
    return {"responseStatus": {"Ack": "Success"}, "priceList": [
        # 2026-10-25 ¥382（调研实证样本：/Date(ms+0800)/ 形态）
        {"departDate": "/Date(1792857600000+0800)/", "price": 382,
         "totalPrice": 522, "rate": 0, "flightNo": "", "airLine": ""},
        # 超线
        {"departDate": "/Date(1792512000000+0800)/", "price": 520,
         "totalPrice": 640, "rate": 0, "flightNo": "", "airLine": ""},
        # 0 元尾填充（+207 天尾部实测形态）
        {"departDate": "/Date(1796054400000+0800)/", "price": 0,
         "totalPrice": 0, "rate": 0, "flightNo": "", "airLine": ""},
        # 价带下限外
        {"departDate": "/Date(1792771200000+0800)/", "price": PRICE_MIN - 1,
         "totalPrice": 0, "rate": 0, "flightNo": "", "airLine": ""},
        # 越窗（days=30）
        {"departDate": "/Date(1796054400000+0800)/", "price": 300,
         "totalPrice": 420, "rate": 0, "flightNo": "", "airLine": ""},
        # 烂日期形态
        {"departDate": "nonsense", "price": 300, "totalPrice": 420,
         "rate": 0, "flightNo": "", "airLine": ""},
    ]}


class TestCtripCalendar(unittest.TestCase):
    def test_decode_and_filters(self):
        w = _watch()
        deals = ctrip_calendar_deals(_ctrip_payload(), "SZX", "KMG", "昆明",
                                     w, _TODAY)
        self.assertEqual(len(deals), 1)
        d = deals[0]
        self.assertEqual(d.date, "2026-10-25")
        self.assertEqual(d.src_price, 382)
        self.assertEqual(d.src, "ctrip")
        self.assertTrue(d.link.startswith(
            "https://m.ctrip.com/html5/flight/taro/first"))
        self.assertIn("dcity=SZX", d.link)
        self.assertIn("acity=KMG", d.link)
        self.assertIn("ddate=2026-10-25", d.link)

    def test_soft_reject_empty(self):
        """软拒形态③（200 Success 空壳）：返回空表不炸。"""
        w = _watch()
        self.assertEqual(ctrip_calendar_deals({}, "SZX", "KMG", "昆明",
                                              w, _TODAY), [])
        self.assertEqual(ctrip_calendar_deals(
            {"responseStatus": {"Ack": "Success"}}, "SZX", "KMG", "昆明",
            w, _TODAY), [])

    def test_year_low_word(self):
        """「年度最低」词面（校准轮落地）：载荷整年有效价最低 300，
        候选价 ≤年低×1.01 打词面——分布比才筛得出真降价。"""
        w = _watch(days=180, max_price=400)
        # 1792857600=10-25（9 天）；1792512000=10-21（5 天）；
        # 1792857600+75*86400=2027-01-08（84 天，>60 出窗=年低本体）
        _far = (1792857600 + 75 * 86400) * 1000
        payload = {"priceList": [
            {"departDate": "/Date(1792857600000+0800)/", "price": 301,
             "totalPrice": 420},                      # ≤299×1.01 → 打
            {"departDate": "/Date(1792512000000+0800)/", "price": 380,
             "totalPrice": 500},                      # 年内但非低 → 不打
            {"departDate": f"/Date({_far}+0800)/", "price": 299,
             "totalPrice": 410},                      # 年低本体（越窗）
        ]}
        deals = ctrip_calendar_deals(payload, "SZX", "KMG", "昆明",
                                     w, _TODAY, days=60)
        words = {d.src_price: d.discount for d in deals}
        self.assertEqual(words[301.0], "年度最低")
        self.assertEqual(words[380.0], "")

    def test_reverse_window_relaxed(self):
        """返程解析放宽窗（Soldier P3#7）：days 形参覆盖 watch.days——
        去程贴 30 天窗尾时，返程日（去程后 N 天，生产实参=days+7）在
        去程窗外的合法形态不再被滤。"""
        w = _watch(days=30)
        # /Date(ms)/：2026-11-20 00:00+08 = 1792857600 + 26*86400（距
        # 今日 35 天：>30 去程窗外，≤37 返程窗内）
        ms = (1792857600 + 26 * 86400) * 1000
        payload = {"priceList": [
            {"departDate": f"/Date({ms}+0800)/", "price": 380,
             "totalPrice": 500}]}
        strict = ctrip_calendar_deals(payload, "KMG", "SZX", "深圳",
                                      w, _TODAY)
        relaxed = ctrip_calendar_deals(payload, "KMG", "SZX", "深圳",
                                       w, _TODAY, days=37)
        self.assertEqual(strict, [])            # 11-20 距今日 35 天 >30
        self.assertEqual(len(relaxed), 1)       # 返程窗（30+7）内命中
        self.assertEqual(relaxed[0].date, "2026-11-20")


class TestCtripBoard(unittest.TestCase):
    """19728 主题榜解析（夹具按 r319d 探针实证形态）：
    routes[].departCity/arriveCity{code,name} + pl[]{price,departDate,
    jumpUrl,isContainsTax:False}。"""

    def _board_payload(self):
        return {"routes": [
            {"departCity": {"code": "SHA", "name": "上海"},
             "arriveCity": {"code": "LHW", "name": "兰州"},
             "pl": [{"price": 200, "departDate": "2026-10-20",
                     "returnDate": "", "decRate": -0.74,
                     "jumpUrl": "https://m.ctrip.com/html5/flight/pages/"
                                "first?dcity=SHA&acity=LHW"
                                "&ddate=2026-10-20"}]},
            # 异出发地（策展组替换失效形态）：出发地闸挡
            {"departCity": {"code": "BJS", "name": "北京"},
             "arriveCity": {"code": "HLD", "name": "海拉尔"},
             "pl": [{"price": 200, "departDate": "2026-10-22",
                     "jumpUrl": "https://m.ctrip.com/x"}]},
            # 0 价 + 烂日期
            {"departCity": {"code": "SHA", "name": "上海"},
             "arriveCity": {"code": "XMN", "name": "厦门"},
             "pl": [{"price": 0, "departDate": "2026-10-21"},
                    {"price": 300, "departDate": "2026-13-99"}]},
            # 越窗（days=30 之外 12-14）+ 缺 jumpUrl（回退构造深链）
            {"departCity": {"code": "SHA", "name": "上海"},
             "arriveCity": {"code": "DLC", "name": "大连"},
             "pl": [{"price": 300, "departDate": "2026-12-14"},
                    {"price": 300, "departDate": "2026-10-23",
                     "jumpUrl": ""}]},
        ]}

    def test_parse_filters_and_fields(self):
        w = _watch()
        deals = deals_from_ctrip_board(self._board_payload(), w, _TODAY)
        self.assertEqual([(d.to_code, d.date) for d in deals],
                         [("LHW", "2026-10-20"),
                          ("DLC", "2026-10-23")])
        d0 = deals[0]
        self.assertEqual(d0.src, "ctripbd")
        self.assertEqual(d0.src_price, 200)
        self.assertEqual(d0.to_name, "兰州")
        # decRate=-0.74 → 2.6 折（校准轮值域，同现役折扣词面口径）
        self.assertEqual(d0.discount, "2.6折")
        self.assertTrue(d0.link.startswith("https://m.ctrip.com/")
                        and "acity=LHW" in d0.link)
        # 缺 jumpUrl 回退构造 taro 深链
        d1 = deals[1]
        self.assertTrue(d1.link.startswith(
            "https://m.ctrip.com/html5/flight/taro/first"))

    def test_origin_gate_board(self):
        # IATA 精确匹配：BJS 出发行只进 from=BJS 的订阅（PEK≠BJS）
        w = parse_watch({"enabled": True, "from": "BJS",
                         "from_name": "北京", "max_price": 400})
        deals = deals_from_ctrip_board(self._board_payload(), w, _TODAY)
        self.assertEqual([d.from_code for d in deals], ["BJS"])
        self.assertEqual(deals[0].to_code, "HLD")


class TestFliggyBoard(unittest.TestCase):
    """飞猪 PC 榜解析（夹具按 r319f 实证形态）：data.flights[]
    {depCode,arrCode,arrName,depDate,price,discount,soldOut}。"""

    def _payload(self):
        return {"status": 200, "data": {"flights": [
            {"depCode": "SHA", "arrCode": "TYN", "arrName": "太原",
             "depDate": "2026-10-17", "price": 200, "discount": 1.9,
             "soldOut": False},
            # soldOut=true：无票价剔（quantity 守卫同语义）
            {"depCode": "SHA", "arrCode": "HRB", "arrName": "哈尔滨",
             "depDate": "2026-10-18", "price": 280, "discount": 1.5,
             "soldOut": True},
            # 异出发地闸
            {"depCode": "BJS", "arrCode": "CAN", "arrName": "广州",
             "depDate": "2026-10-17", "price": 350, "discount": None,
             "soldOut": False},
            # discount null（约半数形态）→ 空词面
            {"depCode": "SHA", "arrCode": "NKG", "arrName": "南京",
             "depDate": "2026-10-19", "price": 350, "discount": None,
             "soldOut": False},
        ]}}

    def test_parse_filters_and_fields(self):
        w = _watch()
        deals = deals_from_fliggy_board(self._payload(), w, _TODAY)
        self.assertEqual([(d.to_code, d.src_price, d.discount)
                          for d in deals],
                         [("TYN", 200, "1.9折"), ("NKG", 350, "")])
        self.assertEqual(deals[0].src, "fliggy")
        self.assertEqual(deals[0].to_name, "太原")
        self.assertTrue(deals[0].link.startswith(
            "https://sjipiao.fliggy.com/flight_search_result.htm"))
        self.assertIn("depCity=SHA", deals[0].link)
        self.assertIn("arrCity=TYN", deals[0].link)

    def test_origin_gate_fliggy(self):
        w = parse_watch({"enabled": True, "from": "BJS",
                         "from_name": "北京", "max_price": 900})
        deals = deals_from_fliggy_board(self._payload(), w, _TODAY)
        self.assertEqual([d.to_code for d in deals], ["CAN"])


class TestPairReturns(unittest.TestCase):
    def test_pair_within_window(self):
        w = _watch(max_price=450, round_trip_days=3)
        out = SpecialDeal(src="ctrip", from_code="SZX", to_code="KMG",
                          date="2026-10-25", src_price=382)
        rev = [SpecialDeal(src="ctrip", from_code="KMG", to_code="SZX",
                           date="2026-10-27", src_price=410),
               SpecialDeal(src="ctrip", from_code="KMG", to_code="SZX",
                           date="2026-10-29", src_price=350),   # 窗外(+4d)
               SpecialDeal(src="ctrip", from_code="KMG", to_code="SZX",
                           date="2026-10-26", src_price=500)]   # 窗内但超线
        pair_ctrip_returns([out], rev, w)
        self.assertEqual(out.ret_date, "2026-10-27")
        self.assertEqual(out.ret_price, 410)

    def test_round_trip_disabled(self):
        w = _watch(round_trip=False)
        out = SpecialDeal(src="ctrip", from_code="SZX", to_code="KMG",
                          date="2026-10-25", src_price=382)
        pair_ctrip_returns([out], [SpecialDeal(
            src="ctrip", from_code="KMG", to_code="SZX",
            date="2026-10-26", src_price=300)], w)
        self.assertEqual(out.ret_date, "")


# ---------- 候选选择 / 去抖 / 核实决策 ----------

class TestSelectAndVerify(unittest.TestCase):
    def _deals(self):
        return [SpecialDeal(src="tuniu", from_code="SHA", to_code="BJS",
                            date="2026-10-20", src_price=450),
                SpecialDeal(src="ctrip", from_code="SHA", to_code="KMG",
                            date="2026-10-25", src_price=382),
                SpecialDeal(src="tuniu", from_code="SHA", to_code="SYX",
                            date="2026-10-21", src_price=360),
                SpecialDeal(src="tuniu", from_code="SHA", to_code="XMN",
                            date="2026-10-22", src_price=399)]

    def test_cap_and_price_order(self):
        sel = select_for_verify(self._deals(), lambda k: None, cap=2)
        self.assertEqual([d.to_code for d in sel], ["SYX", "KMG"])

    def test_dedupe_seen_skipped_dropped_retried(self):
        seen = {"SHA|SYX|2026-10-21": 355.0}   # 已推 355
        sel = select_for_verify(self._deals(), lambda k: seen.get(k), cap=9)
        # SYX 源价 360 未比已推 355 低过 30 → 跳过；其余新键全进
        self.assertNotIn("SYX", [d.to_code for d in sel])
        seen2 = {"SHA|SYX|2026-10-21": 395.0}
        sel2 = select_for_verify(self._deals(), lambda k: seen2.get(k),
                                 cap=9)
        self.assertIn("SYX", [d.to_code for d in sel2])   # 降 35 ≥30 → 重核

    def test_cross_source_dedupe_keeps_lowest(self):
        """同 OD+日期双源各报一条（Soldier P2#1）：只核实/推送一次，
        保源价低者——special_key 不含 src。"""
        deals = self._deals() + [
            SpecialDeal(src="ctrip", from_code="SHA", to_code="SYX",
                        date="2026-10-21", src_price=350.0)]
        sel = select_for_verify(deals, lambda k: None, cap=9)
        syx = [d for d in sel if d.to_code == "SYX"]
        self.assertEqual(len(syx), 1)
        self.assertEqual(syx[0].src_price, 350.0)

    def test_blocked_cooldown_skips(self):
        """核实未过负缓存（Soldier P2#2）：blocked 命中的键当日跳过，
        cap 预算让给后续候选。"""
        deals = self._deals()
        sel = select_for_verify(deals, lambda k: None, cap=2,
                                blocked=lambda k: k == "SHA|SYX|2026-10-21")
        self.assertEqual([d.to_code for d in sel], ["KMG", "XMN"])

    def test_verify_verdict(self):
        # 全渠道零行 → 重试
        self.assertEqual(verify_verdict(None, 382, 400), ("retry", None))
        # 核实价比源价虚高 >15% → 弃
        self.assertEqual(verify_verdict(500, 382, 400), ("drop", "虚高"))
        # 核实价超心理线 → 弃（410>400，即便虚高带内也不推）
        self.assertEqual(verify_verdict(410, 382, 400), ("drop", "超线"))
        # 正常：以核实价推
        self.assertEqual(verify_verdict(395, 382, 400), ("push", 395.0))
        # 恰 15% 边界：382×1.15=439.3，439 虚高带内且 ≤450 → push
        self.assertEqual(verify_verdict(439, 382, 450), ("push", 439.0))

    def test_should_push_dedupe(self):
        # 首推
        self.assertTrue(should_push(410, None, 30))
        # 已推 410，本轮 405（降幅 <30）→ 不重推
        self.assertFalse(should_push(405, 410.0, 30))
        # 降到 375（降幅 ≥30）→ 重推
        self.assertTrue(should_push(375, 410.0, 30))


# ---------- 节流与消息 ----------

class TestGatingAndPush(unittest.TestCase):
    def test_special_due(self):
        self.assertTrue(special_due(1, 4, False))
        self.assertFalse(special_due(4, 4, False))
        self.assertTrue(special_due(5, 4, False))
        self.assertTrue(special_due(3, 4, True))   # 保存配置即触发

    def test_pool_sane(self):
        self.assertGreaterEqual(len(SPECIAL_DEST_POOL), 40)
        codes = [c for c, _n in SPECIAL_DEST_POOL]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertTrue(all(len(c) == 3 and c.isupper() and n
                            for c, n in SPECIAL_DEST_POOL))

    def test_build_push(self):
        w = _watch()
        d1 = SpecialDeal(src="ctrip", from_code="SHA", to_code="KMG",
                         date="2026-10-25", src_price=382,
                         ret_date="2026-10-27", ret_price=410,
                         link="https://m.ctrip.com/html5/flight/taro"
                              "/first?dcity=SHA&acity=KMG")
        d2 = SpecialDeal(src="tuniu", from_code="SHA", to_code="BJS",
                         date="2026-10-20", src_price=450, airline="东航",
                         link="http://flight.tuniu.com/city_SHA_BJS"
                              "/?start=2026-10-20")
        title, desp = build_special_push(w, [(d1, 385.0), (d2, 455.0)])
        self.assertIn("特价", title)
        self.assertIn("上海", title)
        # 核实价与源价双口径在场；深链在场；往返段在场
        # （币符全角 ￥——c330 C4 统一，半角 ¥ 是全库唯一分叉已退役）
        self.assertIn("昆明", desp)
        self.assertIn("￥385", desp)
        self.assertIn("返程", desp)
        self.assertIn("m.ctrip.com", desp)
        self.assertIn("北京", desp)
        self.assertIn("￥455", desp)
        self.assertIn("flight.tuniu.com", desp)
        self.assertNotIn("%s", desp)   # 词面不得裸露格式化占位

    def test_build_push_mobile_line_width(self):
        """行宽纪律（钉钉手机 ≤20 全角=40 列，校准轮 R18）：段内单 \n 分行，
        非 URL 行渲染宽 ≤40 列（CJK 记 2）；条目间 \n\n 分段。"""
        w = _watch()
        d1 = SpecialDeal(src="ctrip", from_code="SHA", to_code="KMG",
                         date="2026-10-25", src_price=382,
                         ret_date="2026-10-27", ret_price=410,
                         discount="年度最低",
                         link="https://m.ctrip.com/html5/flight/taro"
                              "/first?dcity=SHA&acity=KMG")
        _t, desp = build_special_push(w, [(d1, 385.0)])
        import re as _re
        for ln in desp.split("\n"):
            txt = _re.sub(r"\[.*?\]\(.*?\)", "购买直达", ln)
            width = sum(2 if ord(ch) > 0x2E7F else 1 for ch in txt)
            self.assertLessEqual(width, 40, ln)

    def test_build_push_roundtrip_total_not_return_price(self):
        """途牛 roundTrip 词面（Soldier P3#6）：priceBase=往返总价，
        返程段不得显价（会被读成返程单程价）——渲染「往返含返程」。"""
        w = _watch()
        d = SpecialDeal(src="tuniu", from_code="SHA", to_code="CAN",
                        date="2026-10-21", src_price=880,
                        ret_date="2026-10-25", ret_price=880,
                        link="http://flight.tuniu.com/city_SHA_CAN/round/"
                             "?start=2026-10-21&back=2026-10-25")
        _t, desp = build_special_push(w, [(d, 885.0)])
        self.assertIn("往返含返程 10-25", desp)
        self.assertNotIn("返程 10-25 ¥", desp)


if __name__ == "__main__":
    unittest.main()
