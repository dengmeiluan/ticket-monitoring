# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r819_app_qunar_search_row.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import os

from crawlers.app_qunar import _search_result_row


# ---- merged from tests/test_r819_app_qunar_search_row.py ----

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
