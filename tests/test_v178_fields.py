# -*- coding: utf-8 -*-
"""tuniu 黑卡价标记（supportBlack）落地钉。

调研 v178-B 立案：fareList[].flightPriceList[].supportBlack=true 政策
45/117 报价单成为选中最低价来源，报文零文字性会员门标注（键名推断，
非实证）；42/117 报价单仅有黑卡政策带 ADT 价（朴素排除黑卡=荒谬口径，
实证 2710 vs 9900 跨舱位）。裁决：不改选价口径，落透明标记——选中价
来自黑卡政策时 extra.blackCard=True（有值才落），WebUI/推送标「黑卡价」
让受众自判；口径取证（会员态对照）留 WATCH 勿当回归。
"""

from crawlers.tuniu import TuniuCrawler


# ---- cross_days 双信号降信守卫（observe_v178 §1b qunar PC 毒形态） ----

from core.flightnorm import cross_days as _xd


def _f(**kw):
    base = {"depDate": "2026-10-05", "arrDate": "2026-10-05",
            "depTime": "20:35", "arrTime": "20:50",
            "crossDayDesc": "+1天", "totalDuration": "24时15分"}
    base.update(kw)
    return base


def test_pc_poison_arrdate_outvoted():
    """qunar PC 经停行毒形态（实证 G581O1J：arrDate=当日，desc=+1天、
    时长 24时15分 双信号一致指 +1）→ 降信 arrDate 取 1。"""
    assert _xd(_f()) == 1


def test_arrdate_holds_single_signal():
    """仅 desc 矛盾（时长重算无匹配档）：arrDate 仍优先——单信号不降信，
    防「携程中转只给首段时长」类误杀（layoverSrc 先例反向）。"""
    assert _xd(_f(totalDuration="2时00分")) == 0


def test_arrdate_holds_signals_agree():
    """desc/时长与 arrDate 一致：原行为不变。"""
    assert _xd(_f(arrDate="2026-10-06")) == 1


def test_arrdate_outvoted_two_days():
    """双信号一致指 +2：同规则外推。"""
    assert _xd(_f(crossDayDesc="+2天", totalDuration="48时15分")) == 2


def _pl(black=None, plain=None, disc="6.7折"):
    """构造 flightPriceList：supportBlack true/false 各一政策。"""

    def _pr(sb, fare):
        return {"supportBlack": sb,
                "fareBreakdownList": [
                    {"psgType": "ADT", "baseFare": fare, "discount": disc}]}

    out = []
    if black is not None:
        out.append(_pr(True, black))
    if plain is not None:
        out.append(_pr(False, plain))
    return out


def test_black_min_price_flagged():
    """选中最低价来自黑卡政策 → 价格不变、blackCard=True。"""
    p, d, black = TuniuCrawler._adt_fare(_pl(black=2900, plain=4730))
    assert p == 2900.0 and d == "6.7折" and black is True


def test_plain_min_price_unflagged():
    """最低价来自普通政策 → 不落 blackCard 旗标。"""
    p, d, black = TuniuCrawler._adt_fare(_pl(black=5000, plain=4730))
    assert p == 4730.0 and black is False


def test_only_black_policies_flagged():
    """42/117 报价单仅有黑卡政策：价格保持黑卡价 + 旗标（勿丢行）。"""
    p, d, black = TuniuCrawler._adt_fare(_pl(black=2900))
    assert p == 2900.0 and black is True


def test_tie_prefers_plain():
    """黑卡/普通同价：按普通政策算（无旗标价优先，标记零误报）。"""
    p, d, black = TuniuCrawler._adt_fare(_pl(black=4730, plain=4730))
    assert p == 4730.0 and black is False


def test_empty_policy_list():
    """无政策：三元组 (None, '', False) 不变。"""
    assert TuniuCrawler._adt_fare([]) == (None, "", False)


def test_offer_row_carries_blackcard():
    """offer→row 透传：黑卡旗标行落 extra.blackCard=True（有值才落）。"""
    rows = TuniuCrawler._offers_to_flights([{
        "airline": "东方航空", "flight_no": "MU5634",
        "depart_time": "08:30", "arrive_time": "11:50",
        "dep_date": "2026-10-05", "arr_date": "2026-10-05",
        "price": 2900.0, "blackCard": True,
    }, {
        "airline": "东方航空", "flight_no": "MU5635",
        "depart_time": "09:30", "arrive_time": "12:50",
        "dep_date": "2026-10-05", "arr_date": "2026-10-05",
        "price": 4730.0,
    }])
    assert rows[0]["blackCard"] is True
    assert "blackCard" not in rows[1]
