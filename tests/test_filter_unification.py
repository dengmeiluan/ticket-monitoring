# -*- coding: utf-8 -*-
"""检索台筛选能力是明细表的超集；关注航线/关注航班共享曲线组件。"""
import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[1] / "webui.py"
TEXT = SRC.read_text(encoding="utf-8")


def test_search_filter_has_detail_grade_fields():
    m = re.search(r"const SRX_DEFAULT_F=\{(.*?)\};", TEXT, re.S)
    assert m
    fields = m.group(1)
    for key in ("laymin", "laymax", "durmin", "durmax", "prate", "age",
                "bagkg", "wb", "child", "few", "ps", "depA", "arrA",
                "shareMode", "stopMode", "riskMode"):
        assert key in fields, key


def test_search_scope_applies_detail_grade_fields():
    body = TEXT[TEXT.index("function srxScope("):TEXT.index("function srxFiltered(")]
    for key in ("F.laymin", "F.durmin", "F.prate", "F.age", "F.bagkg",
                "F.wb", "F.child", "F.few", "F.ps"):
        assert key in body, key


def test_search_merges_probe_and_detail_latest_rows():
    body = TEXT[TEXT.index("function srxAll("):TEXT.index("function srxPairName(")]
    assert "SRX.probe.rows" in body
    assert "pr.concat(extra)" in body
    assert "seen.has(srxKey(f))" in body


def test_detail_has_common_toggles_and_state():
    for key in ("shareOnly", "stopOnly", "riskOnly", "hideCal", "onlyQual"):
        assert key in TEXT
    for el in ("fshareonly", "fstoponly", "friskonly", "fhidecal", "fonlyqual"):
        assert 'id="%s"' % el in TEXT


def test_common_filter_group_and_reset_exist():
    assert "共同筛选" in TEXT
    assert "srxClearCommonFilters" in TEXT
    assert "fltscope" in TEXT


def test_shared_spark_used_by_route_flight_and_overview():
    assert "function trendSparkSvg(" in TEXT
    for fn in ("monWatchSvg", "monRouteCard", "wsRenderRouteWatch"):
        body = TEXT[TEXT.index("function %s(" % fn):]
        body = body[:body.index("\nfunction ", 1)]
        assert "trendSparkSvg(" in body, fn


def test_watch_copy_states_subset_entity():
    assert "关注航班是配置关注航线+日期明细集合中的指定航班子集" in TEXT
    assert "关注航班独立于关注航线" not in TEXT
    assert "关注航班 = 配置关注航线 + 同日期明细中的指定航班" in TEXT
