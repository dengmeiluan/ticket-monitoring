# -*- coding: utf-8 -*-
"""r819：app_qunar 城市搜索行识别不能写死上海三字码 SHA。

2026-11-02 18:15 真机现场（debug/scene/..._timeout-arr.png）：搜索框已
输入「海口」，结果行「城市 海口 海南 中国 HAK」就在屏幕上，但
`_search_result_row()` 只认「不限机场」或字面量 `SHA`，于是永远不点
这一行，30 秒超时后记 `设到达城市失败：海口`。三亚/海口等非上海城市
全部中招；上海/新加坡能过是因为命中写死的 SHA 或「不限机场」。
"""
import os

from crawlers.app_qunar import _search_result_row


def _node(text, x1, y1, x2, y2):
    return ('<node text="%s" bounds="[%d,%d][%d,%d]" />'
            % (text, x1, y1, x2, y2))


def _xml(*nodes):
    return '<hierarchy rotation="0">%s</hierarchy>' % "".join(nodes)


def test_haikou_row_with_hak_is_clickable():
    xml = _xml(
        _node("城市", 24, 195, 75, 222),
        _node("海口 海南 中国 HAK", 87, 195, 500, 222),
    )
    row = _search_result_row(xml, "海口")
    assert row is not None
    assert row["text"].startswith("海口")


def test_city_and_code_in_separate_nodes_same_row():
    xml = _xml(
        _node("海口", 87, 195, 160, 222),
        _node("海南", 170, 195, 230, 222),
        _node("HAK", 300, 195, 360, 222),
    )
    row = _search_result_row(xml, "海口")
    assert row is not None
    assert row["text"] == "海口"


def test_unlimited_airport_row_still_works():
    xml = _xml(_node("上海（不限机场） 中国 SHA", 87, 195, 500, 222))
    row = _search_result_row(xml, "上海")
    assert row is not None
    assert "不限机场" in row["text"]


def test_plain_city_without_code_is_not_clicked():
    xml = _xml(_node("海口", 87, 195, 160, 222))
    assert _search_result_row(xml, "海口") is None


def test_source_has_no_hardcoded_sha_gate():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "crawlers", "app_qunar.py"),
               encoding="utf-8").read()
    start = src.index("def _search_result_row")
    body = src[start:start + 600]
    assert '"SHA" in t' not in body
    assert "[A-Z]{3}" in body
