"""tuniu 列表路径 prate=20 占位守卫补挂（数据观测立案实锤）：

净化函数 _prate（途牛对无真值航班下发恒「20%」占位默认值，同航班
ctrip 实为 90-97 全背离——宁缺勿错置空）只挂在详情页路径，列表路径
_offers_to_flights 对 onTimeRate 原样透传（rstrip("%") 不清 20），
渲染端 prate_txt 只清 0 族不清 20，「准点20%」假数据直出。
"""
from crawlers.tuniu import TuniuCrawler


def _offer(on_time_rate):
    return {
        "price": 1200, "dep_date": "2026-10-06", "arr_date": "2026-10-06",
        "depart_time": "08:30", "arrive_time": "13:10",
        "flight_no": "MU8370", "airline": "东方航空",
        "onTimeRate": on_time_rate,
    }


def test_list_path_prate20_placeholder_purged():
    rows = TuniuCrawler._offers_to_flights([_offer("20%")])
    assert len(rows) == 1
    # v1.5.104 卫生改：占位置空后无值不落键（同族 avgDelay/discount 律），
    # 守卫语义不变——拦的形态从「空串落键」收紧为「无键」
    assert "prate" not in rows[0]


def test_list_path_prate20_bare_number_purged():
    rows = TuniuCrawler._offers_to_flights([_offer("20")])
    assert "prate" not in rows[0]


def test_list_path_prate20_decimal_and_int_purged():
    # "20.0"/数字 20 形态同族（详情页 _prate 已守的窄面，列表路径同口径）
    assert "prate" not in TuniuCrawler._offers_to_flights([_offer("20.0")])[0]
    assert "prate" not in TuniuCrawler._offers_to_flights([_offer(20)])[0]


def test_list_path_prate_truth_kept():
    rows = TuniuCrawler._offers_to_flights([_offer("94%")])
    assert rows[0]["prate"] == "94"


def test_list_path_prate_missing_empty():
    rows = TuniuCrawler._offers_to_flights([_offer(None)])
    assert "prate" not in rows[0]
