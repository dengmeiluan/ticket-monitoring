# -*- coding: utf-8 -*-
"""多程 CSV：表头/真实历史点/最新行 legs/公式注入转义（真浏览器求值）。"""
from entry_mon_harness import page, srv, _goto  # noqa: F401


SAMPLE = {
    "label": "SHA→TYO→OSA",
    "from": "SHA", "to": "OSA",
    "segments": [
        {"from": "SHA", "to": "TYO", "date": "2026-11-20"},
        {"from": "TYO", "to": "OSA", "date": "2026-11-23"}],
    "threshold": 1500,
    "latest": {"price": 1180, "platform": "ctrip",
               "fetched_at": "2026-11-03 11:00:00",
               "legs": [{"flight_no": "9C8515", "dep": "21:10",
                         "arr": "01:05"},
                        {"flight_no": "MM304", "dep": "07:30",
                         "arr": "09:10"}]},
    "history": [["2026-11-03T08:00:00", 1398],
                ["2026-11-03T11:00:00", 1180]],
}


OPEN_JAW = {
    "segments": [
        {"from": "SHA", "to": "TYO", "date": "2026-11-20"},
        {"from": "OSA", "to": "SHA", "date": "2026-11-26"}]}


def test_mc_chain_shows_open_jaw_discontinuity(page):
    """开口程不能画成 SHA→TYO→SHA：第二段从 OSA 出发，链上要断开。"""
    _goto(page)
    assert page.evaluate("r => _mcChain(r)", OPEN_JAW) == \
        "SHA→TYO / OSA→SHA"
    assert page.evaluate("r => _mcNames(r)", OPEN_JAW) == \
        "SHA→东京 / 大阪→SHA"


def test_mc_csv_rows_and_formula_guard(page):
    _goto(page)
    rows = page.evaluate("m => mcCsvRows(m)", SAMPLE)
    assert rows[0] == ["route", "segments", "total_price", "threshold",
                       "platform", "fetched_at", "legs"]
    assert rows[1][0] == "SHA→TYO→OSA"
    assert rows[1][1] == "SHA-TYO@2026-11-20|TYO-OSA@2026-11-23"
    assert rows[1][2] == 1398 and rows[1][6] == ""
    assert rows[2][2] == 1180 and "9C8515" in rows[2][6]
    assert page.evaluate("s => _csvCell(s)", "=1+1") == "'=1+1"
    assert page.evaluate("s => _csvCell(s)", 'a,"b"') == '"a,""b"""'


def test_mc_export_downloads_real_csv(page):
    """导出按钮必须真产生可读 CSV（不是只拼字符串）。"""
    _goto(page)
    with page.expect_download() as dl:
        page.evaluate(
            "m => { S.users[U].mcRoutes = [m]; mcExport(0); }", SAMPLE)
    path = dl.value.path()
    text = open(path, encoding="utf-8-sig").read()
    lines = text.splitlines()
    assert lines[0] == ("route,segments,total_price,threshold,platform,"
                        "fetched_at,legs")
    assert len(lines) == 3
    assert "SHA→TYO→OSA" in lines[1] and "1398" in lines[1]
    assert "1180" in lines[2] and "9C8515" in lines[2]
