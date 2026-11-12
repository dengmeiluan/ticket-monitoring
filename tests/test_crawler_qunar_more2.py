# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r398_qunar_evidence_scope.py
- tests/test_r701_qunar_round_trip.py
- tests/test_r931_qunar_yuan_price.py
- tests/test_v15279_qunar.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
import io
from support_webui_src import webui_full_src

import inspect
import json
import logging
import os
import sys

from crawlers.app_qunar_parse import parse_flight_rows
from crawlers.app_qunar_roundtrip import is_round_trip_page, parse_back_rows, parse_footer_total, parse_go_rows
from crawlers.qunar import QunarCrawler


# ---- merged from tests/test_r398_qunar_evidence_scope.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _crawler():
    c = QunarCrawler({}, logging.getLogger("t_r398"))
    c.path_reset()
    c._last_challenge = None
    return c


def _status(c, path):
    return [p["status"] for p in c.paths if p["path"] == path]


def test_no_result_does_not_leak_across_dates():
    """上一日期的 no-result 不得把本日期染成 empty。"""
    c = _crawler()
    c._last_no_result = True                    # 上一日期遗留
    QunarCrawler.login_suspect = True           # 会话确实失效
    c._fetch_via_browser = lambda *a, **k: None
    c._fetch_one("SHA", "BKK", "2026-11-16")
    assert _status(c, "H5") == ["login"], c.paths
    QunarCrawler.login_suspect = False


def test_true_no_result_still_empty():
    """本日期真的明确无票时，仍然必须是 empty（别把修复做过头）。"""
    c = _crawler()

    def _br(*a, **k):
        c._last_no_result = True
        return None

    c._fetch_via_browser = _br
    c._fetch_one("SHA", "BKK", "2026-11-17")
    assert _status(c, "H5") == ["empty"], c.paths


def test_no_result_text_is_recognized_on_api_body():
    """API 的 1999+明确措辞必须被认成无票，而不是"没有明细"。"""
    body = json.dumps({
        "bstatus": {"code": 1999, "status": 1999,
                    "msg": "没有查询到符合条件的航班"},
        "code": -1, "data": None,
        "msg": "没有查询到符合条件的航班", "ret": False,
    }, ensure_ascii=False)
    c = _crawler()
    assert c._no_result_text(body) is True
    # 不能把普通软拒/空壳误认成无票
    assert c._no_result_text(json.dumps({"ret": False, "msg": "系统繁忙"})) is False


def test_api_does_not_inherit_h5_verdict():
    """H5 判完无票后，API 必须自己重新判，不能继承。"""
    c = _crawler()
    c._last_no_result = True          # H5 刚判完
    seen = []

    def _httpx(fc, tc, d):
        # 记录进入 API 时标志是否已被清
        seen.append(bool(getattr(c, "_last_no_result", False)))
        c.last_soft_reject = {"kind": "token_gate", "note": "门拒"}
        return None

    c._fetch_via_browser = lambda *a, **k: None
    c._fetch_via_httpx = _httpx
    c._fetch_one("SHA", "BKK", "2026-11-16")
    assert seen == [False], "API 起点必须已清标志，实际=%r" % seen
    # 不继承 H5 的 empty，也不冒充 login
    assert _status(c, "API") == ["soft_reject"], c.paths


def test_blanket_1999_is_soft_not_empty():
    """httpx 的 1999「没有航班」是门拒文案，不得记 empty。

    实证：同一 token 连打四条已知有票的航线（SHA→BKK 别处采到 ¥662、
    SHA→HAK、HAK→SHA、SHA→NRT），四条回应一字不差都是
    code=-1 +「没有查询到符合条件的航班」+ data=null。
    真无票不会恰好四条全无、还与已采到的价矛盾。
    把它记成 empty = 谎报「真无票」，比记错登录更违反数据诚实。
    """
    import core.net as _net  # noqa: F401

    class _Resp:
        status_code = 200
        headers = {}
        text = json.dumps({
            "bstatus": {"code": 1999, "msg": "没有查询到符合条件的航班"},
            "code": -1, "data": None,
            "msg": "没有查询到符合条件的航班", "ret": False,
        }, ensure_ascii=False)

    c = _crawler()
    c._load_token = lambda: {"headers": {}, "body_template": {},
                             "cookies": {}, "updated_at": 0}
    c.last_soft_reject = {}
    import core.net
    _orig = core.net.post
    core.net.post = lambda *a, **k: _Resp()
    try:
        out = c._fetch_via_httpx("SHA", "BKK", "2026-11-16")
    finally:
        core.net.post = _orig
    assert out is None
    assert c.last_soft_reject.get("kind") == "token_gate", c.last_soft_reject
    assert getattr(c, "_last_no_result", False) is False, \
        "门拒文案不得被当成真无票"


# ---- merged from tests/test_r701_qunar_round_trip.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_P = "flight_module_search|"


def _n(desc, text, x1, y1, x2, y2):
    return ('<node text="%s" content-desc="%s" resource-id="" '
            'class="android.widget.TextView" bounds="[%d,%d][%d,%d]" />'
            % (text, desc, x1, y1, x2, y2))


def _go_card(y1, y2, fno, price, dep, arr, selected):
    state = "selected" if selected else "unselected"
    return (_n(_P + "QunarFlightList|FlightsRound_go_" + state, "", 0, y1, 796, y2)
            + _n(_P + "QunarFlightList|FlightsRound_" + fno, "", 0, y1, 796, y2)
            + _n(_P + "round_way_flights|go_depTime", dep, 15, y1 + 37, 78, y1 + 67)
            + _n(_P + "round_way_flights|go_arrTime", arr, 144, y1 + 37, 207, y1 + 67)
            + _n(_P + "round_way_flights|go_aircraftType", "x" + fno,
                 15, y1 + 107, 704, y1 + 128)
            + _n(_P + "round_way_flights|go_depPrice", price,
                 719, y1 + 98, 761, y1 + 131))


def _back_card(y1, y2, fno, supply, dep, arr, selected):
    state = "selected" if selected else "unselected"
    return (_n(_P + "QunarFlightList|FlightsRound_back_" + state, "", 805, y1, 1600, y2)
            + _n(_P + "QunarFlightList|FlightsRound_" + fno, "", 805, y1, 1600, y2)
            + _n(_P + "round_way_flights|back_depTime", dep, 820, y1 + 37, 883, y1 + 67)
            + _n(_P + "round_way_flights|back_arrTime", arr, 949, y1 + 37, 1012, y1 + 67)
            + _n(_P + "round_way_flights|back_aircraftType", "x" + fno,
                 820, y1 + 113, 1452, y1 + 134)
            + _n(_P + "round_way_flights|back_supplyPrice", supply,
                 1565, y1 + 106, 1579, y1 + 139))


def _page(total=None):
    xml = ('<hierarchy>'
           + _n(_P + "QunarFlightList|ScrollView_go", "", 0, 348, 796, 827)
           + _go_card(348, 527, "HO1258", "726", "11:55", "14:10", True)
           + _go_card(527, 692, "CZ8882", "730", "14:00", "16:30", False)
           + _go_card(693, 827, "HO1254", "746", "21:20", "23:30", False)
           + _n(_P + "QunarFlightList|ScrollView_back", "", 805, 348, 1600, 827)
           + _back_card(348, 533, "HO1251", "0", "10:25", "12:40", True)
           + _back_card(533, 704, "HO1257", "16", "08:25", "10:50", False)
           # 真机第三张卡被屏幕底部裁到 827，航司行只剩一半——仍要整卡
           # 归属正确（这里给足高度，模拟滚动后完整可见的形态）
           + _back_card(705, 859, "3U4553", "39", "08:25", "10:50", False))
    if total is not None:
        xml += (_n("", "¥" + total, 27, 834, 98, 879)
                + _n("", "往返价格", 27, 876, 1369, 894))
    return xml + '</hierarchy>'


def test_page_marker():
    assert is_round_trip_page(_page())
    assert not is_round_trip_page("<hierarchy></hierarchy>")


def test_go_rows_pair_price_with_own_card():
    rows = parse_go_rows(_page())
    assert [r["flight_no"] for r in rows] == ["HO1258", "CZ8882", "HO1254"]
    assert [r["price"] for r in rows] == [726, 730, 746]
    assert rows[0]["depart_time"] == "11:55"
    assert rows[1]["arrive_time"] == "16:30"


def test_back_supply_price_is_not_a_fare():
    rows = parse_back_rows(_page())
    # 0 是「补 0 元」的真实读数（不是缺失）；不能因为 falsy 被丢掉
    assert [r["supply_price"] for r in rows] == [0, 16, 39]
    assert [r["flight_no"] for r in rows] == ["HO1251", "HO1257", "3U4553"]


def test_numeric_prefix_airline_code_survives():
    # 3U4553（川航）在旧正则 `[A-Z]{2}\\d{3,4}` 下会被解析成空字符串
    rows = parse_back_rows(_page())
    assert rows[2]["flight_no"] == "3U4553"


def test_footer_total_only_when_label_present():
    assert parse_footer_total(_page("726")) == 726
    # 没有「往返价格」页脚（未选中组合）时绝不拿列表里的 ¥ 顶替
    assert parse_footer_total(_page(None)) is None


def test_footer_prefers_total_over_card_price():
    """页脚 ¥726 与首卡 go_depPrice 726 同值时也不能混淆来源。

    改成页脚 941（=947 去程 + -6 补价，真机实测过这组）后仍要读 941，
    证明取的是页脚而不是卡内价。
    """
    xml = _page("941")
    assert parse_footer_total(xml) == 941


def test_empty_page_yields_nothing():
    assert parse_go_rows("<hierarchy></hierarchy>") == []
    assert parse_back_rows("<hierarchy></hierarchy>") == []
    assert parse_footer_total("<hierarchy></hierarchy>") is None


def test_intl_round_trip_is_recorded_as_unsupported_not_timeout(monkeypatch):
    """国际档不给往返结果页：账本要写 unsupported，不能只写 no-list-page。

    现场（2026-11-01 SHA→LHR）：表单确实是「往返 + 去程 11-23 + 返程 11-30」，
    搜索后却是 25 张 `QunarFlightInterList` 单程卡（无 ScrollView_go/back、
    无「往返价格」页脚）。那 60 秒等待只是在等一个不会出现的页面；结果如果
    只记 no-list-page，读起来像「页面没打开」。
    """
    import crawlers.app_qunar as M

    ticks = {"t": 0.0}

    class FakeTime:
        @staticmethod
        def time():
            ticks["t"] += 1.0
            return ticks["t"]

        @staticmethod
        def sleep(_s):
            pass

        strftime = staticmethod(lambda fmt: "20261101_000000")

        def __getattr__(self, k):
            return getattr(__import__("time"), k)

    monkeypatch.setattr(M, "time", FakeTime)
    monkeypatch.setattr(M, "_sleep", lambda s: None)

    page = ('<hierarchy><node text="搜索" bounds="[48,769][1552,826]" />'
            '<node text="02:25" bounds="[39,384][116,426]" />'
            '<node text="07:10" bounds="[283,384][357,426]" />'
            '</hierarchy>')

    class D:
        def dump(self, retries=2):
            return page

        def tap(self, x, y):
            return True

    c = M.AppQunarCrawler.__new__(M.AppQunarCrawler)
    c.name = "app_qunar"
    c.package = "com.Qunar"
    c.paths = []
    c.login_suspect = False
    c._set_round_trip_form = lambda *a, **k: (True, "")
    c._scroll_home = lambda dev, want="search": page
    notes, dates = [], []
    c.path_note = lambda *a, **k: notes.append((a, k))
    c.note_date = lambda *a, **k: dates.append((a, k))

    prices = c._fetch_round_trip_locked(D(), "SHA", "LHR",
                                        ["2026-11-23"], "2026-11-30")
    assert prices == []
    trips = [n for n in notes if n[0] and n[0][0] == "TRIP"]
    assert trips, "国际往返没有记 TRIP 路径"
    assert trips[0][0][1] == "unsupported", (
        "国际档无往返结果页应记 unsupported，实际 %r" % (trips[0],))
    assert "国际" in str(trips[0][1].get("detail", "")), (
        "说明里要写清是国际档：%r" % (trips[0],))
    assert any(d[0][2] == "no-list-page" for d in dates if len(d[0]) > 2), (
        "日期级仍要如实记 no-list-page：%r" % (dates,))


# ---- merged from tests/test_r931_qunar_yuan_price.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _card(dep, price, y, arr="00:45"):
    """造一张中转混合列表卡片。

    真实结构（现场 2026-11-04 10:33，同一排三个节点，y 相同）：
        ItemDepTime  x=18   20:55
        ItemArrTime  x=301  00:45
        ItemPrice    x=662  ¥5711
    解析器以"左半屏时刻 + 同排右侧时刻"为锚配成一行，所以**到达时刻必须有**。
    """
    return ('<node text="%s" content-desc="flight_search_rn|'
            'QunarFlightInterRoundMixList|ItemDepTime" '
            'bounds="[18,%d][80,%d]" />'
            '<node text="%s" content-desc="flight_search_rn|'
            'QunarFlightInterRoundMixList|ItemArrTime" '
            'bounds="[301,%d][366,%d]" />'
            '<node text="%s" content-desc="flight_search_rn|'
            'QunarFlightInterRoundMixList|ItemPrice" '
            'bounds="[662,%d][723,%d]" />'
            % (dep, y, y + 33, arr, y, y + 33, price, y, y + 33))


def _xml(*cards):
    return "".join(cards)


# ---------------------------------------------------------------------------
# 1. 核心修复：带 ¥ 的价格必须能取到
# ---------------------------------------------------------------------------
def test_yen_prefixed_price_is_parsed():
    xml = _xml(_card("20:55", "¥5711", 366), _card("03:55", "¥4999", 505))
    rows = parse_flight_rows(xml)
    prices = sorted(r["price"] for r in rows if r.get("price"))
    assert prices == [4999, 5711], rows


def test_fullwidth_yen_and_thousands_sep():
    xml = _xml(_card("10:45", "￥1,234", 366))
    rows = parse_flight_rows(xml)
    assert [r["price"] for r in rows if r.get("price")] == [1234]


def test_plain_number_still_works():
    """老形态（纯数字）不能因为这次改动而回归。"""
    xml = _xml(_card("13:10", "3305", 366))
    rows = parse_flight_rows(xml)
    assert [r["price"] for r in rows if r.get("price")] == [3305]


def test_price_none_when_absent():
    """没有价格的卡片仍给 price=None（绝不给 0）。"""
    xml = ('<node text="07:00" content-desc="flight_search_rn|'
           'QunarFlightInterRoundMixList|ItemDepTime" '
           'bounds="[18,366][80,399]" />')
    rows = parse_flight_rows(xml)
    assert rows == [] or all(r.get("price") is None for r in rows)


# ---------------------------------------------------------------------------
# 2. 不应该被误当成价格的东西
# ---------------------------------------------------------------------------
def test_too_many_digits_rejected():
    """位数超范围（如 6 位）不是票价。"""
    xml = _xml(_card("09:00", "¥123456", 366))
    rows = parse_flight_rows(xml)
    assert all(r.get("price") != 123456 for r in rows)


def test_discount_tag_not_price():
    """「已减 ¥70」是优惠标签，不是票价（既有判据不能被破坏）。"""
    xml = ('<node text="08:00" content-desc="flight_search_rn|'
           'QunarFlightInterRoundMixList|ItemDepTime" '
           'bounds="[18,366][80,399]" />'
           '<node text="¥" bounds="[1560,370][1570,395]" />'
           '<node text="已减" bounds="[1580,372][1620,394]" />'
           '<node text="70" bounds="[1625,370][1655,395]" />')
    rows = parse_flight_rows(xml)
    assert all(r.get("price") != 70 for r in rows), rows


# ---------------------------------------------------------------------------
# 3. 真实现场回归（一份 dump = 6 张卡片 6 个价）
# ---------------------------------------------------------------------------
def test_real_scene_six_prices():
    """2026-11-04 10:33 真实 SHA→BKK 现场：6 行，六个价全在。

    修前这份 dump 解析出「6 行、带价 0 行」→ 上层记 no-priced-rows。
    """
    cards = [_card("20:55", "¥5711", 366),
             _card("03:55", "¥4999", 505),
             _card("13:10", "¥5455", 645),
             _card("10:45", "¥5465", 784),
             _card("16:10", "¥8418", 923),
             _card("17:35", "¥8418", 1062)]
    rows = parse_flight_rows(_xml(*cards))
    priced = [r for r in rows if r.get("price")]
    assert len(priced) == 6, [r.get("price") for r in rows]
    assert sorted(r["price"] for r in priced) == [4999, 5455, 5465, 5711,
                                                 8418, 8418]


# ---------------------------------------------------------------------------
# 4. 源码钉：不许退回「只认纯数字」
# ---------------------------------------------------------------------------
def test_source_accepts_currency_prefix():
    import io
    src = io.open(os.path.join(ROOT, "crawlers", "app_qunar_parse.py"),
                  encoding="utf-8").read()
    assert '[¥￥$' in src or "\u00a5" in src, "没剥货币符号"
    assert "QunarFlightInterRoundMixList" in src, "没记录中转混合列表这条现场"


# ---- merged from tests/test_v15279_qunar.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    with io.StringIO(webui_full_src()) as f:
        return f.read()


def test_qunar_crawler_h5_first_and_pc_dead():
    from crawlers.qunar import QunarCrawler as QC
    assert QC.URL_TPL.startswith(
        "https://m.flight.qunar.com/ncs/page/flightlist")
    assert "flight.qunar.com/site/oneway_list.htm" not in QC.URL_TPL
    fn = inspect.getsource(QC._fetch_one)
    assert fn.index("_fetch_via_browser") < fn.index("_fetch_via_pc")
    body = inspect.getsource(QC._fetch_inner)
    assert "H5 浏览器优先" not in body  # 注释在 _fetch_one，防误挂
    assert "H5 浏览器优先" in fn


def test_qunar_user_links_are_h5_not_pc():
    import logging
    from core.alerter import Alerter
    from core.models import Route
    a = Alerter(logging.getLogger("t"), storage=None)
    r = Route(from_code="SHA", from_name="上海", to_code="CAN",
              to_name="广州", dates=["2026-10-23"])
    u = a._build_view_url(r, "2026-10-23", "qunar")
    assert "m.flight.qunar.com/ncs/page/flightlist" in u
    assert "flight.qunar.com/site/oneway_list.htm" not in u
    assert "depCity=%E4%B8%8A%E6%B5%B7" in u and "goDate=2026-10-23" in u


def test_qunar_page_has_no_dead_pc_link():
    page = _src()
    assert "flight.qunar.com/site/oneway_list.htm" not in page
    assert "m.flight.qunar.com/ncs/page/flightlist" in page


def test_ctrip_intl_login_is_classified():
    src = open(os.path.join(ROOT, "crawlers", "ctrip.py"),
               encoding="utf-8").read()
    assert "需登录 · 国际列表需携程会话" in src
    assert "CtripCrawler.login_suspect = True" in src
    assert "服务器发生异常" in src
