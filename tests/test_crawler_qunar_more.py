# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r385_qunar_1999_layering.py
- tests/test_r664_qunar_parse.py
- tests/test_r686_qunar_city_history_row.py
- tests/test_r694_qunar_low_fare.py
- tests/test_r702_qunar_single_trip_reset.py
- tests/test_r939_qunar_multi_city.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import crawlers.app_qunar as q
import io
import json
import logging
import os
import sys

from crawlers.app_qunar import AppQunarCrawler, _ID_BACK_DATE_LL, _pick_city_row
from crawlers.app_qunar_lowfare import is_low_fare_page, parse_low_fare_strip
from crawlers.app_qunar_parse import detect_state, parse_flight_rows
from crawlers.qunar import QunarCrawler


# ---- merged from tests/test_r385_qunar_1999_layering.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t_r385")


def _src():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "crawlers", "qunar.py"),
              encoding="utf-8") as f:
        return f.read()


def test_risk_signal_still_flags_login_family():
    """信号层不变：1999/2008/code 8 仍上报 login 族，由 fetch 层分层。"""
    assert QunarCrawler._risk_signal(
        '{"bstatus":{"code":1999}}').status == "login"
    assert QunarCrawler._risk_signal(
        '{"bstatus":{"code":2008},"code":8}').status == "login"
    # 真登录页文本仍是 login（不受 1999 分层影响）
    assert QunarCrawler._risk_signal(
        '{"msg":"请先登录后查看"}').status == "login"


def test_single_1999_is_soft_reject_not_login():
    src = _src()
    i = src.find('if risk == "login":')
    assert i > 0
    block = src[i:i + 2600]
    assert 'self.path_note("H5", "soft_reject"' in block, \
        "单次 1999 必须记 soft_reject（不冷却）"
    assert "免登录冷却" in block
    # 单次分支不得置 login_suspect
    seg = block[:block.find("else:")] if "else:" in block else ""
    assert "login_suspect = True" not in seg.split("if _n >= 2:")[0], seg


def test_two_consecutive_1999_escalate_only_without_auth_cookie():
    # 连续 ≥2 且认证 Cookie 不在场才升 login；Cookie 在场时是限流/软拒。
    assert QunarCrawler._qn1999_is_login(1, False) is False
    assert QunarCrawler._qn1999_is_login(2, False) is True
    assert QunarCrawler._qn1999_is_login(2, True) is False
    src = _src()
    i = src.find('if risk == "login":')
    block = src[i:i + 3000]
    assert "_qn1999_streak" in block
    assert "self._qn1999_is_login(_n, _auth_present)" in block
    assert "self._read_session_state()" in block
    # 只有“无认证 Cookie + 连续 ≥2”分支置 login_suspect
    j = block.find("if self._qn1999_is_login(")
    assert "login_suspect = True" in block[j:j + 600], block[j:j + 600]
    assert 'self.path_note("H5", "login"' in block[j:j + 700]


def test_success_clears_1999_streak():
    src = _src()
    i = src.find('detail="touch.qunar.com 国际列表"')
    assert i > 0, "国际成功落账点必须存在"
    block = src[max(0, i - 700):i]
    assert "_qn1999_streak.pop(" in block, "出数即清零连续计数"


def test_single_1999_schedules_one_same_round_retry():
    """A/B 显示 1.5 分钟自愈：单次必须在同轮短退避重试一次，且只一次。"""
    src = _src()
    assert "INTL_1999_RETRY_S" in src
    i = src.find('if risk == "login":')
    block = src[i:i + 6000]
    assert "_qn1999_retried" in block and "_intl_list_once(" in block
    assert "INTL_1999_RETRY_S" in block
    # 重试拿到数必须撤掉刚才的 soft_reject 记账并按成功落账
    assert 'self.paths.pop()' in block
    assert "同轮重试后放行" in block


def test_same_round_retry_is_single_day_scoped():
    """同轮重试是单日单页，不得再次解析成"登录"或写第二份软拒。"""
    src = _src()
    i = src.find("def _intl_list_once")
    assert i > 0
    fn = src[i:i + 2200]
    assert "touchInterList" in fn and "_parse_intl_response" in fn
    assert "path_note" not in fn, "重试纯取数，记账由调用方按真实结果做"


def test_streak_state_is_instance_scoped():
    a = QunarCrawler({}, _LOG)
    b = QunarCrawler({}, _LOG)
    a._qn1999_streak["SHA|LHR|2026-11-16"] = 2
    assert b._qn1999_streak == {}, "计数必须实例内（不跨实例串味）"


def test_legacy_1999_login_rows_show_as_soft(tmp_path):
    """历史 1999 行写的是 login；复发账必须按证据改判 soft（r385 A/B）。

    否则面板持续挂"登录态失效（需人工）"，催用户做无效重登——而那条
    路同会话 1.5 分钟就自愈。
    """
    from core.storage import PriceStorage
    st = PriceStorage(str(tmp_path / "p.db"))
    for i in range(4):
        st.save_fetch_path("qunar", "SHA", "LHR", "2026-11-16", "H5",
                           "login", note="国际列表 1999/8 未登录硬拒",
                           attempt_id="q%d" % i)
    row = next(r for r in st.failure_recurrence(24, 3) if r["path"] == "H5")
    assert row["status"] == "soft_reject"
    assert row["kind"] == "soft"
    assert "1999" in (row["evidence"] or {}).get("note", "")


def test_real_login_wall_still_login(tmp_path):
    """真登录页证据（passport/请先登录）不得被 1999 改判波及。"""
    from core.storage import PriceStorage
    st = PriceStorage(str(tmp_path / "p.db"))
    for i in range(4):
        st.save_fetch_path("qunar", "SHA", "LHR", "2026-11-16", "H5",
                           "login", note="登录门（passport）",
                           attempt_id="p%d" % i)
    row = next(r for r in st.failure_recurrence(24, 3) if r["path"] == "H5")
    assert row["status"] == "login" and row["kind"] == "login"


# ---- merged from tests/test_r664_qunar_parse.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _n(text, x1, y1, x2, y2):
    return ('<node text="%s" resource-id="" class="android.widget.TextView"'
            ' bounds="[%d,%d][%d,%d]" />' % (text, x1, y1, x2, y2))


def _card(dep_y, dep, arr, code, price, discount=None, name_prefix="航司"):
    """按真机 dump 的坐标画一张卡片。

    真机上「已减」「¥」「70」三个节点在**同一行**（实测 y=625–647），
    连排在票价右侧；票价本身在下一行的右列。这里必须照样画——
    早期 fixture 把优惠标签画到了票价上方 66px（真机没有这种形态），
    结果测试针对的是一个不存在的布局。
    """
    parts = [
        _n(dep, 36, dep_y, 120, dep_y + 50),
        _n(arr, 270, dep_y, 354, dep_y + 50),
        _n("北京大兴", 36, dep_y + 34, 120, dep_y + 57),
        _n("虹桥T2", 267, dep_y + 34, 351, dep_y + 57),
        _n(name_prefix + code, 57, dep_y + 73, 160, dep_y + 94),
        _n("经济舱1.8折", 1413, dep_y + 72, 1563, dep_y + 95),
        _n("¥", 1492, dep_y + 53, 1504, dep_y + 94),
        _n(str(price), 1504, dep_y + 50, 1563, dep_y + 94),
    ]
    if discount:
        # 真机形态：与票价同一行（cy 差 0），在票价右侧连排
        parts += [_n("已减", 1560, dep_y + 50, 1594, dep_y + 72),
                  _n("¥", 1594, dep_y + 50, 1604, dep_y + 72),
                  _n(str(discount), 1604, dep_y + 50, 1623, dep_y + 72)]
    return "".join(parts)


def _xml(*cards):
    return ('<?xml version="1.0"?><hierarchy rotation="0">'
            + "".join(cards) + "</hierarchy>")


def test_chinese_prefixed_flight_no_is_parsed():
    """「南航CZ8889」必须取出 CZ8889。"""
    xml = _xml(_card(363, "20:30", "22:50", "CZ8889", 280))
    rows = parse_flight_rows(xml)
    assert rows and rows[0]["flight_no"] == "CZ8889", rows


def test_discount_label_is_not_a_fare():
    """「已减 ¥70」是优惠标签，票价仍是 ¥378。"""
    xml = _xml(_card(746, "21:35", "23:40", "MU123", 378, discount=70))
    rows = parse_flight_rows(xml)
    assert rows[0]["price"] == 378, rows


def test_cards_are_paired_by_row_not_document_order():
    """相邻卡片不得串行：每张卡片的到达时刻取自本行。"""
    xml = _xml(
        _card(363, "20:30", "22:50", "CZ8889", 280),
        _card(589, "20:30", "22:40", "MU5130", 377),
        _card(746, "21:35", "23:40", "MU123", 378, discount=70),
    )
    rows = parse_flight_rows(xml)
    got = [(r["flight_no"], r["depart_time"], r["arrive_time"], r["price"])
           for r in rows]
    assert got == [("CZ8889", "20:30", "22:50", 280),
                   ("MU5130", "20:30", "22:40", 377),
                   ("MU123", "21:35", "23:40", 378)], got


def test_card_without_flight_identity_is_not_a_price_row():
    """无航班号的卡片（优惠/占位）不得变成 ¥20 假票价。

    2026-11-03 生产实测：app_qunar 多航线落库 `code=""、price=20/25`，
    被孤低价守卫拦在推送层；根因是解析器把无身份卡也 append 成行。
    """
    xml = _xml(_card(363, "08:25", "12:00", "", 20))
    assert parse_flight_rows(xml) == []


def test_below_band_price_is_not_recorded_as_fare():
    """有航班号但价格 <100 时保留身份、price=None，不落假票价。"""
    xml = _xml(_card(363, "08:25", "12:00", "MU123", 20))
    rows = parse_flight_rows(xml)
    assert rows and rows[0]["flight_no"] == "MU123"
    assert rows[0]["price"] is None, rows


def test_missing_price_stays_none():
    """没有价格的卡片不得给 0 或猜价。"""
    xml = _xml(_n("20:30", 36, 363, 120, 413),
               _n("22:50", 270, 363, 354, 413),
               _n("南航CZ8889", 57, 436, 160, 457))
    rows = parse_flight_rows(xml)
    assert rows and rows[0]["price"] is None


def test_login_page_is_login_state():
    xml = ('<?xml version="1.0"?><hierarchy>'
           + _n("+86", 39, 673, 79, 706)
           + _n("请输入手机号", 159, 663, 1561, 717)
           + _n("获取验证码", 54, 785, 1546, 866)
           + "</hierarchy>")
    assert detect_state(xml) == "login"


def test_list_page_is_ok_state():
    xml = _xml(_card(363, "20:30", "22:50", "CZ8889", 280))
    assert detect_state(xml) == "ok"


def test_empty_only_on_explicit_copy():
    """只有明确的「没找到」文案才算 empty。"""
    xml = ('<?xml version="1.0"?><hierarchy>'
           + _n("没有找到符合条件的航班", 100, 700, 800, 740)
           + "</hierarchy>")
    assert detect_state(xml) == "empty"


# ---- r672：密集版结果页（价格右列 x≈772–863，不是 1490+） ----
def test_dense_result_page_prices_are_found():
    """结果页价格列实测 x=772–863；钉死「右列 x>=1200」会一个都取不到。

    现场：解析出航班行但 price 全 None → 账本记 no-priced-rows，
    用户看到「采到了 0 条」。判据必须是「屏宽右半屏」，不是固定像素。
    """
    def _price_row(top, dep, arr, code, price, discount=None):
        parts = [
            _n(dep, 36, top, 120, top + 50),
            _n(arr, 270, top, 354, top + 50),
            _n("北京大兴", 36, top + 34, 120, top + 57),
            _n("虹桥T2", 267, top + 34, 351, top + 57),
            _n("东航" + code, 57, top + 73, 160, top + 94),
            _n("¥", 772, top + 60, 786, top + 100),
            _n(str(price), 786, top + 57, 863, top + 100),
        ]
        if discount:
            parts += [_n("¥", 826, top + 130, 836, top + 152),
                      _n(str(discount), 836, top + 130, 856, top + 152)]
        return "".join(parts)

    xml = ('<?xml version="1.0"?><hierarchy rotation="0">'
           + _price_row(354, "20:45", "22:55", "KN5977", 1130)
           + _price_row(589, "21:20", "23:30", "HO1254", 1175)
           + "</hierarchy>")
    rows = parse_flight_rows(xml)
    assert len(rows) == 2, rows
    assert [r["price"] for r in rows] == [1130, 1175], rows
    assert [r["flight_no"] for r in rows] == ["KN5977", "HO1254"]


def test_wide_layout_still_works():
    """宽版列表页（价格 x≈1490+）不能被新判据弄坏——两套版面都要能读。"""
    xml = _xml(_card(363, "20:30", "22:50", "CZ8889", 280))
    rows = parse_flight_rows(xml)
    assert rows and rows[0]["price"] == 280, rows


def test_transfer_card_is_marked_not_sold_as_direct():
    """「停9时45分 / 全程12时45分」的卡片必须标成中转。

    真机（北京→上海 11-05）：首卡 21:20→10:05 ￥420 是中转，直飞 ￥455。
    不标 transCity，下游会把 12 小时的中转当直飞塞进直飞最优池，
    行头价也被 ￥420 顶掉。
    """

    def n(text, x1, y1, x2, y2):
        return ('<node text="%s" resource-id="" class="android.widget.TextView"'
                ' bounds="[%d,%d][%d,%d]" />' % (text, x1, y1, x2, y2))

    xml = ('<hierarchy>'
           + n("21:20", 39, 384, 200, 420)
           + n("10:05", 282, 384, 420, 420)
           + n("全程12时45分", 156, 383, 345, 404)
           + n("停9时45分", 156, 430, 345, 451)
           + n("420", 1511, 385, 1560, 431)
           + n("¥", 1500, 400, 1511, 426)
           + n("07:30", 39, 700, 200, 736)
           + n("09:45", 282, 700, 420, 736)
           + n("MU5186", 60, 770, 200, 795)
           + n("455", 1511, 700, 1560, 745)
           + n("¥", 1500, 715, 1511, 740)
           + '</hierarchy>')
    rows = parse_flight_rows(xml)
    assert len(rows) == 2, rows
    assert rows[0]["trans_city"] == "中转", rows[0]
    assert rows[1]["trans_city"] == "", rows[1]


def _intl_node(text, x1, y1, x2, y2, desc=""):
    return ('<node text="%s" content-desc="%s" class="android.widget.TextView"'
            ' bounds="[%d,%d][%d,%d]" />' % (text, desc, x1, y1, x2, y2))


def test_intl_card_price_comes_from_itemprice_desc():
    """国际列表的票价在 `|ItemPrice` 节点里，与 ¥ 符号**不相邻**。

    2026-11-01 22:43 现场（SHA→LHR 11-16，`nopriced-2026-11-16`）真实节点
    顺序：`¥ [778,400]` → `下单可减 [729,430]` → `¥35 [811,430]` →
    `3305 [789,385]`（desc 含 `QunarFlightInterList|ItemPrice`）。按「¥ +
    紧邻数字」取不到，整份列表 5 行全部 price=None。
    """
    p = "flight_search_rn|QunarFlightInterList|ItemPrice"
    xml = ('<hierarchy>'
           + _intl_node("02:25", 39, 384, 116, 426,
                        "flight_search_rn|QunarFlightInterList|ItemDepTime")
           + _intl_node("07:10", 283, 384, 357, 426,
                        "flight_search_rn|QunarFlightInterList|ItemArrTime")
           + _intl_node("中国国航CA847", 63, 463, 183, 486,
                        "flight_search_rn|QunarFlightInterList|SingleItemAviationName")
           + _intl_node("¥", 778, 400, 789, 426)
           + _intl_node("下单可减", 729, 430, 797, 454)
           + _intl_node("¥35", 811, 430, 841, 454)
           + _intl_node("3305", 789, 385, 861, 432, p)
           + '</hierarchy>')
    rows = parse_flight_rows(xml)
    assert rows, "一行都没解析出来"
    assert rows[0]["price"] == 3305, rows
    assert rows[0]["flight_no"] == "CA847", rows


def test_intl_card_without_itemprice_keeps_price_none():
    """没有 ItemPrice 时仍按「无价」处理，绝不给 0 或拿优惠金额充数。"""
    xml = ('<hierarchy>'
           + _intl_node("02:25", 39, 384, 116, 426)
           + _intl_node("07:10", 283, 384, 357, 426)
           + _intl_node("中国国航CA847", 63, 463, 183, 486)
           + _intl_node("¥", 778, 400, 789, 426)
           + _intl_node("下单可减", 729, 430, 797, 454)
           + _intl_node("¥35", 811, 430, 841, 454)
           + '</hierarchy>')
    rows = parse_flight_rows(xml)
    assert rows and rows[0]["price"] is None, rows


# ---- merged from tests/test_r686_qunar_city_history_row.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _n(text, x1, y1, x2, y2):
    return ('<node text="%s" resource-id="" class="android.widget.TextView"'
            ' bounds="[%d,%d][%d,%d]" />' % (text, x1, y1, x2, y2))


def _city_page(city="上海"):
    return ('<hierarchy>'
            + _n("选择目的地", 380, 120, 700, 160)
            + _n("搜索国家/城市/景点等", 87, 193, 294, 225)
            + _n("国内/港澳台", 60, 300, 200, 330)
            + _n("国际", 260, 300, 320, 330)
            + _n("历史选择", 40, 400, 140, 425)
            + _n("清除", 780, 400, 860, 425)
            + _n(city, 40, 440, 120, 480)          # 历史区那条
            + _n("热门城市", 40, 620, 160, 650)
            + _n(city, 60, 680, 140, 720)          # 有效的那条
            + _n("北京", 180, 680, 260, 720)
            + '</hierarchy>')


def test_skips_history_row_and_returns_hot_city():
    row = _pick_city_row(_city_page(), "上海")
    assert row is not None
    assert row["y1"] >= 680, "取到了历史选择区那条：%s" % row


def test_returns_none_when_city_only_in_history():
    xml = ('<hierarchy>'
           + _n("历史选择", 40, 400, 140, 425)
           + _n("东京", 40, 440, 120, 480)
           + _n("热门城市", 40, 620, 160, 650)
           + _n("上海", 60, 680, 140, 720)
           + '</hierarchy>')
    assert _pick_city_row(xml, "东京") is None, \
        "只有历史区有时不该返回可点行（应走搜索框）"


def test_works_without_hot_city_section():
    """没渲染「热门城市」时至少要避开历史区。"""
    xml = ('<hierarchy>'
           + _n("历史选择", 40, 400, 140, 425)
           + _n("上海", 40, 440, 120, 480)
           + '</hierarchy>')
    assert _pick_city_row(xml, "上海") is None


def test_set_city_verifies_leaving_city_page():
    """选中后必须确认离开了城市页；停在原页不许返回 True。"""
    import inspect
    from crawlers.app_qunar import AppQunarCrawler
    src = inspect.getsource(AppQunarCrawler._set_city)
    assert "_CITY_PAGE_MARK" in src, \
        "没有校验是否离开城市页：点了历史区也会返回 True"


# ---- merged from tests/test_r694_qunar_low_fare.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _n(text, x1, y1, x2, y2):
    return ('<node text="%s" resource-id="" class="android.widget.TextView"'
            ' bounds="[%d,%d][%d,%d]" />' % (text, x1, y1, x2, y2))


def _page():
    """真机结构缩影：日期带 + 一天航班卡片（后者不得被当低价）。"""
    return ('<hierarchy>'
            + _n("北京", 734, 55, 782, 84)
            + _n("上海", 824, 55, 872, 84)
            + _n("10.31", 7, 112, 60, 133)
            + _n("11.01", 273, 112, 326, 133)
            + _n("11.02", 539, 112, 592, 133)
            + _n("11.03", 805, 112, 858, 133)
            + _n("今天", 22, 133, 62, 154)
            + _n("明天", 287, 133, 327, 154)
            + _n("后天", 554, 133, 594, 154)
            + _n("周二", 820, 133, 860, 154)
            + _n("¥410", 7, 156, 67, 182)
            + _n("¥358", 273, 156, 333, 182)
            + _n("¥420", 539, 156, 599, 182)
            + _n("¥410", 805, 156, 865, 182)
            # 下方是当天的航班明细卡片，票价 358 与上面 11.01 相同
            + _n("直飞低价", 24, 322, 120, 343)
            + _n("07:30", 36, 363, 200, 399)
            + _n("09:45", 270, 363, 420, 399)
            + _n("¥", 1490, 359, 1501, 385)
            + _n("358", 1502, 356, 1560, 400)
            + _n("东航MU5186", 57, 437, 200, 462)
            + '</hierarchy>')


def test_strip_parses_daily_min_price():
    rows = parse_low_fare_strip(_page(), "2026")
    got = [(r["date"], r["price"]) for r in rows]
    assert got == [("2026-10-31", 410), ("2026-11-01", 358),
                   ("2026-11-02", 420), ("2026-11-03", 410)], got


def test_strip_ignores_flight_card_prices():
    """下方卡片的 `¥358` 不得被当成 11.01 之外的另一天。"""
    rows = parse_low_fare_strip(_page(), "2026")
    assert len(rows) == 4, rows
    assert all(r["price"] in (410, 358, 420) for r in rows)


def test_strip_carries_weekday():
    rows = {r["date"]: r for r in parse_low_fare_strip(_page(), "2026")}
    assert rows["2026-10-31"]["weekday"] == "今天"
    assert rows["2026-11-01"]["weekday"] == "明天"


def test_missing_price_is_none_not_zero():
    xml = ('<hierarchy>'
           + _n("10.31", 7, 112, 60, 133)
           + _n("11.01", 273, 112, 326, 133)
           + _n("11.02", 539, 112, 592, 133)
           + _n("今天", 22, 133, 62, 154)
           + _n("¥410", 273, 156, 333, 182))
    rows = {r["mm_dd"]: r for r in parse_low_fare_strip(xml, "2026")}
    assert rows["10-31"]["price"] is None
    assert rows["11-02"]["price"] is None
    assert rows["11-01"]["price"] == 410


def test_home_strip_with_chajia_is_not_low_fare_page():
    """首页 7 天条每天下面是「查价」，不是价格——不能当结果页。"""
    xml = ('<hierarchy>'
           + _n("10.31", 7, 112, 60, 133)
           + _n("11.01", 273, 112, 326, 133)
           + _n("11.02", 539, 112, 592, 133)
           + _n("查价", 7, 156, 67, 182)
           + _n("查价", 273, 156, 333, 182)
           + _n("查价", 539, 156, 599, 182)
           + '</hierarchy>')
    assert not is_low_fare_page(xml)


def test_low_fare_prunes_to_window():
    """日期带会渲染跨年远期日；14 天窗口之外的必须裁掉。"""
    import datetime as dt
    from crawlers.app_qunar import AppQunarCrawler
    today = dt.date.today()
    rows = [{"date": today.isoformat(), "price": 1},
            {"date": (today + dt.timedelta(days=13)).isoformat(), "price": 2},
            {"date": (today + dt.timedelta(days=14)).isoformat(), "price": 3},
            {"date": (today - dt.timedelta(days=1)).isoformat(), "price": 4}]
    out = AppQunarCrawler._pick_window(rows, 14)
    assert [r["price"] for r in out] == [1, 2], out


def test_low_fare_resets_to_home_after_collect():
    """采完低价必须回首页，否则同进程紧接着查明细会整轮失败。

    真机（2026-10-30）：先 low_fare 再 safe_fetch，明细两次都是
    `pick-date-failed` / `set-city-dep`——低价页与首页是两条导航栈，
    `_ensure_home` 的深链在低价页上会被 RN 吞掉。
    """
    import inspect
    from crawlers.app_qunar import AppQunarCrawler
    src = inspect.getsource(AppQunarCrawler._low_fare_locked)
    assert "_back_to_home" in src, "低价采完没有复位到首页"


def test_pick_date_rebuilds_home_when_date_row_missing():
    """首页停在「搜索位」时日期行不在视图树，必须重建而不是盲滑。

    真机：下拉手势会误触首页活动位、打开 HyWebActivity（活动 H5），
    比原来更糟。所以判据是「找不到日期行 → force-stop 重建」。
    """
    import inspect
    from crawlers.app_qunar import AppQunarCrawler
    src = inspect.getsource(AppQunarCrawler._pick_date)
    assert "_back_to_home" in src, "日期行缺失时没有重建首页"
    # 日历**网格内部**的滚动是必要的（跨月要翻）；禁止的是在首页盲滑
    # 找日期行——那会误触活动位。判据：swipe 只能出现在「选择日期」之后。
    head = src.split("在月份网格里定位")[0]
    assert "swipe" not in head, "日期行缺失时仍在首页盲滑"


def test_h5_webview_activity_is_detected():
    """r805cj：搜索后落到 H5 WebView ≠ 原生日期带（dump 里没有文本）。"""
    from crawlers.app_qunar_lowfare import is_h5_low_fare_activity
    assert is_h5_low_fare_activity(
        "com.Qunar/com.mqunar.hy.browser.activity.HyWebActivity01") is True
    assert is_h5_low_fare_activity(
        "com.Qunar/com.mqunar.atom.flight.modules.home.TabHomeActivity"
    ) is False


def test_h5_low_fare_maps_to_not_connected(monkeypatch):
    """通路接不上（H5）记 not_connected；真 timeout 仍是 error。

    负控很重要：把所有空结果都改成 not_connected 会把「被拦/超时」
    洗成「渠道没接」，读者就不去查风控了。
    """
    import datetime as dt
    import logging

    import crawlers.app_qunar as aq
    from core.special_radar import RadarQuery, _app_qunar_deals

    # **相对日期**：`_app_qunar_deals` 在「请求区间已过去」时会提前返回
    # `empty`，写死过去的日期会让本用例跨过午夜后必然失败
    # （2026-11-06 实际踩到：期望 not_connected，实得 empty）。
    _t0 = dt.date.today()
    q = RadarQuery("", "BJS", "北京", "SHA", "上海",
                   _t0, _t0 + dt.timedelta(days=2),
                   ["app_qunar"])

    def _fake(status):
        class Fake:
            def __init__(self, cfg, logger):
                self.paths = [{"path": "low-fare", "status": status,
                               "detail": "低价机票结果页是 H5 WebView"}]
            def low_fare(self, *a, **k):
                return []
        monkeypatch.setattr(aq, "AppQunarCrawler", Fake)
        return _app_qunar_deals(q, logging.getLogger("t"))

    rows, st = _fake("unsupported")
    assert rows == [] and st["status"] == "not_connected", st
    rows, st = _fake("timeout")
    assert rows == [] and st["status"] == "error", st


# ---- merged from tests/test_r702_qunar_single_trip_reset.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class _FakeDev:
    def __init__(self, pages):
        self.pages = list(pages)
        self.taps = []
        self.dumps = 0

    def tap(self, x, y):
        self.taps.append((x, y))
        return True

    def dump(self):
        self.dumps += 1
        i = min(self.dumps, len(self.pages) - 1)
        return self.pages[i]


def _home(round_trip):
    xml = ('<hierarchy>'
           '<node text="单程" resource-id="com.Qunar:id/atom_flight_single_rb"'
           ' class="android.widget.RadioButton" bounds="[51,418][550,460]" />'
           '<node text="往返" resource-id="com.Qunar:id/atom_flight_round_rb"'
           ' class="android.widget.RadioButton" bounds="[550,418][1049,460]" />'
           '<node text="" resource-id="com.Qunar:id/atom_flight_ll_dep_date"'
           ' class="android.widget.LinearLayout" bounds="[48,564][205,609]" />')
    if round_trip:
        xml += ('<node text="" resource-id="com.Qunar:id/atom_flight_ll_back_date"'
                ' class="android.widget.LinearLayout"'
                ' bounds="[1343,564][1552,609]" />')
    return xml + '</hierarchy>'


class _Crawler(q.AppQunarCrawler):
    def __init__(self):
        super().__init__({}, None)


def test_round_trip_home_is_switched_to_single():
    dev = _FakeDev([_home(True), _home(False)])
    xml = _Crawler()._switch_to_single(dev, _home(True))
    assert dev.taps, "停在往返档却没点「单程」"
    # 点的是单程 RadioButton 的中心 (300, 439)，不是往返那颗 (799, 439)
    assert dev.taps[0] == (300, 439)
    assert q._ID_BACK_DATE_LL not in xml


def test_single_home_resets_mode_idempotently():
    """首页看着是单程也要点一次「单程」——App 内部可能记着多程。

    2026-11-04 实测：首页有城市位、无「第一程」，看起来完全是单程；点搜索
    却直接进「多程航班」结果页（App 把上次搜索记成了多程的第一段）。
    点一次「单程」tab 就能把内部模式重置回来，且对真单程无副作用。
    """
    c = _Crawler()
    dev = _FakeDev([_home(False)])
    xml = c._switch_to_single(dev, _home(False))
    assert dev.taps == [(300, 439)], "没有幂等重置「单程」档"
    assert xml == _home(False)


def test_page_without_single_control_is_left_alone():
    """没有「单程」控件（结果页/弹层）时不能瞎点。"""
    c = _Crawler()
    page = ('<hierarchy><node text="选择航班" bounds="[0,0][900,60]" />'
            '</hierarchy>')
    dev = _FakeDev([page])
    xml = c._switch_to_single(dev, page)
    assert dev.taps == [], "没有单程控件却点了屏幕"
    assert xml == page


def test_single_fetch_switches_before_picking_dates():
    """单程入口本身要调复位——只测 `_switch_to_single` 会漏掉这里。"""
    import inspect
    src = inspect.getsource(q.AppQunarCrawler._fetch_locked)
    assert "_switch_to_single" in src, \
        "单程流程没复位档位：往返档下会 pick-date-failed 或把往返价当单程价"


def test_back_date_marker_is_distinct_from_dep_date():
    # 判据必须是「返程位」，不能是泛化的日期位 id：单程档也有 dep_date
    assert q._ID_BACK_DATE_LL != q._ID_DEP_DATE_LL
    assert q._ID_BACK_DATE_LL.endswith("back_date")


# ---- merged from tests/test_r939_qunar_multi_city.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_SCENE = os.path.join(ROOT, "tests", "fixtures",
                      "qunar_multi_city_scene.txt")


def _crawler():
    return AppQunarCrawler({"user_data_dir": "user_data"}, None)


class Dev:
    def __init__(self, frames):
        self.frames = list(frames)
        self.i = 0
        self.taps = []
        self.backs = 0

    def dump(self):
        f = self.frames[min(self.i, len(self.frames) - 1)]
        self.i += 1
        return f

    def tap(self, x, y):
        self.taps.append((x, y))
        return True

    def keyevent(self, code):
        self.backs += 1
        return True


MULTI = ('<node text="选择航班" bounds="[0,0][100,40]" />'
         '<node text="抱歉未找到符合条件的多程航班" bounds="[0,60][900,90]" />'
         '<node text="第一程" bounds="[0,100][60,130]" />'
         '<node text="第二程" bounds="[0,200][60,230]" />')
MULTI_WITH_TAB = (MULTI +
                  '<node text="单程" bounds="[10,300][60,340]" />')
SINGLE = ('<node text="机票查询" bounds="[0,0][100,40]" />'
          '<node text="11月16日" bounds="[10,100][90,130]" />')
ROUND = (f'<node resource-id="{_ID_BACK_DATE_LL}" '
         'bounds="[0,200][100,240]" />'
         '<node text="单程" bounds="[10,300][60,340]" />')


# ---------------------------------------------------------------------------
# 1. 核心：多程必须被识别成"需要切档"
# ---------------------------------------------------------------------------
def test_multi_city_triggers_switch():
    c = _crawler()
    d = Dev([MULTI_WITH_TAB])
    out = c._switch_to_single(d, MULTI_WITH_TAB)
    assert d.taps, "多程档没有点「单程」——这就是 no-list-page 的根因"
    assert out is not None


def test_single_mode_does_not_tap():
    """已是单程：不白点。"""
    c = _crawler()
    d = Dev([SINGLE])
    c._switch_to_single(d, SINGLE)
    assert d.taps == []


def test_round_trip_still_switches():
    """往返档的既有行为不能回归。"""
    c = _crawler()
    d = Dev([ROUND])
    c._switch_to_single(d, ROUND)
    assert d.taps, "往返档不再切单程了"


# ---------------------------------------------------------------------------
# 2. 多程结果页（无档位控件）：先 BACK 退回表单
# ---------------------------------------------------------------------------
def test_multi_result_page_backs_out_then_switches():
    """多程**结果页**（无档位控件）：先 BACK 退回表单，再点「单程」。

    入参是结果页 MULTI（没有「单程」控件），BACK 之后 dump 给带
    「单程」的表单页 —— 所以帧序列只需一帧 MULTI_WITH_TAB。
    """
    c = _crawler()
    d = Dev([MULTI_WITH_TAB])
    c._switch_to_single(d, MULTI)
    assert d.backs >= 1, "多程结果页没有先 BACK 退回表单"
    assert d.taps, "BACK 回表单后没有点「单程」"


# ---------------------------------------------------------------------------
# 3. 真实现场：旧判据漏判、新判据命中
# ---------------------------------------------------------------------------
def test_real_scene_is_multi_city():
    """这份 dump 是病根本身：它不是往返（无返程日期位），是多程。"""
    if not os.path.isfile(_SCENE):
        raise AssertionError("真实现场快照缺失：%s" % _SCENE)
    s = io.open(_SCENE, encoding="utf-8", errors="replace").read()
    assert _ID_BACK_DATE_LL not in s, "现场有返程日期位，那就不是多程问题"
    assert "第一程" in s and "第二程" in s, "现场不是多程页，判据假设失效"
    assert "多程" in s


# ---------------------------------------------------------------------------
# 4. 源码钉：判据必须同时覆盖两种档位残留
# ---------------------------------------------------------------------------
def test_source_covers_both_residues():
    src = io.open(os.path.join(ROOT, "crawlers", "app_qunar.py"),
                  encoding="utf-8").read()
    i = src.find("def _switch_to_single")
    assert i > 0
    body = src[i:i + 2600]
    assert "_ID_BACK_DATE_LL in" in body, "往返判据不见了"
    assert "第一程" in body and "第二程" in body, "没有覆盖多程档"


def test_multi_layer_back_is_supported():
    """多程结果页到表单**可能不止一层**，必须循环退（最多 3 层）。

    现场只见过「结果页」这一层，但退栈路径不保证永远一层：
    结果页 → 查询中间页 → 表单 也是可能的。只 BACK 一次就把
    "退不干净"变成了新的 `no-list-page` 来源。
    """
    c = _crawler()
    # 前两次 BACK 后仍是结果页，第 3 次才回到带「单程」的表单
    d = Dev([MULTI, MULTI, MULTI_WITH_TAB, MULTI_WITH_TAB])
    c._switch_to_single(d, MULTI)
    assert d.backs >= 1, "没有退栈"
    assert d.taps, "退栈后没找到「单程」并点击"


def test_back_is_bounded():
    """退栈次数有上限，不能无限按 BACK。"""
    c = _crawler()
    d = Dev([MULTI])          # 永远是结果页，退不出去
    c._switch_to_single(d, MULTI)
    assert d.backs <= 3, "退栈没有上限：%d 次" % d.backs


# ---------------------------------------------------------------------------
# 6. 多程**结果页**：没有「单程」控件、BACK 也退不出 → 必须重建
# ---------------------------------------------------------------------------
def test_multi_result_page_without_switch_control_is_detected():
    """现场 `nolist-2026-11-16` 第二次：只有「多程」字样、**没有**「单程」。

    说明只认「第一程+第二程」不够——多程**结果页**可能只带「多程」文案。
    判据必须放宽到"出现「多程」即需处理"。
    """
    src = io.open(os.path.join(ROOT, "crawlers", "app_qunar.py"),
                  encoding="utf-8").read()
    i = src.find("def _switch_to_single")
    body = src[i:i + 3200]
    # 必须覆盖多程结果页（用长文案，而不是 tab 上的「多程」二字——
    # 首页本来就有那个 tab，用它当判据会把正常页面判成多程，实测踩过）
    assert '"多程航班" in low' in body, "多程结果页判据缺失"
    assert '"分开预订" in low' in body, "多程结果页文案判据缺失"


def test_force_stop_fallback_exists():
    """切档与 BACK 都失败时，必须有 force-stop + 深链重建的兜底。

    多程结果页不在正常导航栈里，BACK 退不回表单——只能硬重建。
    没有这一步，整轮就在多程页上跑，记 `no-list-page`。
    """
    src = io.open(os.path.join(ROOT, "crawlers", "app_qunar.py"),
                  encoding="utf-8").read()
    assert "force-stop 重建后重试单程" in src, "没有重建兜底"
    assert "多程档残留：切单程与重建均未成功" in src, \
        "重建也失败时没有如实记账"


def test_real_scene_second_occurrence_has_no_single_control():
    """第二份现场确认：多程结果页确实没有「单程」可点。"""
    p = os.path.join(ROOT, "tests", "fixtures",
                     "qunar_multi_city_scene_2.txt")
    assert os.path.isfile(p), "第二份现场快照缺失：%s" % p
    s = io.open(p, encoding="utf-8", errors="replace").read()
    assert "多程" in s, "第二份现场不是多程页，判据假设失效"
    assert "单程" not in s, "现场有「单程」控件，那就不该走重建兜底"
    assert "抱歉未找到" in s or "第一程" in s


# ---------------------------------------------------------------------------
# 7. **正常首页不许被误判成多程**（本轮修的 bug）
# ---------------------------------------------------------------------------
def test_normal_home_with_multi_tab_is_not_multi_city():
    """首页本来就有「多程」tab —— 不能用 `"多程" in xml` 当判据。

    2026-11-04 我第一版就是这么写的：
    ```python
    is_multi = (("第一程" in low and "第二程" in low) or "多程" in low)
    ```
    实测在一个 **175 节点的正常页面**上 `"多程" in xml` 就是 True ——
    于是每轮都会判成多程、白做一次 force-stop 重建。
    """
    c = _crawler()
    home = ('<node text="机票查询" bounds="[0,0][100,40]" />'
            '<node text="单程" bounds="[10,50][60,90]" />'
            '<node text="往返" bounds="[70,50][120,90]" />'
            '<node text="多程" bounds="[130,50][180,90]" />'      # ← tab 文案
            '<node text="11月16日" bounds="[10,100][90,130]" />')
    d = Dev([home])
    c._switch_to_single(d, home)
    # **允许点一次「单程」**（2026-11-04 实测定论：App 会把上次搜索记成多程，
    # 即使首页看起来是单程；幂等点一次单程能把内部模式重置回来）。
    # 这里守住的不变量是：**不许误触发退栈/重建**（那才是代价大的动作）。
    assert d.backs == 0, "正常首页被误判并触发了退栈"
    assert len(d.taps) <= 1, "正常首页点了不止一次（会拖慢每轮）"


def test_multi_result_page_still_detected_by_long_text():
    """真正的多程结果页用长文案判，仍然命中。"""
    result = ('<node text="选择航班" bounds="[0,0][100,40]" />'
              '<node text="抱歉未找到符合条件的多程航班" '
              'bounds="[0,60][900,90]" />'
              '<node text="建议修改搜索条件或分开预订" '
              'bounds="[0,100][900,130]" />')
    assert "多程航班" in result or "分开预订" in result


def test_precise_criteria_in_source():
    """源码里不许再出现宽判据 `"多程" in low`。"""
    src = io.open(os.path.join(ROOT, "crawlers", "app_qunar.py"),
                  encoding="utf-8").read()
    assert 'or "多程" in low' not in src, "宽判据回来了（会误伤正常首页）"
    assert 'or "多程" in (xml or "")' not in src, "宽判据回来了"


# ---------------------------------------------------------------------------
# 8. 点搜索前必须确认「现在是单程表单」（本轮新增）
# ---------------------------------------------------------------------------
def test_pre_search_asserts_single_mode():
    """不确认就点搜索 → 得到多程结果页 → 记 `no-list-page`（看不出真因）。

    实测 34 次 `no-list-page` 全是这个。现在提前判一次，把原因写成
    `multi-city-form` / `点搜索前发现停在多程档`，账本上直接看得见。
    """
    src = io.open(os.path.join(ROOT, "crawlers", "app_qunar.py"),
                  encoding="utf-8").read()
    i = src.find("def _search_and_parse")
    assert i > 0
    j = src.find("def _to_prices", i)
    body = src[i:j]
    assert "multi-city-form" in body, "点搜索前没有档位断言"
    assert "点搜索前发现停在多程档" in body, "没有把原因写进账本"
    # 断言必须在**点搜索之前**
    assert body.find("multi-city-form") < body.find("tap(*_center(btn))"), \
        "档位断言跑到点搜索之后了（那已经晚了）"


def test_multi_city_form_reason_is_distinct_from_no_list_page():
    """`multi-city-form` 必须与 `no-list-page` 区分开。

    两者在账本上含义完全不同：
    * `multi-city-form` = 我方没切档（可修）
    * `no-list-page`    = 点了搜索但列表没出来（可能真没数据）
    混成一个，下一轮又得猜。
    """
    src = io.open(os.path.join(ROOT, "crawlers", "app_qunar.py"),
                  encoding="utf-8").read()
    assert '"multi-city-form"' in src
    assert '"no-list-page"' in src
    assert src.count("multi-city-form") >= 1


# ---------------------------------------------------------------------------
# 9. 搜索前必须留痕：把"点之前是什么状态"记一行（本轮新增）
# ---------------------------------------------------------------------------
def test_pre_search_state_is_logged():
    """`_one_date` 在调 `_search_and_parse` 之前要记一行页面状态。

    2026-11-04：`no-list-page` 只能看到最终结果，**看不出按下搜索时表单
    是哪个档**——同一句账错了 34 次。留一行"命中了哪些标记"，
    就不用每次翻 8KB dump。
    """
    src = io.open(os.path.join(ROOT, "crawlers", "app_qunar.py"),
                  encoding="utf-8").read()
    i = src.find("def _one_date")
    assert i > 0
    j = src.find("def _ensure_home", i)
    body = src[i:j]
    assert "搜索前页面" in body, "搜索前没有留痕"
    # 留痕必须在调用 _search_and_parse **之前**
    assert body.find("搜索前页面") < body.find("return self._search_and_parse"), \
        "留痕跑到搜索之后了（那已经看不出点之前的状态）"
    # 要能区分这几个关键状态
    for mk in ("单程日期", "返程日期", "城市位", "多程段", "多程结果"):
        assert mk in body, "留痕缺少标记：%s" % mk


# ---------------------------------------------------------------------------
# 10. 幂等重置必须**紧贴点搜索**（本轮加固）
# ---------------------------------------------------------------------------
def test_reset_happens_right_before_search_tap():
    """重置「单程」必须放在 `_search_and_parse` 里、点搜索之前。

    放在 `_fetch_locked` 开头是不够的：中间隔着 `_set_city` / `_pick_date`
    两次页面跳转，任何一次都可能把 App 的搜索模式又写回多程。
    实测就是这么错的——首页重置过了，点搜索照样进多程结果页。
    """
    src = io.open(os.path.join(ROOT, "crawlers", "app_qunar.py"),
                  encoding="utf-8").read()
    i = src.find("def _search_and_parse")
    j = src.find("def _to_prices", i)
    body = src[i:j]
    assert "幂等重置" in body, "点搜索前没有做幂等重置"
    # 重置必须在 `_search_widget`（找搜索按钮）之前
    assert body.find("幂等重置") < body.find("_search_widget"), \
        "重置跑到找搜索按钮之后了（太晚）"
    # 重置后要重新取页面（否则还拿旧帧找按钮）
    assert "xml = self._scroll_home(dev, want=\"search\")" in body


def test_multi_city_reason_says_already_reset():
    """重置过仍失败时，reason 要写明「已重置」——区分"没试"和"试了不行"。"""
    src = io.open(os.path.join(ROOT, "crawlers", "app_qunar.py"),
                  encoding="utf-8").read()
    assert "已重置仍未切回" in src


# ---------------------------------------------------------------------------
# 11. 切单程**可能清空城市位** —— 必须核对，不能静默搜空航线（本轮新增）
# ---------------------------------------------------------------------------
def test_city_cleared_by_reset_is_caught():
    """点「单程」有可能把已设好的城市清空（2026-11-04 安全检查）。

    如果清了还照常搜索，搜的是**空航线**，结果会被记成"该日无航班"
    （`empty`）——**把解析问题伪装成业务结论**，比缺数据更糟。
    所以切档前后要核对城市位，被清空就用独立 reason 报出来。
    """
    src = io.open(os.path.join(ROOT, "crawlers", "app_qunar.py"),
                  encoding="utf-8").read()
    i = src.find("def _search_and_parse")
    j = src.find("def _to_prices", i)
    body = src[i:j]
    assert "city-cleared-by-reset" in body, "没有保护：切档清空城市后会继续搜"
    assert "_dep_before" in body and "_dep_after" in body, "没有前后核对"
    assert "切单程后城市位被清空" in body, "没有把原因写进账本"
    # 保护必须在点搜索之前
    assert body.find("city-cleared-by-reset") < body.find("_search_widget"), \
        "保护跑到点搜索之后了（那已经搜错了）"


def test_city_cleared_reason_is_distinct():
    """`city-cleared-by-reset` 与 `multi-city-form` / `no-list-page` 三者互斥。"""
    src = io.open(os.path.join(ROOT, "crawlers", "app_qunar.py"),
                  encoding="utf-8").read()
    for r in ("city-cleared-by-reset", "multi-city-form", "no-list-page"):
        assert r in src, "缺少 reason：%s" % r
