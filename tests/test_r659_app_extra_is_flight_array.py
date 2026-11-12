# -*- coding: utf-8 -*-
"""r659：App 渠道的 extra 必须是**航班数组**，与五个浏览器渠道同形。

缺陷现场：App 三条产出路径都写 `{"calendar": true, "source": "..."}`
这类元信息**对象**，而所有消费端都是
`if not isinstance(obj, list): continue`——
  * `webui._user_state` 列表池：整批跳过 → 页面一条航班都没有；
  * `Alerter._build_sections` 推送池：同样跳过 → 推送也不带 App；
  * `report.recent_platform_flights`：`if isinstance(obj, list) and obj`。
结果：库里有行、日志说采到了、页面与推送全空。这种「写入形状与读取
契约不一致」的缺陷不会抛异常，任何只测采集器的断言都看不出来——所以
这里直接断言**产出形状**，并另测一条真实的读取链路。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_zhixing import AppZhixingCrawler


def _crawler():
    c = AppZhixingCrawler.__new__(AppZhixingCrawler)
    c.name = "app_zhixing"
    return c


def test_detail_extra_is_array_of_flights():
    c = _crawler()
    rows = [{"flight_no": "CZ8212", "depart_time": "20:25",
             "arrive_time": "23:10", "price": 349.0}]
    out = c._to_prices(rows, "SHA", "CAN", "2026-12-05")
    assert len(out) == 1, "一渠道一日期只应产出一行（消费端按此去重）"
    obj = json.loads(out[0].extra)
    assert isinstance(obj, list), "extra 必须是数组，实际 %r" % type(obj)
    assert obj and isinstance(obj[0], dict)
    assert obj[0]["price"] == 349.0
    assert obj[0]["code"] == "CZ8212"
    assert obj[0]["depTime"] == "20:25" and obj[0]["arrTime"] == "23:10"


def test_one_row_carries_all_flights_of_that_date():
    """同日期多班合成一行：分开写会被 (platform, 航线, 日期) 去重丢掉。"""
    c = _crawler()
    rows = [{"flight_no": "CZ8212", "depart_time": "20:25",
             "arrive_time": "23:10", "price": 349.0},
            {"flight_no": "MU5317", "depart_time": "13:35",
             "arrive_time": "23:05", "price": 360.0}]
    out = c._to_prices(rows, "SHA", "CAN", "2026-12-05")
    assert len(out) == 1
    obj = json.loads(out[0].extra)
    assert len(obj) == 2, "两班必须都在 extra 里：%s" % obj
    assert out[0].price == 349.0, "行头价应是最低价"
    assert out[0].flight_no == "CZ8212", "行头航班号应跟随最低价那班"


def test_calendar_extra_is_array_too():
    """日历价同样要能进列表池：写成对象时整页只剩明细、日历全消失。"""
    from crawlers.app_zhixing import _cal_extra
    obj = json.loads(_cal_extra(450.0, "2026-11-07"))
    assert isinstance(obj, list) and obj
    assert obj[0]["price"] == 450.0
    assert obj[0]["calendar"] is True
    assert not obj[0]["depTime"], "日历行不得伪造时刻"


def test_produced_rows_are_visible_to_list_pool():
    """端到端形状检查：产出必须能被 webui 的列表池收集器吃下。

    只断言爬虫产出形状不够——真正丢数据的是读取侧的类型门。这里直接
    复现读取侧的两个判据（webui 与 alerter 同款），任一处不满足即失败。
    """
    c = _crawler()
    out = c._to_prices([{"flight_no": "CZ8212", "depart_time": "20:25",
                         "arrive_time": "23:10", "price": 349.0}],
                       "SHA", "CAN", "2026-12-05")
    obj = json.loads(out[0].extra)
    # webui._user_state: if not isinstance(obj, list): continue
    assert isinstance(obj, list)
    # 其后的 real_items 判据：code/depTime/arrTime 三者齐备
    real = [x for x in obj if isinstance(x, dict)
            and str(x.get("code") or "").strip()
            and str(x.get("depTime") or "").strip()
            and str(x.get("arrTime") or "").strip()]
    assert real, "列表池会把它当『日历薄行』，明细整片消失"
    # Alerter._build_sections 走同一形状 + 要求 price 键
    assert all("price" in x for x in obj)
