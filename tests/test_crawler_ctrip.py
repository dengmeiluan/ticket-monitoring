# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1050_ctrip_cal_scroll_dir.py
- tests/test_r1053_ctrip_cal_1260.py
- tests/test_r815i_ctrip_round_trip_pc.py
- tests/test_r945_ctrip_puzzle_simple.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import io
import json
import logging
import os
import sys

from crawlers import slider
from crawlers.app_ctrip import cal_scroll_dir
from crawlers.app_ctrip_calendar import _month_headers, parse_calendar_words
from crawlers.ctrip import CtripCrawler
from datetime import date


# ---- merged from tests/test_r1050_ctrip_cal_scroll_dir.py ----

#: 实测：表单残留 2027-02-14 时，日历首屏表头就这三行
_LEAKED = [(2027, 2, 684), (2027, 3, 1677), (2027, 4, 2670)]


def test_target_earlier_scrolls_back():
    assert cal_scroll_dir(_LEAKED, 2026, 11) == "back"


def test_target_later_scrolls_forward():
    assert cal_scroll_dir([(2026, 11, 684), (2026, 12, 1677)],
                          2027, 2) == "forward"


def test_target_visible_uses_forward_default():
    """目标已在可见范围时不会走到滚动分支，方向取默认值即可。"""
    assert cal_scroll_dir([(2026, 11, 684), (2026, 12, 1677)],
                          2026, 12) == "forward"


def test_empty_months_falls_back_to_forward():
    """表头都没识别出来时保持原行为，不要引入新的不确定性。"""
    assert cal_scroll_dir([], 2026, 11) == "forward"


def test_same_year_boundary_back():
    """跨年比较必须按 (年, 月) 元组，不能只比月份数字。"""
    assert cal_scroll_dir([(2027, 1, 684)], 2026, 12) == "back"
    assert cal_scroll_dir([(2026, 12, 684)], 2027, 1) == "forward"


def test_garbage_months_does_not_crash():
    assert cal_scroll_dir(None, 2026, 11) == "forward"
    assert cal_scroll_dir([("x", "y", 0)], 2026, 11) == "forward"


# ---- merged from tests/test_r1053_ctrip_cal_1260.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "ctrip_cal_1260_words.json")

#: 截图拍摄日：2026-11-06（fixture 里的「今天/明天/后天」按这个日期生成）
TODAY = date(2026, 11, 6)


def _words():
    return json.loads(io.open(FIX, encoding="utf-8").read())


def test_month_headers_need_scaled_left_bound():
    """左栏界限不缩放时认不出月份——这正是 0 行的第一因。"""
    w = _words()
    assert _month_headers(w, x_max=240.0) == [], "240 界限下不该认出完整月份"
    got = _month_headers(w, x_max=336.0)
    assert (2026, 11) in [(y, m) for y, m, _cy in got], got


def test_parses_daily_prices_at_1260():
    rows = parse_calendar_words(_words(), today=TODAY, width=1260)
    assert len(rows) >= 40, "1260 档应解析出整月逐日价，实际 %d 行" % len(rows)
    got = {r["date"]: r["price"] for r in rows}
    # 抽几个真机读到的值做锚（截图 OCR 原文：今天 500 / 明天 350 / 后天 400）
    assert got.get("2026-11-06") == 500.0
    assert got.get("2026-11-07") == 350.0
    assert got.get("2026-11-08") == 400.0
    # 11-10 是 ¥340（当天最低之一）
    assert got.get("2026-11-10") == 340.0


def test_weekday_label_matches_today():
    rows = parse_calendar_words(_words(), today=TODAY, width=1260)
    by = {r["date"]: r for r in rows}
    assert by["2026-11-06"]["weekday"] == "今天"
    assert by["2026-11-07"]["weekday"] == "明天"


def test_no_900_geometry_would_misparse():
    """不传宽度（按 900 基准）时解析不出东西——反证宽度标定是必需的。"""
    rows = parse_calendar_words(_words(), today=TODAY)
    assert rows == []


def test_all_dates_inside_visible_months():
    rows = parse_calendar_words(_words(), today=TODAY, width=1260)
    for r in rows:
        assert r["date"].startswith(("2026-11", "2026-12", "2027-01")), r
        assert r["price"] >= 10


# ---- merged from tests/test_r815i_ctrip_round_trip_pc.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t_r815i")

SAMPLE = """
携程旅行网
自由搭配往返组合
11-19周四去
11-22周日返
¥2404低
1选择去程上海东京11-19 周四2选择返程东京上海11-22 周日
直飞
直飞优先低价优先起飞时间早-晚耗时短优先更多排序
司比价低价提醒
捷星日本
GK036 空客320(中)
02:20
浦东国际机场T2
06:20
成田国际机场T3
3小时航班详情
¥2404起
往返含税价
选为去程
春秋航空日本
IJ004 波音737(中)
17:30
浦东国际机场T2
21:30
成田国际机场T3
3小时航班详情
¥2451起
往返含税价
选为去程
日本乐桃航空
01:10
浦东国际机场T2
04:40
羽田机场T3
2小时30分航班详情
¥2682起
往返含税价
选为去程
"""


class _Page:
    def __init__(self, body, url=""):
        self._body = body
        self.url = url
        self.closed = False
        self.gotos = []

    def goto(self, url, **_k):
        self.gotos.append(url)
        self.url = url

    def set_default_timeout(self, *_a, **_k):
        return None

    def inner_text(self, *_a, **_k):
        return self._body

    def wait_for_timeout(self, *_a, **_k):
        return None

    def close(self):
        self.closed = True


class _Ctx:
    def __init__(self, page):
        self.page = page

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def new_page(self, *_a, **_k):
        return self.page


def _crawler():
    c = CtripCrawler({}, _LOG)
    c._debug_snapshot = lambda *_a, **_k: None
    CtripCrawler.login_suspect = False
    return c


def _wire(monkeypatch, c, page):
    # 绕过 BaseCrawler.new_page 的超时/响应钩子：这里只验正文解析
    # 与落账，不测 Playwright 页面对象本身。
    monkeypatch.setattr(c, "browser", lambda *_a, **_k: _Ctx(page))
    monkeypatch.setattr(c, "new_page", lambda *_a, **_k: page)


def test_parse_rt_body_uses_product_total_only():
    rows = CtripCrawler._parse_rt_body(SAMPLE, "2026-11-19", "2026-11-22")
    assert len(rows) == 3, rows
    by_no = {r["flight"]: r for r in rows}
    assert by_no["GK036"]["price"] == 2404.0
    assert by_no["IJ004"]["price"] == 2451.0
    assert by_no[""]["price"] == 2682.0  # 乐桃那行页面没给航班号，不臆造
    gk = by_no["GK036"]
    assert (gk["dep"], gk["arr"]) == ("02:20", "06:20")
    assert gk["depAirport"] == "浦东国际机场T2"
    assert gk["arrAirport"] == "成田国际机场T3"
    assert gk["airline"] == "捷星日本"
    assert gk["basis"] == "product_round_trip_tax"
    assert gk["tripType"] == "RT" and gk["backDate"] == "2026-11-22"
    assert gk["depDate"] == "2026-11-19"
    # 顶部条带 ¥2404低 不是价锚，不能被当成卡片
    assert all("低" not in str(r.get("price")) for r in rows)


DOM_SAMPLE = """
11-03周二去
11-06周五返
¥1002低
1选择去程上海北京11-03 周二2选择返程北京上海11-06 周五
东方航空
MU5195\xa0空客321(中)
19:55
浦东国际机场T1
22:15
大兴国际机场
3小时20分航班详情
¥1002起
往返总价
选为去程
新海航｜海南航空
HU7610 空客330(大)
20:55
虹桥国际机场T2
23:15
首都国际机场T2
3小时20分航班详情
¥1020起
往返总价
选为去程
"""


def test_parse_rt_body_domestic_total_label():
    """国内页标签是「往返总价」而非「往返含税价」（实测两棵真页面）。"""
    rows = CtripCrawler._parse_rt_body(DOM_SAMPLE, "2026-11-03",
                                       "2026-11-06")
    assert len(rows) == 2, rows
    assert [r["price"] for r in rows] == [1002.0, 1020.0]
    assert rows[0]["flight"] == "MU5195"
    assert rows[0]["priceLabel"] == "往返总价"
    assert rows[0]["basis"] == "product_round_trip_total"
    assert rows[0]["backDate"] == "2026-11-06"


def test_parse_rt_body_requires_round_trip_tax_anchor():
    body = "\n".join([
        "捷星日本", "GK036 空客320(中)", "02:20", "浦东国际机场T2",
        "06:20", "成田国际机场T3", "3小时航班详情", "¥2404起",
        "选为去程",  # 单程卡：没有「往返含税价」
    ])
    assert CtripCrawler._parse_rt_body(body, "2026-11-19", "2026-11-22") == []


def test_parse_rt_body_skips_card_without_times():
    body = "\n".join(["捷星日本", "GK036 空客320(中)", "¥2404起",
                      "往返含税价", "选为去程"])
    assert CtripCrawler._parse_rt_body(body, "2026-11-19", "2026-11-22") == []
    assert CtripCrawler._parse_rt_body("", "2026-11-19", "2026-11-22") == []


def test_rt_url_is_round_trip_with_containstax():
    url = CtripCrawler.URL_RT_PC.format(
        from_city="sha", to_city="tyo", date="2026-11-19",
        ret_date="2026-11-22")
    assert "/round-sha-tyo?" in url
    assert "depdate=2026-11-19_2026-11-22" in url
    assert "containstax=1" in url


def test_fetch_rt_returns_product_total_and_ok_path(monkeypatch):
    c = _crawler()
    page = _Page(SAMPLE, url="https://flights.ctrip.com/online/list/round-sha-tyo")
    _wire(monkeypatch, c, page)
    out = c._fetch_rt("SHA", "TYO", ["2026-11-19"], "2026-11-22")
    assert len(out) == 1
    fp = out[0]
    assert fp.platform == "ctrip"
    assert fp.depart_date == "2026-11-19"
    assert fp.price == 2404.0  # 往返含税总价，不是单程 1202×2
    assert fp.flight_no == "GK036"
    rows = json.loads(fp.extra)
    assert len(rows) == 3 and rows[0]["basis"] == "product_round_trip_tax"
    notes = [p for p in c.paths if p["path"] == "往返"]
    assert len(notes) == 1 and notes[0]["status"] == "ok", c.paths
    assert notes[0]["rows"] == 3
    # 国际机场码归并城市码（NRT→TYO），且 URL 是往返入口
    assert any("/round-sha-tyo" in u for u in page.gotos), page.gotos


def test_fetch_rt_no_anchor_is_error_not_empty(monkeypatch):
    c = _crawler()
    page = _Page("<html>whaleguard</html>")
    _wire(monkeypatch, c, page)
    assert c._fetch_rt("SHA", "PEK", ["2026-11-19"], "2026-11-22") == []
    notes = [p for p in c.paths if p["path"] == "往返"]
    assert notes and notes[0]["status"] == "blocked", c.paths

    c2 = _crawler()
    page2 = _Page("<html>页面改版了</html>")
    _wire(monkeypatch, c2, page2)
    assert c2._fetch_rt("SHA", "PEK", ["2026-11-19"], "2026-11-22") == []
    notes2 = [p for p in c2.paths if p["path"] == "往返"]
    assert notes2 and notes2[0]["status"] == "error", c2.paths


def test_fetch_rt_explicit_no_flight_is_empty(monkeypatch):
    c = _crawler()
    page = _Page("没有符合条件的航班，请更换日期")
    _wire(monkeypatch, c, page)
    assert c._fetch_rt("SHA", "PEK", ["2026-11-19"], "2026-11-22") == []
    notes = [p for p in c.paths if p["path"] == "往返"]
    assert notes and notes[0]["status"] == "empty", c.paths
    assert "站点明确无可售往返" == notes[0]["detail"]


def test_fetch_ret_date_routes_to_rt_not_oneway(monkeypatch):
    c = _crawler()
    seen = {}

    def boom(*_a, **_k):
        raise AssertionError("往返不得走单程 H5/日历通路")

    monkeypatch.setattr(c, "_fetch_intl", boom)
    monkeypatch.setattr(c, "_fetch_rt",
                        lambda f, t, d, r: seen.update(args=(f, t, list(d), r)) or [])
    for frm, to in (("SHA", "CAN"), ("SHA", "TYO")):
        assert c.fetch(frm, to, ["2026-11-10"], ret_date="2026-11-15") == []
    assert seen["args"] == ("SHA", "TYO", ["2026-11-10"], "2026-11-15")
    assert [p for p in c.paths if p["path"] == "TRIP"] == []


# ---- merged from tests/test_r945_ctrip_puzzle_simple.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ---------------------------------------------------------------------------
# 1. 携程拼图文案要判成 simple（可解）
# ---------------------------------------------------------------------------
def test_ctrip_puzzle_is_simple():
    for text in ("请完成拼图验证", "拼图验证", "完成拼图",
                 "拖动滑块完成拼图"):
        tier = slider.classify("", text)
        assert tier.name == "simple", (text, tier.name)
        assert tier.solvable is True, text


# ---------------------------------------------------------------------------
# 2. 强人机边界不许破（这是红线）
# ---------------------------------------------------------------------------
def test_strong_still_not_solvable():
    for text in ("geetest 智能验证", "极验", "天御验证", "tcaptcha",
                 "baxia", "recaptcha", "hcaptcha", "请按顺序点击",
                 "人脸识别"):
        tier = slider.classify("", text)
        assert tier.solvable is False, (text, tier.name)


def test_unknown_text_still_unknown():
    assert slider.classify("", "请选择出发城市").name == "unknown"


# ---------------------------------------------------------------------------
# 3. 登录助手：结构 + 不碰强人机
# ---------------------------------------------------------------------------
_LOGIN = os.path.join(ROOT, "scripts", "ctrip_login.py")


def test_login_helper_exists_with_check_mode():
    src = io.open(_LOGIN, encoding="utf-8").read()
    assert "--check" in src and "--code" in src and "--send-only" in src
    assert "def is_logged_in(" in src
    assert "def solve_slider(" in src


def test_login_helper_skips_strong_tier():
    """滑块分级不是 simple 时**不许拖**（代码里要有这个闸）。"""
    src = io.open(_LOGIN, encoding="utf-8").read()
    i = src.find("def solve_slider(")
    j = src.find("\ndef ", i + 10)
    body = src[i:j]
    assert "tier.solvable" in body, "没有按分级放行"
    assert "不动手" in body, "非 simple 时没有明确放弃"


def test_login_helper_reuses_slider_module():
    """距离/轨迹必须复用 `crawlers.slider`，不许自己再算一遍。"""
    src = io.open(_LOGIN, encoding="utf-8").read()
    assert "from crawlers import slider" in src
    assert "attempt_device" in src
    # 不许自己实现拖动距离
    assert "def trajectory(" not in src, "自己实现了轨迹（会两处漂移）"


def test_login_helper_checks_result_honestly():
    src = io.open(_LOGIN, encoding="utf-8").read()
    # 结束必须核对登录态，而不是"拖完就算成功"
    assert "登录结果:" in src
    assert "成功" in src and "未成功" in src
