# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1063_tuniu_week_calendar.py
- tests/test_r1063_week_calendar_harvest.py
- tests/test_r1063_week_calendar_mixin.py
- tests/test_r1063_week_harvest_per_plat.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import io
import logging
import os
import sys

from crawlers import week_calendar as WC
from crawlers.ctrip import CtripCrawler
from crawlers.tuniu import TuniuCrawler


# ---- merged from tests/test_r1063_tuniu_week_calendar.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_week_dates_same_year_takes_min_price():
    d = TuniuCrawler._week_to_dates(
        "2026-11-16", [("11-13", 470), ("11-16", 388), ("11-16", 380)])
    assert d["2026-11-13"] == 470
    assert d["2026-11-16"] == 380, "同一日期要取最低价"


def test_week_dates_cross_year():
    d = TuniuCrawler._week_to_dates("2026-12-30", [("01-02", 999)])
    assert d == {"2027-01-02": 999}


def test_week_dates_ignores_dirty_rows():
    assert TuniuCrawler._week_to_dates(
        "2026-11-16", [("bad", 1), (None, 2), ("11-20", "x")]) == {}


def test_switch_default_off_and_config_on():
    """r1063 T154：代码默认**关闭**（单测不联网），生产由 config 显式打开。"""
    import logging
    assert TuniuCrawler({}, logging.getLogger("t"))._week_calendar_enabled() is False
    assert TuniuCrawler({"tuniu_week_calendar": True},
                        logging.getLogger("t"))._week_calendar_enabled() is True


def test_wired_as_independent_path():
    src = io.open(os.path.join(ROOT, "crawlers", "tuniu.py"),
                  encoding="utf-8").read()
    assert '"PC·周历"' in src, "周历必须是独立通路（单独进账本/面板）"
    assert "_fetch_week_calendar" in src
    # fetch 里必须有"列表/接口都没数时的兜底"
    i = src.index("def fetch(self, from_city")
    seg = src[i:src.index("def _split_pc_dates", i) if
              "def _split_pc_dates" in src[i:] else i + 12000]
    assert "_fetch_week_calendar" in seg, seg[-500:]


# ---- merged from tests/test_r1063_week_calendar_harvest.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(name):
    return io.open(os.path.join(ROOT, "crawlers", name), encoding="utf-8").read()


def test_switch_exists_in_both():
    for name in ("ctrip.py", "fliggy.py"):
        s = _src(name)
        assert "week_calendar_harvest" in s, "%s 缺开关" % name


def test_harvest_only_adds_dates_missing_from_list():
    for name in ("ctrip.py", "fliggy.py"):
        s = _src(name)
        i = s.index("week_calendar_harvest")
        seg = s[i:i + 900]
        assert "if not missing and not _harvest" in seg, (
            "%s 默认行为必须保持：没缺日期就不跑周历" % name)
        # 收割时要遍历周历全部日期
        j = s.index("_targets")
        seg2 = s[j:j + 500]
        assert "sorted(cal" in seg2, "%s 收割必须遍历周历全部日期" % name
        assert "d not in have" in seg2, "%s 不许覆盖列表已有的真实数据" % name


# ---- merged from tests/test_r1063_week_calendar_mixin.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_week_to_dates_same_year_min_price():
    d = WC.week_to_dates("2026-11-16", [("11-13", 1412), ("11-16", 1200),
                                        ("11-16", 1300)])
    assert d["2026-11-13"] == 1412
    assert d["2026-11-16"] == 1200, "同日取最低"


def test_week_to_dates_cross_year():
    assert WC.week_to_dates("2026-12-30", [("01-02", 999)]) == \
        {"2027-01-02": 999}


def test_week_to_dates_dirty_rows_never_raise():
    assert WC.week_to_dates("2026-11-16",
                            [("x", 1), (None, 2), ("11-20", "y")]) == {}
    assert WC.week_to_dates("bad", []) == {}


def test_ctrip_inherits_mixin_and_has_switch():
    assert issubclass(CtripCrawler, WC.WeekCalendarMixin)
    c = CtripCrawler({}, logging.getLogger("t"))
    # r1063 T154：代码默认关闭（单测不联网），生产由 config 显式打开
    assert c._week_calendar_enabled() is False
    on = CtripCrawler({"ctrip_week_calendar": True}, logging.getLogger("t"))
    assert on._week_calendar_enabled() is True


def test_ctrip_fetch_wraps_core_and_fills_week():
    """fetch() 必须是"核心采集 + 周历兜底"，核心采集改名为 _fetch_core。"""
    src = io.open(os.path.join(ROOT, "crawlers", "ctrip.py"),
                  encoding="utf-8").read()
    assert "def _fetch_core(" in src
    i = src.index("def fetch(self, from_city")
    seg = src[i:i + 500]
    assert "_fetch_core" in seg and "_fill_week" in seg
    assert '"PC·周历"' in src, "周历必须是独立通路"


def test_fliggy_inherits_mixin_and_skips_domestic():
    """飞猪：国际接周历兜底；国内页实测没有"周X ￥N"形态，必须跳过不浪费请求。"""
    from crawlers.fliggy import FliggyCrawler
    assert issubclass(FliggyCrawler, WC.WeekCalendarMixin)
    src = io.open(os.path.join(ROOT, "crawlers", "fliggy.py"),
                  encoding="utf-8").read()
    i = src.index("def _fill_week")
    seg = src[i:i + 2200]
    assert "is_intl_route" in seg, "国内必须跳过周历（无此结构）"
    assert "PC·周历" in seg


def test_week_js_tolerates_parenthetical_marker():
    """飞猪的日期条形态是 `11-16 周一(去) ¥282`——正则必须容忍括号后缀。"""
    assert "[（(]" in WC.WEEK_JS, "正则没容忍括号标记，飞猪会抽不到"


# ---- merged from tests/test_r1063_week_harvest_per_plat.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(name):
    return io.open(os.path.join(ROOT, "crawlers", name), encoding="utf-8").read()


def test_map_supported_in_both():
    for name in ("ctrip.py", "fliggy.py"):
        s = _src(name)
        assert "week_calendar_harvest_map" in s, "%s 缺按渠道覆盖" % name
        i = s.index("week_calendar_harvest_map")
        seg = s[i:i + 500]
        assert "get(self.name" in seg, "%s 必须按 self.name 取覆盖值" % name
        assert 'week_calendar_harvest' in seg, "%s 缺省要回退到全局开关" % name


def test_note_explains_why_per_channel():
    """注释里要写清"为什么需要按渠道"（飞猪无价 14.8s/次），否则后人会删掉。"""
    s = _src("fliggy.py")
    i = s.index("week_calendar_harvest_map")
    seg = s[max(0, i - 400):i + 400]
    assert "无价" in seg or "14.8" in seg, "要把飞猪的实测结果写进注释"
