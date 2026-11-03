# -*- coding: utf-8 -*-
r"""r815a：去哪儿 App 日历/低价机票从“未接通”更正为原生可采集。

现场（2026-11-02 06:34–06:49，真机、已登录）：
  * 首页「低价机票」点「搜索低价机票」后落 **QReactNativeActivity1**
    （React Native 原生页），不是 H5 WebView；dump 有日期条+航班行。
  * 现成 `AppQunarCrawler.low_fare('BJS','SHA',days=14)` 41.2s 出 14 天：
    11-02 ¥408、11-03 ¥359、11-04 ¥450 … 11-15 ¥410。
  * 低价页点「日历」后整月 2026-11/2026-12/2027-01 每天都有 ¥ 价。
  * 因此矩阵 `app_qunar.low_fare/calendar` 都必须为 y，雷达源恢复；
    `low_fare` 成功后同时写 `path_note("日历","calendar")`，让日历维度
    有独立账本证据，而不是只靠 low-fare 一条名字。

旧结论「落到 H5 WebView、dump 无文本」保留为异常转场兜底（遇到
`HyWebActivity` 仍记 unsupported），但不能再用它把整条能力判成 n。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.channels import CHANNEL_DIMENSIONS, DIMENSION_NOTES, app_alignment_gaps
from core.specials import SPECIAL_CAPABILITY


def test_matrix_marks_qunar_app_calendar_and_low_fare_as_verified():
    dims = CHANNEL_DIMENSIONS["app_qunar"]
    assert dims["calendar"] == "y", dims
    assert dims["low_fare"] == "y", dims
    # 2026-11-03：ctrip PC 多程 2 段升 y 后，App 端仅剩 multi_city 缺口。
    assert app_alignment_gaps("app_qunar") == ("multi_city",), \
        app_alignment_gaps("app_qunar")


def test_full_calendar_parses_day_cell_subtrees():
    """整月日格：date 在 content-desc，价格在子树，不依赖坏掉的 bounds。"""
    from crawlers.app_qunar_lowfare import parse_full_calendar
    xml = (
        '<hierarchy>'
        '<node content-desc="q_flight_calendarDayItem#2026-11-10">'
        '<node text="¥498"/><node text="10"/></node>'
        '<node content-desc="q_flight_calendarDayItem#2026-11-11">'
        '<node text="¥500"/><node text="11"/></node>'
        '<node content-desc="q_flight_calendarDayItem#2026-11-12">'
        '<node text="12"/></node>'   # 无价：跳过，不给 0
        '</hierarchy>')
    rows = parse_full_calendar(xml)
    assert rows == [{"date": "2026-11-10", "price": 498},
                    {"date": "2026-11-11", "price": 500}], rows


def test_notes_carry_the_native_page_evidence():
    low = DIMENSION_NOTES[("app_qunar", "low_fare")]
    cal = DIMENSION_NOTES[("app_qunar", "calendar")]
    assert "QReactNativeActivity1" in low, low
    assert "14 天" in low and "¥408" in low, low
    assert "日历" in cal and "整月" in cal, cal
    assert "2026-12" in cal and "60 天" in cal, cal


def test_radar_source_is_restored():
    entry = SPECIAL_CAPABILITY["app_qunar"]
    assert entry.get("sources") == ["app_qunar"], entry
    assert "低价" in entry.get("note", ""), entry


def test_low_fare_writes_a_separate_calendar_path():
    src = io.open(os.path.join(ROOT, "crawlers", "app_qunar.py"),
                  encoding="utf-8").read()
    i = src.index("def _low_fare_locked(")
    body = src[i:src.index("def _hard_reset_home(", i)]
    assert '"日历", "calendar"' in body, (
        "low_fare 成功后没有写独立日历证据，calendar=y 会失去账本支撑")
    assert "parse_full_calendar" in body, (
        "日历证据不是整月解析，而是日期带冒充？")
    assert 'path_note("low-fare", "ok"' in body, body[:200]
    assert "is_h5_low_fare_activity" in body, (
        "H5 WebView 异常转场兜底被删：遇到 H5 会误记 timeout")


def test_terminal_legend_distinguishes_product_from_collection():
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert "产品支持但采集端未实现或当前风控未出数" in src, (
        "矩阵图例仍把未验证读成渠道不支持")
    assert "渠道无此能力/停服" in src, src[:200]
