# -*- coding: utf-8 -*-
"""携程 App 解析纯函数：卡片/表单/城市/日历坐标。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_ctrip_parse import (calendar_xy, is_form, is_list_page,
                                     is_login_wall, parse_city_candidates,
                                     parse_flight_cards, parse_form,
                                     parse_months)


def _card(no, dep="06:40", arr="09:00", price="700 ", airline="中国国航",
          dep_airport="浦东T2", arr_airport="大兴", extra=""):
    return f'''
<node index="0" text="" resource-id="第{no}航班" content-desc="第{no}航班"
      class="android.view.ViewGroup" bounds="[0,419][876,537]">
  <node text="{dep}" content-desc="第{no}航班出发时间" bounds="[72,437][203,476]" />
  <node text="{arr}" content-desc="第{no}航班到达时间" bounds="[267,437][398,476]" />
  <node text="¥" bounds="[798,447][828,475]" />
  <node text="{price}" content-desc="第{no}航班价格" bounds="[828,437][866,476]" />
  <node text="{dep_airport}" content-desc="第{no}航班出发机场+航站楼"
        bounds="[72,476][203,500]" />
  <node text="{arr_airport}" content-desc="第{no}航班到达机场+航站楼"
        bounds="[267,476][398,500]" />
  <node text="经济舱3.3折" content-desc="第{no}航班舱等信息" bounds="[720,480][866,500]" />
  <node text="{airline}" content-desc="第{no}航班航司信息" bounds="[40,514][240,536]" />
  {extra}
</node>'''


def _xml(body="", rotation="0"):
    return (f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<hierarchy rotation="{rotation}">{body}</hierarchy>')


def test_parse_flight_cards_reads_semantic_labels():
    rows = parse_flight_cards(_xml(_card("CA8322")))
    assert len(rows) == 1
    r = rows[0]
    assert r["flight_no"] == "CA8322"
    assert r["dep_time"] == "06:40"
    assert r["arr_time"] == "09:00"
    assert r["dep_airport"] == "浦东T2"
    assert r["arr_airport"] == "大兴"
    assert r["airline"] == "中国国航"
    assert r["cabin"] == "经济舱3.3折"
    assert r["price"] == 700.0


def test_parse_flight_cards_requires_price_and_valid_times():
    no_price = _card("CA1111", price="")
    no_price = no_price.replace(
        'content-desc="第CA1111航班价格"', 'content-desc="第CA1111航班其他"')
    bad_time = _card("CA2222", dep="--")
    page = _xml(_card("CA3333") + no_price + bad_time)
    rows = parse_flight_cards(page)
    assert [r["flight_no"] for r in rows] == ["CA3333"]


def test_parse_flight_cards_dedupes_same_flight_keeps_lowest():
    page = _xml(_card("MU5099", price="800 ") + _card("MU5099", price="700 "))
    rows = parse_flight_cards(page)
    assert len(rows) == 1
    assert rows[0]["price"] == 700.0


def test_parse_form_reads_city_and_date_desc():
    page = _xml('''
<node text="上海" content-desc="depart city" bounds="[48,522][408,594]" />
<node text="北京" content-desc="arrival city" bounds="[492,522][852,594]" />
<node text="11月16日周一" content-desc="depart date" bounds="[48,595][852,667]" />
''')
    assert is_form(page) is True
    assert parse_form(page) == {"dep": "上海", "arr": "北京",
                                "date": "11月16日周一"}


def test_parse_months_and_calendar_xy():
    page = _xml('''
<node text="2026年11月" bounds="[24,356][168,393]" />
<node text="2026年12月" bounds="[24,886][168,923]" />
<node text="2027年1月" bounds="[24,1416][153,1453]" />
''')
    assert parse_months(page) == [(2026, 11, 374), (2026, 12, 904),
                                 (2027, 1, 1434)]
    # 2026-11-01 是周日（第 0 列），16 日在第 3 行周一（第 1 列）
    assert calendar_xy(374, 2026, 11, 1) == (66, 425)
    assert calendar_xy(374, 2026, 11, 16) == (199, 625)
    # 2026-12-01 是周二（第 2 列），第一行
    assert calendar_xy(904, 2026, 12, 1) == (333, 955)
    assert calendar_xy(374, 2026, 2, 30) is None


def test_parse_city_candidates_prefers_search_result_over_search_box():
    page = _xml('''
<node text="广州" bounds="[0,240][410,290]" />
<node text="广州 \u200c白云机场 \u200c广东 \u200cCAN \u200c"
      bounds="[30,320][336,366]" />
<node text="广州" bounds="[720,590][816,634]" />
''')
    cands = parse_city_candidates(page, "广州")
    assert cands
    assert "CAN" in cands[0]["text"]
    assert cands[0]["cx"] == 183


def test_is_list_page_and_login_wall_do_not_cross_match():
    assert is_list_page(_xml(_card("CA8322"))) is True
    assert is_login_wall(_xml(_card("CA8322"))) is False
    wall = _xml('<node text="手机验证码登录" bounds="[0,0][100,50]" />')
    assert is_login_wall(wall) is True
    assert is_list_page(wall) is False


def test_intl_ordinal_cards_parse_without_fake_flight_no():
    """国际列表卡是「第7条航班」，没有航班号；不能把序号当航班号。"""
    path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "tests", "fixtures",
        "ctrip_intl_list.xml")
    with open(path, encoding="utf-8") as f:
        rows = parse_flight_cards(f.read())
    assert len(rows) >= 5
    r = [x for x in rows
         if x["dep_time"] == "09:15" and x["airline"] == "南方航空"][0]
    assert r["price"] == 1467.0
    assert r["flight_no"] == ""
    assert r["dep_airport"] == "浦东T2"
    assert r["arr_airport"] == "成田T1"
    assert r["aircraft"].startswith("空客320")
    same = [x for x in rows if x["dep_time"] == "09:35"]
    assert {"东方航空", "上海航空(共享)"} <= {x["airline"] for x in same}
