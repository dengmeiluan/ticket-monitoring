# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1042_fliggy_calendar_prices.py
- tests/test_r1043_fliggy_blocked_reason.py
- tests/test_r1044_fliggy_mode_tab.py
- tests/test_r1052_fliggy_rt_verify.py
- tests/test_r1055_fliggy_rt_result.py
- tests/test_r736_fliggy_round_trip_honesty.py
- tests/test_r794_fliggy_h5_form_and_risk.py
- tests/test_r805n_fliggy_intl_round_trip.py
- tests/test_v1587_fliggy_bizprice.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import io
import json
import logging
import os
import pytest
import sys
import yaml

from crawlers.app_fliggy import AppFliggyCrawler, _mode_tap_xy, round_trip_footer_matches
from crawlers.app_fliggy_parse import parse_calendar_prices, parse_round_trip_result
from crawlers.fliggy import FliggyCrawler
from datetime import date


# ---- merged from tests/test_r1042_fliggy_calendar_prices.py ----

_MONTHS = [(2026, 11, 697.0), (2026, 12, 1830.0)]
_COLS = (83, 255, 426, 598, 769, 940, 1112)
_TODAY = date(2026, 11, 5)


def _tok(t, x, y, w=40, h=40):
    return {"t": t, "x": x, "y": y, "w": w, "h": h}


def _day_row(days, y=1458, cols=_COLS):
    out = []
    for d, x in zip(days, cols):
        out.append(_tok(str(d), x, y))
    return out


def test_reads_price_under_day():
    words = _day_row((22, 23, 24, 25, 26, 27, 28))
    words += [_tok("820", 98, 1528, 60, 30),     # 22 下方
              _tok("950", 955, 1528, 60, 30)]    # 27 下方
    rows = parse_calendar_prices(words, _MONTHS, today=_TODAY)
    got = {r["date"]: r["price"] for r in rows}
    assert got == {"2026-11-22": 820.0, "2026-11-27": 950.0}


def test_view_text_means_no_price():
    """「查看」不是价格；该日不进结果（不能编造 0 元）。"""
    words = _day_row((22, 23, 24, 25, 26, 27, 28))
    words += [_tok("查看", 426, 1528, 60, 30)]
    rows = parse_calendar_prices(words, _MONTHS, today=_TODAY)
    assert rows == []


def test_price_far_below_is_not_matched():
    """价格必须在日号下方 25..130px；太远的是下一行的价，不能张冠李戴。"""
    words = _day_row((22, 23, 24, 25, 26, 27, 28))
    words += [_tok("820", 98, 1458 + 300, 60, 30)]
    rows = parse_calendar_prices(words, _MONTHS, today=_TODAY)
    assert rows == []


def test_past_days_are_skipped():
    words = _day_row((1, 2, 3, 4, 5, 6, 7))
    words += [_tok("700", 83, 1528, 60, 30)]
    rows = parse_calendar_prices(words, _MONTHS, today=_TODAY)
    assert rows == []


def test_nearest_price_below_wins_in_one_cell():
    """同一格内取**最靠近日号**的那个价格（不是最低价）。

    真实日历每格只有一个价；出现两个数字时（如价格 + 折扣角标），
    离日号最近的那个才是当日最低价。
    """
    words = _day_row((22, 23, 24, 25, 26, 27, 28))
    words += [_tok("820", 98, 1528, 60, 30),
              _tok("790", 96, 1600, 60, 30)]
    rows = parse_calendar_prices(words, _MONTHS, today=_TODAY)
    assert [r["price"] for r in rows] == [820.0]


def test_duplicate_date_across_screens_takes_lowest():
    """同一日期在两屏里都读到（滚动重叠），取更低的价格。"""
    words = _day_row((22, 23, 24, 25, 26, 27, 28))
    words += [_tok("820", 98, 1528, 60, 30)]
    # 同一屏里 22 号又被读到一次（把它放在 11 月区间内的另一行）
    words += _day_row((22, 23, 24, 25, 26, 27, 28), y=1250)
    words += [_tok("790", 98, 1320, 60, 30)]
    rows = parse_calendar_prices(words, _MONTHS, today=_TODAY)
    assert [r["price"] for r in rows] == [790.0]


def test_second_month_band_is_used():
    """第二个月（12 月）的日号必须归到 12 月，不能记成 11 月。"""
    words = _day_row((1, 2, 3, 4, 5, 6, 7), y=2390)
    words += [_tok("680", 83, 2460, 60, 30)]
    rows = parse_calendar_prices(words, _MONTHS, today=_TODAY)
    assert [r["date"] for r in rows] == ["2026-12-01"]


def test_no_months_returns_empty():
    words = _day_row((22, 23, 24, 25, 26, 27, 28))
    assert parse_calendar_prices(words, []) == []


def test_row_needs_at_least_four_days():
    """少于 4 个日号的一行不算日号行（价格行/零碎数字会被排除）。"""
    words = [_tok("8", 83, 1458), _tok("9", 255, 1458)]
    words += [_tok("820", 98, 1528, 60, 30)]
    assert parse_calendar_prices(words, _MONTHS, today=_TODAY) == []


def test_last_row_with_two_days_keeps_its_price():
    """月份最后一行常常只有 1–2 天（11 月 29/30），它的价格不能丢。

    这类日期往往就是月底/节假日的高价位，丢了会让日历价系统性偏低。
    「向下补一行」的规则专门处理这个。
    """
    words = _day_row((22, 23, 24, 25, 26, 27, 28))
    words += [_tok("29", 83, 1660), _tok("30", 255, 1660)]
    words += [_tok("740", 98, 1730, 60, 30)]
    rows = parse_calendar_prices(words, _MONTHS, today=_TODAY)
    got = {r["date"]: r["price"] for r in rows}
    assert got.get("2026-11-29") == 740.0


# ---- merged from tests/test_r1043_fliggy_blocked_reason.py ----

class _FakeDev:
    def __init__(self, act="", words=None):
        self._act = act
        self._words = words or []

    def current_activity(self):
        return self._act

    def dump(self):
        return ""


def _crawler(tmp_path=None):
    cfg = {"user_data_dir": "user_data", "android": {}}
    c = AppFliggyCrawler(cfg, logging.getLogger("test"))
    return c


def _with_ocr(monkeypatch, words):
    c = _crawler()
    monkeypatch.setattr(c, "_ocr", lambda dev: words)
    return c


def test_security_container_is_blocked(monkeypatch):
    c = _with_ocr(monkeypatch, [])
    dev = _FakeDev(act="com.taobao.trip/com.alibaba.wireless.security.open."
                       "middletier.fc.ui.ContainerActivity")
    r = c._blocked_reason(dev)
    assert "安全容器" in r


def test_access_denied_text_is_blocked(monkeypatch):
    c = _with_ocr(monkeypatch, [{"t": "访问被拒绝"}, {"t": "请稍后再试"}])
    r = c._blocked_reason(_FakeDev(act="com.taobao.trip/.home.HomeActivity"))
    assert "访问被拒绝" in r


def test_plain_home_is_not_blocked(monkeypatch):
    c = _with_ocr(monkeypatch, [{"t": "机票"}, {"t": "酒店"}])
    r = c._blocked_reason(_FakeDev(act="com.taobao.trip/.home.HomeActivity"))
    assert r == ""


def test_ocr_failure_degrades_to_not_blocked(monkeypatch):
    """OCR 挂了不能误判成风控——否则会把"读不到字"记成"被拦"。"""
    c = _crawler()

    def _boom(dev):
        raise RuntimeError("ocr down")

    monkeypatch.setattr(c, "_ocr", _boom)
    assert c._blocked_reason(_FakeDev(act="com.taobao.trip/.home.HomeActivity")) == ""


# ---- merged from tests/test_r1044_fliggy_mode_tab.py ----

def _w(t, x, y=576, ww=44, hh=44):
    return {"t": t, "x": x, "y": y, "w": ww, "h": hh}


_TABS = [_w("单", 189), _w("程", 238),
         _w("往", 581), _w("返", 631),
         _w("多", 976), _w("程", 1024)]


def test_one_way_hits_dan_cheng():
    xy = _mode_tap_xy(_TABS, "单程")
    assert xy is not None
    # x 落在 单..程 两字之间（189..282）
    assert 189 <= xy[0] <= 282


def test_round_trip_hits_wang_fan():
    xy = _mode_tap_xy(_TABS, "往返")
    assert xy is not None
    assert 581 <= xy[0] <= 675


def test_multi_city_hits_duo_cheng():
    xy = _mode_tap_xy(_TABS, "多程")
    assert xy is not None
    assert 976 <= xy[0] <= 1068


def test_y_is_in_tab_row():
    assert _mode_tap_xy(_TABS, "往返")[1] == 598


def test_missing_label_returns_none():
    assert _mode_tap_xy(_TABS, "国际") is None


def test_out_of_band_words_ignored():
    """y 不在 400..800 的同名字不属于档位行（例如正文里的「单程」）。"""
    words = [_w("单", 100, y=1200), _w("程", 150, y=1200)]
    assert _mode_tap_xy(words, "单程") is None


def test_empty_words_returns_none():
    assert _mode_tap_xy([], "单程") is None


# ---- merged from tests/test_r1052_fliggy_rt_verify.py ----

def test_both_match():
    ok, _why = round_trip_footer_matches(
        {"dep": (11, 16), "ret": (11, 19), "total": 1880.0},
        "2026-11-16", "2026-11-19")
    assert ok is True


def test_return_not_selected_is_rejected():
    """只选了去程（返程仍是「未选择」）不能算成功。"""
    ok, why = round_trip_footer_matches(
        {"dep": (11, 16), "ret": None, "total": None},
        "2026-11-16", "2026-11-19")
    assert ok is False
    assert "不符" in why


def test_wrong_return_day_is_rejected():
    """返程被点到了别的日子（差一天）必须拒绝——这正是"点偏一格"。"""
    ok, why = round_trip_footer_matches(
        {"dep": (11, 16), "ret": (11, 20), "total": None},
        "2026-11-16", "2026-11-19")
    assert ok is False
    assert "11-20" in why


def test_wrong_depart_day_is_rejected():
    ok, _why = round_trip_footer_matches(
        {"dep": (12, 14), "ret": (11, 19), "total": None},
        "2026-11-16", "2026-11-19")
    assert ok is False


def test_bad_ymd_format_is_rejected_not_crashing():
    ok, why = round_trip_footer_matches(
        {"dep": (11, 16), "ret": (11, 19)}, "2026/11/16", "2026-11-19")
    assert ok is False
    assert "格式" in why


def test_footer_none_is_rejected():
    ok, _why = round_trip_footer_matches(None, "2026-11-16", "2026-11-19")
    assert ok is False


def test_cross_year_compares_month_day_only():
    """跨年时底栏只写「1月2日」，按 (月, 日) 比较应当通过。"""
    ok, _why = round_trip_footer_matches(
        {"dep": (12, 30), "ret": (1, 2), "total": None},
        "2026-12-30", "2027-01-02")
    assert ok is True


# ---- merged from tests/test_r1055_fliggy_rt_result.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "fliggy_rt_result_words.json")


def _words():
    return json.loads(io.open(FIX, encoding="utf-8").read())


def test_total_comes_from_bottom_bar():
    got = parse_round_trip_result(_words())
    assert got["total"] == 747.0, got


def test_dep_min_is_card_price_not_coupon():
    """去程起价应是卡片区的 ¥682，不能是顶部优惠券的「50」。"""
    got = parse_round_trip_result(_words())
    assert got["dep_min"] == 682.0, got


def test_coupon_number_is_not_treated_as_fare():
    """把卡片区之外的价格全抹掉，起价必须变成 None 而不是退化成 50。"""
    words = [w for w in _words() if not (600 <= float(w.get("y") or 0) <= 2600)]
    got = parse_round_trip_result(words)
    assert got["dep_min"] is None, got


def test_no_label_means_no_total():
    """没有「往返总价」标签时不能拿去程价冒充往返价。"""
    words = [w for w in _words() if str(w.get("t")) != "价"
             and str(w.get("t")) != "总"]
    got = parse_round_trip_result(words)
    assert got["total"] is None, got


def test_empty_words():
    assert parse_round_trip_result([]) == {"total": None, "dep_min": None}


# ---- merged from tests/test_r736_fliggy_round_trip_honesty.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _src():
    return io.open(os.path.join(ROOT, "crawlers", "fliggy.py"),
                   encoding="utf-8").read()


def _fetch_body():
    """取"真正干活的那个函数体"。

    r1063 T151 起 `fetch` 只是薄壳（`_fetch_core` + 周历兜底），
    往返守卫在 `_fetch_core` 里，所以这里优先取 `_fetch_core`。
    """
    src = _src()
    for name in ("    def _fetch_core(self", "    def fetch(self"):
        i = src.find(name)
        if i < 0:
            continue
        j = src.find("\n    def ", i + 10)
        body = src[i:j if j > 0 else len(src)]
        if "国内往返暂不支持" in body or "for date in dates" in body:
            return body
    i = src.index("    def fetch(self")
    j = src.find("\n    def ", i + 10)
    return src[i:j if j > 0 else len(src)]


def test_domestic_round_trip_bails_out_before_the_list_loop():
    """守卫：国内往返必须在进入单程列表循环**之前**就显式退出。

    国内列表页只有单程，继续往下走必然把单程价当往返返回（r736 实测
    ¥497）。所以 fetch 里 ret_date 的判断要出现在 `for date in dates`
    之前，且落 unsupported。
    """
    body = _fetch_body()
    i_guard = body.find("国内往返暂不支持")
    i_loop = body.find("for date in dates")
    assert i_guard > 0, "fetch 里没有国内往返的显式处置"
    assert i_loop > 0, "找不到单程列表循环"
    assert i_guard < i_loop, (
        "国内往返判断出现在单程循环之后——单程价已经先算出来了")
    assert "unsupported" in body[i_guard - 400:i_guard + 200], (
        "国内往返没有落 unsupported")


def test_round_trip_without_return_evidence_is_not_returned():
    """行为：假的「往返」行（无返程证据）不能当结果返回。"""
    import logging
    from crawlers.fliggy import FliggyCrawler

    inst = FliggyCrawler({"user_data_dir": "user_data"},
                         logging.getLogger("t"))

    # 模拟 PC 拿到一条纯单程行（无返程字段）
    def _fake_pc(fc, tc, date, ret_date="", **_):
        return [{"price": 497, "code": "HO1257", "name": "吉祥",
                 "depTime": "08:25", "arrTime": "10:50"}]

    inst._fetch_pc = _fake_pc            # type: ignore
    inst._sleep = lambda *a, **k: None   # 不真睡
    rows = inst.fetch("SHA", "BJS", ["2026-11-20"], ret_date="2026-11-24")
    assert rows == [], (
        "没有返程证据的单程行被当成往返结果返回了：%s"
        % [getattr(r, "price", r) for r in rows])


def test_oneway_still_returns(monkeypatch):
    """负控：不传 ret_date 时照常返回单程（别把单程也拦掉）。"""
    import logging
    from crawlers.fliggy import FliggyCrawler

    inst = FliggyCrawler({"user_data_dir": "user_data"},
                         logging.getLogger("t"))
    inst._fetch_pc = lambda fc, tc, date, ret_date="", **_: [
        {"price": 497, "code": "HO1257", "name": "吉祥",
         "depTime": "08:25", "arrTime": "10:50"}]
    inst._sleep = lambda *a, **k: None
    inst.path_note = lambda *a, **k: None
    rows = inst.fetch("SHA", "BJS", ["2026-11-20"])
    assert len(rows) == 1 and rows[0].price == 497, rows


def test_international_round_trip_still_goes_through_the_calendar():
    """正控：国际往返不被国内那条闸门拦掉（飞猪真往返在国际日历里）。

    国际走 `cheapestCalendar`（tripType=1 + backDate），与国内列表页是两条
    路。这里只钉住「国内闸门不误伤国际」，不假装国际一定出数。
    """
    import logging
    from crawlers.fliggy import FliggyCrawler

    inst = FliggyCrawler({"user_data_dir": "user_data"},
                         logging.getLogger("t"))
    seen = {}

    def _fake_intl(fc, tc, dates, ret_date=""):
        seen["fc"], seen["tc"] = fc, tc
        seen["ret"] = ret_date
        return []

    inst._fetch_intl = _fake_intl        # type: ignore
    inst.fetch("SHA", "NRT", ["2026-11-20"], ret_date="2026-11-24")
    assert seen.get("fc") == "SHA", (
        "国际往返被国内闸门拦掉了，没走到 _fetch_intl：%s" % (seen,))
    assert seen.get("ret") == "2026-11-24", seen


# ---- merged from tests/test_r794_fliggy_h5_form_and_risk.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "crawlers", "fliggy_h5.py"),
           encoding="utf-8").read()


def test_risk_of_flags_mtop_rejection_at_all():
    """r794 的原始样本（H5 当时 0 行的真身）：必须被识别成拒绝，不是正常结果。"""
    from crawlers.fliggy_h5 import risk_of
    p = {"ret": ["FAIL_SYS_USER_VALIDATE",
                 "RGV587_ERROR::SM::哎哟喂,被挤爆啦,请稍后重试"],
         "data": {"url": "https://h5api.m.taobao.com/h5/_____tmd_____/punish"}}
    assert risk_of(p), "mtop 拒绝体被当成正常结果，会退回「解析 0 行」"


def test_risk_of_detects_validate_shell_without_ret():
    """验证壳：ret 为 null，data 只有 url —— 只看 ret 会漏。"""
    from crawlers.fliggy_h5 import risk_of
    p = {"api": "mtop.trip.flight.listingsearch", "ret": None,
         "data": {"url": "https://h5api.m.taobao.com/h5/_____tmd_____/punish"}}
    assert risk_of(p) == "wall:USER_VALIDATE"


def test_risk_of_is_quiet_on_real_results():
    """正控：真的带 items 的结果页不能被判成风控，否则真数据也会被丢。"""
    from crawlers.fliggy_h5 import risk_of
    ok = {"api": "mtop.trip.flight.listingsearch",
          "ret": ["SUCCESS::调用成功"],
          "data": {"success": True, "items": [
              {"itemType": "FLIGHT_DIRECT", "data": [{"priceInfo": {}}]}]}}
    assert risk_of(ok) == ""
    assert risk_of({}) == ""
    assert risk_of(None) == ""


def test_risk_of_separates_rate_limit_from_validate_wall():
    """RGV587 的原文是「被挤爆啦,请稍后重试」——是限流，不是验证墙。

    r795 实测：冷却后单次请求 4 条响应全 SUCCESS 并正常出数。
    把限流记成 blocked 会引导用户去解一个不存在的验证。
    """
    from crawlers.fliggy_h5 import risk_of
    rate = {"ret": ["FAIL_SYS_USER_VALIDATE",
                    "RGV587_ERROR::SM::哎哟喂,被挤爆啦,请稍后重试"]}
    assert risk_of(rate).startswith("rate:"), risk_of(rate)

    wall = {"ret": ["FAIL_SYS_USER_VALIDATE", "请完成验证"]}
    assert risk_of(wall).startswith("wall:"), risk_of(wall)

    shell = {"ret": None,
             "data": {"url": "https://h5api.m.taobao.com/h5/_____tmd_____/punish"}}
    assert risk_of(shell).startswith("wall:"), risk_of(shell)


def test_rate_limit_maps_to_soft_reject_not_blocked():
    """限流必须落 soft_reject（等一会自愈），不能落 blocked（要人去验证）。"""
    assert 'self._last_soft = True' in SRC
    assert '"soft_reject" if getattr(self, "_last_soft", False)' in SRC
    # 只有 wall 分支才置 blocked
    i_kind = SRC.index('kind = risk.split(":", 1)[0]')
    i_soft = SRC.index("self._last_soft = True", i_kind)
    i_block = SRC.index("self._last_blocked = True", i_kind)
    assert i_soft < i_block, "rate 分支必须先于 wall 分支"
    assert SRC[i_soft:i_block].count("return []") == 1, (
        "rate 分支要直接返回，不能落到 wall 的 blocked")


def test_risk_detail_text_is_used_by_ledger():
    """账本 detail 必须分别落到「限流」与「风控验证」两种文案。"""
    assert "H5 限流（mtop %s，冷却后自愈）" in SRC
    assert "H5 风控验证（mtop %s）" in SRC
    # 顺序：限流分支在前，验证分支在后；两者都必须在「解析 0 行」之前
    i_rate = SRC.index('"H5 限流（mtop %s，冷却后自愈）" % marker')
    i_wall = SRC.index('"H5 风控验证（mtop %s）" % marker')
    i_parse = SRC.index('"H5 listingsearch 解析 0 行（响应 %d 条）"')
    assert i_rate < i_wall < i_parse


def test_city_pick_targets_result_row_and_verifies_form():
    """选城市必须以结果行 class 为目标，并以表单读数复核。"""
    from crawlers.fliggy_h5 import FliggyH5Crawler
    js = FliggyH5Crawler._PICK_ROW_JS
    assert "flight-city-picker-search-line-item-name-wrapper" in js
    # 旧判据的三个特征都必须消失
    assert "querySelectorAll('*')" not in js
    assert "所有机场" not in js
    assert "city-picker|city-item|city-list|row" not in js
    # 复核：点完要回到表单读数确认，不能只信 click 的返回值
    body = SRC[SRC.index("def _pick_city"):SRC.index("def _read_form")]
    assert "_read_form(page)" in body
    assert "now[idx] == name" in body


def test_search_is_triggered_on_both_branches():
    """原来只在日期已匹配的分支点搜索；选完城市直接 return 导致零请求。"""
    body = SRC[SRC.index("def _fetch_one"):SRC.index("def fetch(")]
    i_pick = body.index("self._pick_city(page, 1, want_arr)")
    i_trig = body.index("self._trigger_search(page)")
    assert i_pick < i_trig, "点搜索必须在选完城市之后统一执行"
    # 只允许一处调用（两条分支合并成一条），不再分散
    assert body.count("self._trigger_search(page)") == 1


def test_search_click_tolerates_navigation():
    """点搜索会整页导航，evaluate 可能抛上下文销毁——这不是失败。"""
    body = SRC[SRC.index("def _trigger_search"):SRC.index("def _select_date")]
    assert "Execution context was destroyed" in body
    assert "return True" in body


def test_wait_loop_parses_incrementally():
    """首页会自动重放上次搜索：不能因 buffer 非空就退出。"""
    body = SRC[SRC.index("self._trigger_search(page)\n            # 首页会"):
               SRC.index("best = {}")]
    assert "scanned" in body
    assert "while time.time() < deadline:" in body
    assert "not payloads" not in body, "旧循环只要非空就退出，会读到旧航线"


class _CalPage:
    """日历弹层替身：只记录 evaluate 的入参，并按脚本特征返回预设结果。"""

    def __init__(self, shown, moved=True, clicked=True):
        self.shown = shown
        self.moved = moved
        self.clicked = clicked
        self.calls = []

    def evaluate(self, script, arg=None):
        self.calls.append((script, arg))
        if isinstance(arg, dict):
            if "scrollIntoView" in script:
                return self.moved
            if "date-item-container" in script:
                return self.clicked
        if "traffic-show-date" in script and "innerText" in script:
            return self.shown
        return None

    def wait_for_timeout(self, ms):
        pass


def test_select_date_reaches_far_month_and_never_accepts_wrong_month():
    """跨月选日：必须带着目标 `YYYY-MM` 去滚月，并且校验只认目标月份。

    实测（2026-11-01）：日历把所有月份排在同一条纵向列表里（`.month-header-text`
    文案 `YYYY-MM`，2026-11 → 2027-06），原实现只点「当前可见月里等于 day 的
    第一个元素」——目标 2027-01-30 时点到 11 月的 30 日，随后校验月份不符，
    记「日期选择未匹配」，等于 90 天外的日期根本选不了。
    """
    from crawlers.fliggy_h5 import FliggyH5Crawler
    c = FliggyH5Crawler.__new__(FliggyH5Crawler)
    page = _CalPage("1 月 30 日 周六")
    assert c._select_date(page, "2027-01-30") is True
    args = [a for (_s, a) in page.calls if isinstance(a, dict)]
    assert args and all(a.get("ym") == "2027-01" for a in args), args
    assert all(a.get("day") == "30" for a in args), args

    # 负控：表单落在 11 月 30 日（选错月）绝不能算成功
    bad = _CalPage("11 月 30 日 周日")
    assert c._select_date(bad, "2027-01-30") is False

    # 月标题不存在（超出日历覆盖范围）→ 直接失败，不乱点
    miss = _CalPage("1 月 30 日 周六", moved=False)
    assert c._select_date(miss, "2028-01-30") is False


# ---- merged from tests/test_r805n_fliggy_intl_round_trip.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

RT_ROWS = [
    {"leaveDate": "2026-11-27", "backDate": "2026-12-01",
     "price": 1479.0, "tax": 768.0,
     "url": "//sijipiao.fliggy.com/ie/flight_search_result.htm?"
            "depCityCode=SHA&arrCityCode=TYO&tripType=1&"
            "depDate=2026-11-27&arrDate=2026-12-01"},
    {"leaveDate": "2026-11-28", "backDate": "2026-12-02",
     "price": 1509.0, "tax": 768.0, "url": ""},
]


def test_round_trip_row_yields_price_with_return_evidence():
    el = FliggyCrawler._parse_calendar_days(
        RT_ROWS, "2026-11-27", ret_date="2026-12-01",
        city_codes="SHA-TYO")
    assert el is not None, "受理形态的往返行被解析器丢掉了"
    assert el["price"] == 2247.0, el["price"]
    assert el["tax"] == 768.0
    assert el["backDate"] == "2026-12-01"
    assert el["tripType"] == "RT"
    # 深链也要体现往返口径（用户在界面点「查看」时落到往返页）
    assert "arrDate=2026-12-01" in el.get("view", "")
    assert "tripType=1" in el.get("view", "")


@pytest.mark.parametrize("bad_ret,rows,why", [
    ("2026-12-05", RT_ROWS, "回程日不符"),
    ("2026-12-01", [dict(RT_ROWS[0], backDate=None)], "往返行缺 backDate"),
])
def test_single_trip_price_cannot_masquerade_as_round_trip(
        bad_ret, rows, why):
    got = FliggyCrawler._parse_calendar_days(rows, "2026-11-27",
                                             ret_date=bad_ret)
    assert got is None, (
        "%s 时应拒绝该行，否则单程价会冒充往返总价（¥%s）"
        % (why, (got or {}).get("price")))


def test_intl_round_trip_skips_pc_list():
    """ret_date 在场时国际主路径不得先跑 PC 明细列表。

    PC 列表（sijipiao /ie/）只有去程一列；先跑它、拿它的最低价当往返，
    就会把 ¥1078 的单程价写成往返总价。代码里 `if not ret_date:` 是这条
    纪律的唯一闸门——改坏了不会报错，只会静默串味。
    """
    src = io.open(os.path.join(ROOT, "crawlers", "fliggy.py"),
                  encoding="utf-8").read()
    i = src.index("def _fetch_intl(")
    body = src[i:src.index("\n    def _fetch_intl_pc(", i)]
    gate = body.index("if not ret_date:")
    pc_call = body.index("self._fetch_intl_pc(")
    assert gate < pc_call, "PC 列表调用跑到了 ret_date 闸门之前"
    # 日历兜底必须收到 ret_date（否则它按单程拉）
    assert "ret_date)" in body, "日历兜底没把 ret_date 传下去"


# ---- merged from tests/test_v1587_fliggy_bizprice.py ----

def _row(txt):
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-06")
    assert rows, txt
    return rows[0]


_HEAD = "国航CA8564\n中型机 320\n15:15\n21:30\n乌鲁木齐天山国际机场\n虹桥国际机场T2\n"


def test_bizprice_high_first_with_word():
    """高价在前带舱位词：主价取低、高价落 bizPrice、cabin 撤键不变。"""
    r = _row(_HEAD + "¥9900 商务舱\n¥3960\n订票")
    assert r["price"] == 3960.0
    assert r["bizPrice"] == 9900 and isinstance(r["bizPrice"], int)
    assert "cabin" not in r


def test_bizprice_low_first_high_with_word():
    """低价在前、高价行带词：词跟随本行报价，同样落 bizPrice。"""
    r = _row(_HEAD + "¥3960 4.5折\n¥9900 商务舱\n订票")
    assert r["price"] == 3960.0
    assert r["bizPrice"] == 9900
    assert "cabin" not in r


def test_bizprice_no_word_high_not_booked():
    """无词/「全价」满值高价：高档舱归属无佐证，宁缺勿错不落。"""
    r = _row(_HEAD + "¥9900 全价\n¥3960 4.5折\n订票")
    assert r["price"] == 3960.0
    assert "bizPrice" not in r


def test_bizprice_economy_word_not_booked():
    """经济舱词高价：不属高档舱域，不落 bizPrice。"""
    r = _row(_HEAD + "¥9900 经济舱\n¥3960\n订票")
    assert r["price"] == 3960.0
    assert "bizPrice" not in r


def test_bizprice_three_price_rows_converge():
    """第三个价格行：bizPrice 恒为带词高档价中最低（协议=高档舱最低
    参考价，qunar businessClassMinPrice/tuniu ADT 最低 baseFare 同
    语义），不随后续无词行回撤。"""
    r = _row(_HEAD + "¥9900 商务舱\n¥5000\n¥3960\n订票")
    assert r["price"] == 3960.0
    assert r["bizPrice"] == 9900


def test_bizprice_two_worded_rows_take_lowest():
    """两档带词高档行（假想 ¥9900 商务舱＋¥12000 头等舱）：取最低档
    ——取 max 会成「公务￥头等价」舱名数值双误（Soldier M4）。"""
    r = _row(_HEAD + "¥9900 商务舱\n¥12000 头等舱\n¥3960\n订票")
    assert r["price"] == 3960.0
    assert r["bizPrice"] == 9900


def test_bizprice_single_price_row_untouched():
    """单报价行（主价即高档舱价）：bizPrice 不重复记账，cabin 照旧。"""
    r = _row(_HEAD + "¥9900 商务舱\n订票")
    assert r["price"] == 9900.0
    assert r["cabin"] == "商务舱"
    assert "bizPrice" not in r


def test_bizprice_alt_price_still_not_leaked():
    """_alt_price 内部留痕键继续不进 extra（既有卫生语义不回退）。"""
    r = _row(_HEAD + "¥9900 商务舱\n¥3960\n订票")
    assert "_alt_price" not in r
