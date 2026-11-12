# -*- coding: utf-8 -*-
"""r732 智行 App「特价」= 逐天报价，接成 low_fare 发现源。

真机实测（2026-10-31，海口→上海）：首页「特价」页签 → 设出发/到达 +
日期区间 →「搜索特价」→ 结果页逐天列出：

    02.16 周二   ¥1646
    02.15 周一   ¥1646
    02.14 周日   ¥1646

**此前被记成「目的地低价榜、口径对不上」是错的**——那是把首页
「省钱攻略」里按目的地报价的推荐卡当成了「特价」档。这直接导致
`app_alignment_gaps("app_zhixing")` 恒为 `("low_fare",)`，
「两款 App 与浏览器渠道同口径」这条一直差一格。

判据的关键陷阱（真机 dump 里就有）：
  * 同一页还有「近期成交价¥462」——那是历史参考价，**不是**当天报价。
    只按「有 ¥ 就算价」会把它算成 02-14 的价格（462 ≠ 1646）；
  * 日期只有 `MM.DD`，年份要按锚点推，跨年不能错；
  * 价格是 `¥` 与数字两个节点。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers.app_zhixing_lowfare import (  # noqa: E402
    parse_low_fare_rows, to_ymd, is_low_fare_page, find_entry,
    page_selection, selection_covers,
)

# 真机 dump（2026-10-31 海口→上海 特价结果页），入库为固定样本
REAL = os.path.join(ROOT, "tests", "fixtures", "zhixing_low_fare_result.xml")


def _xml(rows, extra=""):
    out = ["<hierarchy>"]
    for i, (md, wd, price) in enumerate(rows):
        y = 800 + i * 60
        out.append('<node text="%s" bounds="[42,%d][92,%d]" />'
                   % (md, y, y + 20))
        out.append('<node text="%s" bounds="[98,%d][148,%d]" />'
                   % (wd, y, y + 20))
        out.append('<node text="¥" bounds="[767,%d][780,%d]" />'
                   % (y - 3, y + 17))
        out.append('<node text="%d" bounds="[780,%d][830,%d]" />'
                   % (price, y, y + 22))
    out.append(extra)
    out.append("</hierarchy>")
    return "".join(out)


ROWS = [("02.16", "周二", 1646), ("02.15", "周一", 1640),
        ("02.14", "周日", 1588)]


def test_parses_each_day_from_layout():
    got = parse_low_fare_rows(_xml(ROWS))
    assert [r["md"] for r in got] == ["02.14", "02.15", "02.16"]
    assert [r["price"] for r in got] == [1588, 1640, 1646]
    assert [r["weekday"] for r in got] == ["周日", "周一", "周二"]


def test_row_takes_the_rightmost_price_on_its_own_row():
    """一行里出现两个价时，取**本行最靠右**的那个（价格列在右侧）。

    真机页面在日期行右侧还有「已减 ¥75」这类优惠标签。价格列在整页
    最右，所以按 x 取最右能稳定拿到票价；若改成「取第一个遇到的价」，
    就会把优惠标签的 75 当成票价——这条用例就是那个负控。
    """
    xml = ('<hierarchy>'
           '<node text="02.16" bounds="[42,800][92,820]" />'
           '<node text="周二" bounds="[98,800][148,820]" />'
           # 优惠标签在前（文档序），x 更小
           '<node text="¥" bounds="[500,798][512,812]" />'
           '<node text="75" bounds="[512,800][545,822]" />'
           # 票价在后，x 更靠右
           '<node text="¥" bounds="[767,798][780,812]" />'
           '<node text="1646" bounds="[780,800][830,822]" />'
           '</hierarchy>')
    got = parse_low_fare_rows(xml)
    assert len(got) == 1, got
    assert got[0]["price"] == 1646, (
        "取到了优惠标签的价而不是票价：%s" % (got,))


def test_reference_price_line_without_date_is_ignored():
    """「近期成交价¥462」整串带前缀，既非裸 ¥ 节点也过不了 ^¥数字$。

    它没有同排日期，所以本来就进不了任何一行；这里明确钉住这个结果，
    免得将来放宽正则后把它吃成某天的价。
    """
    noise = ('<node text="近期成交价¥462" bounds="[353,830][500,860]" />')
    xml = _xml(ROWS).replace("</hierarchy>", noise + "</hierarchy>")
    got = parse_low_fare_rows(xml)
    assert 462 not in [r["price"] for r in got], got
    assert len(got) == 3, got


def test_whole_string_price_is_accepted():
    """有的版式把价格写成整串 ¥1646（与列表页同款两种形态）。"""
    xml = ('<hierarchy>'
           '<node text="02.16" bounds="[42,800][92,820]" />'
           '<node text="周二" bounds="[98,800][148,820]" />'
           '<node text="¥1646" bounds="[767,800][830,822]" />'
           '</hierarchy>')
    got = parse_low_fare_rows(xml)
    assert len(got) == 1 and got[0]["price"] == 1646, got


def test_year_inference_across_new_year():
    assert to_ymd("02.16", "2026-10-31") == "2027-02-16"
    assert to_ymd("01.05", "2026-12-20") == "2027-01-05"
    assert to_ymd("12.28", "2027-01-03") == "2026-12-28"
    assert to_ymd("11.07", "2026-10-31") == "2026-11-07"
    assert to_ymd("bad", "2026-10-31") == ""


def test_page_predicate_covers_entry_and_result():
    entry = '<hierarchy><node text="搜索特价" /></hierarchy>'
    result = ('<hierarchy><node text="出发日期" />'
              '<node text="重新选择" /></hierarchy>')
    home = '<hierarchy><node text="机票查询" /></hierarchy>'
    assert is_low_fare_page(entry) is True
    assert is_low_fare_page(result) is True
    assert is_low_fare_page(home) is False


def test_find_entry_returns_the_teja_tab():
    xml = ('<hierarchy>'
           '<node text="国内" bounds="[100,330][150,360]" />'
           '<node text="特价" bounds="[750,330][800,360]" />'
           '</hierarchy>')
    n = find_entry(xml)
    assert n is not None and n.text == "特价"
    # Node 只有 cy 没有 cx（见 app_zhixing_parse.Node），点击用边界取中
    assert (n.x1 + n.x2) // 2 == 775
    assert n.cy == 345


def test_real_device_dump_gives_three_days_no_reference_price():
    """真机回归：3 天各一条，且都不等于「近期成交价 462」。"""
    assert os.path.exists(REAL), "真机 dump 样本缺失：%s" % REAL
    xml = io.open(REAL, encoding="utf-8").read()
    got = parse_low_fare_rows(xml)
    assert len(got) == 3, got
    for r in got:
        assert r["price"] != 462, "把近期成交价当成了当天报价：%s" % (r,)
        assert to_ymd(r["md"], "2026-10-31").startswith("2027-02-")

def test_low_fare_taps_search_with_bounds(monkeypatch):
    """r805ch：「搜索特价」来自 parse.Node（只有 cy，没有 cx）。

    现场（2026-11-02 01:47 雷达只选两个 App）：智行报
    `'Node' object has no attribute 'cx'`，整条低价源在点按钮时崩掉。
    这里用替身设备复现该路径：必须先过「找到按钮」，且点击坐标取
    边界中点（与 find_entry 同一约定），而不是 .cx。
    """
    import contextlib
    import logging

    import crawlers.app_zhixing as m
    from crawlers.app_zhixing import AppZhixingCrawler

    entry = ('<hierarchy><node text="上海-北京" />'
             '<node text="11月10日-11月12日" />'
             '<node text="搜索特价" '
             'bounds="[700,900][800,960]" /></hierarchy>')
    result = _xml([("02.16", "周二", 1646)])
    taps = []

    class Dev:
        def __init__(self):
            self.tapped = False

        def dump(self):
            return result if self.tapped else entry

        def tap(self, x, y):
            taps.append((x, y))
            # 「搜索特价」点下去之后结果页才出现；之前的 F 序变化
            # （驱动会多 dump 几次）不该把结果页当成入口页。
            if (x, y) == (750, 930):
                self.tapped = True
            return True

    dev = Dev()

    class RT:
        def ensure_ready(self):
            return True, ""

        def device(self):
            return dev

        def device_lock(self, owner=""):
            return contextlib.nullcontext()

    c = AppZhixingCrawler({"user_data_dir": "user_data",
                           "android": {"enabled": True}},
                          logging.getLogger("r732"))
    c.runtime = lambda: RT()
    c.prepare_device = lambda d: None
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    rows = c.low_fare("SHA", "BJS", days=3, anchor_ymd="2026-11-10")
    assert taps == [(750, 930)], taps
    assert rows and rows[0]["price"] == 1646, rows


def test_page_selection_reads_route_and_band():
    xml = ('<hierarchy><node text="上海" /><node text="出发日期" />'
           '<node text="2月14日-2月16日" /><node text="上海-" />'
           '<node text="上海-新加坡" /></hierarchy>')
    route, band = page_selection(xml)
    assert route == ("上海", "新加坡")
    assert band == (2, 14, 2, 16)


def test_selection_covers_requires_route_and_date_band():
    import datetime as dt
    xml = ('<hierarchy><node text="上海-新加坡" />'
           '<node text="2月14日-2月16日" /></hierarchy>')
    ok, why = selection_covers(xml, "上海", "北京",
                               dt.date(2026, 11, 10), dt.date(2026, 11, 12))
    assert not ok and "上海-新加坡" in why, why
    ok, why = selection_covers(xml, "上海", "新加坡",
                               dt.date(2026, 11, 10), dt.date(2026, 11, 12))
    assert not ok and "日期带" in why, why
    ok, why = selection_covers(xml, "上海", "新加坡",
                               dt.date(2027, 2, 14), dt.date(2027, 2, 16))
    assert ok, why


def test_low_fare_refuses_stale_page_without_tapping(monkeypatch):
    """页面停在别的航线/日期带时：先尝试驱动；驱动不动就不点搜索、如实记。

    r805ci 起 low_fare 会**驱动**表单改航线/日期。驱动失败（城市弹层
    打不开）时必须停在原地：既不能拿旧页面的报价冒充请求航线，也不能
    在没改成功的页面上点「搜索特价」——那会把旧航线的结果当新结果。
    """
    import contextlib
    import logging

    import crawlers.app_zhixing as m
    from crawlers.app_zhixing import AppZhixingCrawler

    stale = ('<hierarchy>'
             '<node text="上海" bounds="[69,450][858,487]" />'
             '<node text="新加坡" bounds="[69,525][858,562]" />'
             '<node text="2月14日 - 2月16日" bounds="[71,608][290,640]" />'
             '<node text="搜索特价" bounds="[700,900][800,960]" />'
             '</hierarchy>')
    taps = []

    class Dev:
        def dump(self):
            return stale

        def tap(self, x, y):
            taps.append((x, y))
            return True

    dev = Dev()

    class RT:
        def ensure_ready(self):
            return True, ""

        def device(self):
            return dev

        def device_lock(self, owner=""):
            return contextlib.nullcontext()

    c = AppZhixingCrawler({"user_data_dir": "user_data",
                           "android": {"enabled": True}},
                          logging.getLogger("r732"))
    c.runtime = lambda: RT()
    c.prepare_device = lambda d: None
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    # 时序不是这条用例的契约：把「等弹层」压成立即返回一帧
    c._lf_wait_for = lambda d, pred, timeout=0, step=0: d.dump() or ""
    rows = c.low_fare("SHA", "BJS", days=3, anchor_ymd="2026-11-10")
    assert rows == [], rows
    assert (750, 930) not in taps, "驱动失败仍点了「搜索特价」"
    assert any(p.get("path") == "low-fare" and "驱动失败" in p.get("detail", "")
               for p in c.paths), c.paths


def test_form_city_rows_reads_stacked_rows():
    """真机构型：出发/到达是上下两行整行中文，不是「A-B」。"""
    from crawlers.app_zhixing_lowfare import form_city_rows, page_selection
    xml = ('<hierarchy>'
           '<node text="机票用户订酒店，立享75折+最高20元返现" '
           'bounds="[87,386][825,411]" />'
           '<node text="上海" bounds="[69,450][858,487]" />'
           '<node text="新加坡，广州" bounds="[69,525][858,562]" />'
           '<node text="2月14日 - 2月16日" bounds="[71,608][290,640]" />'
           '<node text="搜索特价" bounds="[42,728][858,803]" />'
           '</hierarchy>')
    rows = form_city_rows(xml)
    assert [r.text for r in rows] == ["上海", "新加坡，广州"]
    assert page_selection(xml) == (("上海", "新加坡，广州"),
                                   (2, 14, 2, 16))


def test_pending_cities_reads_multi_select_chips():
    from crawlers.app_zhixing_lowfare import pending_cities
    xml = ('<hierarchy>'
           '<node text="新加坡" resource-id="cn.suanya.zhixing:id/'
           'Search_City_Multi_Cities_Bottom_Bar_Item_Text-0" '
           'bounds="[25,1538][94,1570]" />'
           '<node text="广州" resource-id="cn.suanya.zhixing:id/'
           'Search_City_Multi_Cities_Bottom_Bar_Item_Text-1" '
           'bounds="[140,1538][209,1570]" />'
           '</hierarchy>')
    assert [(t, x2) for t, x2, _ in pending_cities(xml)] == [
        ("新加坡", 94), ("广州", 209)]


def test_calendar_cells_assign_month_and_drop_leading_tail():
    """月份按上方最近的「YYYY年M月」标题归属；标题之上的上月尾巴丢弃。"""
    from crawlers.app_zhixing_lowfare import calendar_cells, calendar_months
    xml = ('<hierarchy>'
           '<node text="31" bounds="[50,518][80,538]" />'
           '<node text="2026年11月" bounds="[400,600][500,624]" />'
           '<node text="10" bounds="[300,680][330,700]" />'
           '<node text="12" bounds="[560,680][590,700]" />'
           '<node text="2026年12月" bounds="[400,1152][500,1176]" />'
           '<node text="1" bounds="[180,1230][210,1250]" />'
           '</hierarchy>')
    got = calendar_cells(xml)
    assert (2026, 11, 31) not in [c[:3] for c in got], got
    assert (2026, 11, 10) in [c[:3] for c in got], got
    assert (2026, 12, 1) in [c[:3] for c in got], got
    assert calendar_months(xml) == [(2026, 11), (2026, 12)]


def test_calendar_cells_prefer_iso_resource_id():
    """真机日格自带 ISO id：优先按 id 取，不受月份标题影响。

    不可售日期**不渲染**（2026-11-02 实测缺格），所以「找不到」不是解析
    失败——驱动要据此跳到窗口内最近可售日。
    """
    from crawlers.app_zhixing_lowfare import calendar_cells
    xml = ('<hierarchy>'
           '<node text="2026年11月" bounds="[400,500][500,524]" />'
           '<node text="1" resource-id="cn.suanya.zhixing:id/'
           'flight_calendar_date_cell_date_text-2026-11-01" '
           'bounds="[50,600][80,620]" />'
           '<node text="3" resource-id="cn.suanya.zhixing:id/'
           'flight_calendar_date_cell_date_text-2026-11-03" '
           'bounds="[180,600][210,620]" />'
           '</hierarchy>')
    got = [c[:3] for c in calendar_cells(xml)]
    assert got == [(2026, 11, 1), (2026, 11, 3)], got


def test_selection_within_allows_first_day_unsellable():
    """首日不可售 → 带起点晚一天仍可采；终点不到位就必须判失败。"""
    import datetime as dt
    from crawlers.app_zhixing_lowfare import selection_within
    xml = ('<hierarchy>'
           '<node text="上海" bounds="[69,450][858,487]" />'
           '<node text="广州" bounds="[69,525][858,562]" />'
           '<node text="11月3日 - 11月15日" bounds="[71,608][290,640]" />'
           '<node text="搜索特价" bounds="[42,728][858,803]" />'
           '</hierarchy>')
    start, end = dt.date(2026, 11, 2), dt.date(2026, 11, 15)
    ok, eff, why = selection_within(xml, "上海", "广州", start, end)
    assert ok and eff == (11, 3), (ok, eff, why)
    ok, _, why = selection_within(xml, "上海", "广州", start,
                                  dt.date(2026, 11, 16))
    assert not ok and "末日" in why, why
