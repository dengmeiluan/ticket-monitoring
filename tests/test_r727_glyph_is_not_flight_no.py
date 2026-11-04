# -*- coding: utf-8 -*-
"""r727 图标字形被当成航班号：CZ3516 被记成 `984839`。

真机 dump（2026-10-31，智行列表页）里图标写成 XML 数字实体：

    text="&#984839;" [135,1534][164,1564]     ← 底部「时间」排序图标
    text="&#984838;" [435,1549][464,1579]     ← 「价格」排序图标
    text="&#984837;" [735,1549][764,1579]     ← 「比价」图标

解析器从不还原实体，`text` 里留着字面量 `&#984839;`，于是：

1. 旧航班号正则 `[A-Z0-9]{2}\\d{3,4}` 在 `&#984839;` 里匹配到 `984839`
   —— 一个纯数字被当成航班号；
2. 它落在 CZ3516 那一卡的纵向窗口里（dy≈10），抢在真正的 `CZ3516`
   前面被取走（节点顺序靠前），于是那一班记成「984839 ¥2094」。

纯数字不可能是航班号（中国航班号至少含一位字母：CA8573 / 3U8888），
所以两处一起修：**先解码实体**，再要求航班号必须含字母。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers.app_zhixing_parse import (  # noqa: E402
    _nodes, _unescape, parse_flight_rows, detect_state,
)


def _card(code, airline, dep, arr, price, y):
    """一张国内航班卡片（几何取自真机 dump）。

    真机实测（list_0.xml）：时刻行 cy=1485，航司/航班号在**下方** cy=1539，
    即航班号比时刻低 ~54px；价格在右侧同一带。
    """
    return (
        '<node text="%s" resource-id="" class="android.widget.TextView" '
        'bounds="[54,%d][96,%d]" />'
        '<node text="%s" resource-id="" class="android.widget.TextView" '
        'bounds="[92,%d][155,%d]" />'
        '<node text="%s" resource-id="" class="android.widget.TextView" '
        'bounds="[92,%d][150,%d]" />'
        '<node text="%s" resource-id="" class="android.widget.TextView" '
        'bounds="[480,%d][540,%d]" />'
        '<node text="&#165;%d" resource-id="" class="android.widget.TextView" '
        'bounds="[770,%d][850,%d]" />'
        % (airline, y + 42, y + 64,
           code, y + 42, y + 64,
           dep, y, y + 24,
           arr, y, y + 24,
           price, y + 20, y + 50)
    )


def _page():
    body = (
        '<node text="上海" bounds="[24,180][80,210]" />'
        '<node text="海口" bounds="[820,180][876,210]" />'
        '<node text="时间" bounds="[120,1534][164,1564]" />'
        '<node text="&#984839;" bounds="[135,1534][164,1564]" />'
        '<node text="价格低-高" bounds="[415,1549][464,1579]" />'
        '<node text="&#984838;" bounds="[435,1549][464,1579]" />'
        '<node text="比价" bounds="[735,1549][764,1579]" />'
        '<node text="&#984837;" bounds="[735,1549][764,1579]" />'
    )
    return ("<hierarchy>"
            + _card("CA8573", "国航", "15:30", "18:55", 1734, 1250)
            + _card("CZ3516", "南航", "12:25", "16:05", 2094, 1500)
            + body + "</hierarchy>")


def test_entity_is_decoded_to_the_glyph():
    """数字实体要还原成字符，不能留字面量 `&#984839;`。"""
    assert _unescape("&#984839;") == chr(984839)
    assert _unescape("&amp;") == "&"
    assert _unescape("普通文本") == "普通文本"


def test_glyph_text_is_not_a_flight_number():
    texts = [n.text for n in _nodes(_page())]
    assert "984839" not in texts
    assert chr(984839) in texts, "图标字形没解码出来，说明实体还原没生效"


def test_flight_number_must_contain_a_letter():
    """底部工具栏图标不能被当成本页某个航班的航班号。"""
    rows = parse_flight_rows(_page())
    codes = [r["flight_no"] for r in rows]
    assert codes == ["CA8573", "CZ3516"], codes
    assert all(any(c.isalpha() for c in c) for c in codes if c), codes


def test_prices_still_attach_to_the_right_card():
    """负控：修实体不能把价格/时刻弄丢。"""
    rows = {r["flight_no"]: r for r in parse_flight_rows(_page())}
    assert rows["CA8573"]["price"] == 1734
    assert rows["CA8573"]["depart_time"] == "15:30"
    assert rows["CZ3516"]["price"] == 2094
    assert rows["CZ3516"]["depart_time"] == "12:25"


def test_numeric_only_text_in_card_is_not_a_flight_no():
    """卡片窗口里的 6 位纯数字不能被当成航班号。

    真机页面里除图标实体外还有大量数字（时长、里程、编号）。旧正则
    `[A-Z0-9]{2}\\d{3,4}` 会把 `202701` 整串吃下——「数字正好落在窗口里
    就变成航班号」。航班号至少含一位字母（CA8573 / 3U8888 / 9C8888），
    所以要求必须含字母。
    """
    xml = ("<hierarchy>"
           '<node text="12:25" bounds="[92,1485][150,1509]" />'
           '<node text="16:05" bounds="[480,1485][540,1509]" />'
           '<node text="202701" bounds="[92,1527][155,1549]" />'
           '<node text="&#165;2094" bounds="[770,1505][850,1535]" />'
           "</hierarchy>")
    rows = parse_flight_rows(xml)
    assert len(rows) == 1, rows
    assert rows[0]["flight_no"] == "", rows[0]["flight_no"]


def test_state_still_ok():
    assert detect_state(_page()) == "ok"


def test_real_device_dump_has_no_numeric_flight_no():
    """回归：真机 dump（8 行列表）里不应再出现纯数字航班号。

    该 fixture 是本轮抓到的真机页面；修复前最后一行是 `984839`。
    """
    path = os.path.join(ROOT, "tests", "fixtures", "zhixing_list_glyph.xml")
    assert os.path.exists(path), "真机 dump 样本缺失：%s" % path
    xml = io.open(path, encoding="utf-8").read()
    rows = parse_flight_rows(xml)
    assert len(rows) == 8, len(rows)
    codes = [r["flight_no"] for r in rows]
    assert "CZ3516" in codes, codes
    assert all(any(c.isalpha() for c in c) for c in codes), codes
