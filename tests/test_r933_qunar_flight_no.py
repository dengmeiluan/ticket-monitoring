# -*- coding: utf-8 -*-
"""r933：中转行没有航班号 + `11022` 被当成航班号。

现场（2026-11-04 `debug/scene/*_nopriced-*.txt`）：

     |  | flight_search_rn|QunarFlightInterList|FlightsRound_OD617|PVG-KUL
        |2026-11-16/OD528|KUL-DMK|2026-11-16 |  | 0,481,

两个问题叠在一起：

**① 中转行整条没有身份。**
航班号只在 `content-desc` 里，`text` 是空的；而 `_nodes()` 只收
「有文字的节点」，于是这条被过滤掉 → 入库 `flight_no=''`。
下游只看得到"这天有个 ¥4999"，看不出是哪一班。

**② 纯数字被误判成航班号。**
`_FLIGHT_RE = ([A-Z0-9]{2}\\d{3,4})` 会把价格 `11022` 匹配成
"11 + 022" → 入库 `flight_no='11022'`、`price=11022`。
一个看着像航班号的数字，其实是这一天的票价。

修法：
  1. 新增 `_desc_flight_marks()` —— 从 `content-desc` 的 `FlightsRound_` 段
     取航班号；两段（中转）用 `+` 连成 `OD617+OD528`；
  2. 卡片内 `code` 为空时用它兜底；
  3. `_FLIGHT_RE` 要求前缀**至少一个字母**，`11022` 不再匹配，
     而 `3U8889` / `9C7293` 这类真实航司码仍然认得出。

顺带确认：`trans_city` 的判据是页面上的「转 XX / 停 X 时」文案。现场那 7 条
虽然来自 `QunarFlightInterRoundMixList`（中转混合列表**组件**），但每段只有
一个航班号（无 `/` 第二段），所以**确实是直飞**，`trans` 为空是对的——
组件名叫 RoundMix 不代表里面每行都是中转。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r933_qunar_flight_no.py -q
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers.app_qunar_parse import (_desc_flight_marks,  # noqa: E402
                                      parse_flight_rows)


def _card(dep, price, y, arr="18:55", desc_round=None, code_text=""):
    """一张卡片：时刻 + 到达 + 价格（+ 可选的中转航班号 desc 节点）。"""
    parts = [
        '<node text="%s" content-desc="flight_search_rn|'
        'QunarFlightInterRoundMixList|ItemDepTime" '
        'bounds="[18,%d][80,%d]" />' % (dep, y, y + 33),
        '<node text="%s" content-desc="flight_search_rn|'
        'QunarFlightInterRoundMixList|ItemArrTime" '
        'bounds="[301,%d][366,%d]" />' % (arr, y, y + 33),
        '<node text="%s" content-desc="flight_search_rn|'
        'QunarFlightInterRoundMixList|ItemPrice" '
        'bounds="[662,%d][723,%d]" />' % (price, y, y + 33),
    ]
    if code_text:
        parts.append('<node text="%s" bounds="[36,%d][104,%d]" />'
                     % (code_text, y + 74, y + 97))
    if desc_round:
        parts.append('<node text="" content-desc="flight_search_rn|'
                     'QunarFlightInterList|FlightsRound_%s" '
                     'bounds="[0,%d][741,%d]" />' % (desc_round, y + 85,
                                                     y + 130))
    return "".join(parts)


# ---------------------------------------------------------------------------
# 1. desc 航班号提取
# ---------------------------------------------------------------------------
def test_desc_marks_direct_single_leg():
    xml = _card("15:40", "¥5031", 366, desc_round="MU3686|SHA-BKK|2026-11-16")
    marks = _desc_flight_marks(xml)
    assert len(marks) == 1
    assert marks[0][0] == "MU3686"


def test_desc_marks_transfer_two_legs_joined():
    """真中转：两段用 `+` 连起来，单程号会含糊"这到底是哪班"。"""
    xml = _card("20:55", "¥5711", 366,
                desc_round="OD617|PVG-KUL|2026-11-16/OD528|KUL-DMK|2026-11-16")
    marks = _desc_flight_marks(xml)
    assert marks and marks[0][0] == "OD617+OD528", marks


def test_desc_marks_ignores_non_flight_desc():
    xml = ('<node text="¥5711" content-desc="flight_search_rn'
           '|QunarFlightInterRoundMixList|ItemPrice" '
           'bounds="[662,366][723,399]" />')
    assert _desc_flight_marks(xml) == []


# ---------------------------------------------------------------------------
# 2. 纯数字不能当航班号（核心 bug）
# ---------------------------------------------------------------------------
def test_numeric_price_is_not_flight_no():
    """`11022` 是价格，不是「航班 11+022」。"""
    xml = _card("15:30", "¥11022", 366)
    rows = parse_flight_rows(xml)
    assert len(rows) == 1
    assert rows[0]["flight_no"] == "", rows[0]
    assert rows[0]["price"] == 11022


def test_real_airline_codes_still_work():
    """`3U8889` / `9C7293` 这类"数字开头"的真实航司码不能被误伤。"""
    for code in ("3U8889", "9C7293", "HO1234", "CZ8757"):
        xml = _card("08:00", "¥680", 366, code_text="川航" + code)
        rows = parse_flight_rows(xml)
        assert rows and rows[0]["flight_no"] == code, (code, rows)


# ---------------------------------------------------------------------------
# 3. 卡片内 code 为空时用 desc 兜底
# ---------------------------------------------------------------------------
def test_transfer_row_gets_code_from_desc():
    xml = _card("20:55", "¥5711", 366,
                desc_round="OD617|PVG-KUL|2026-11-16/OD528|KUL-DMK|2026-11-16")
    rows = parse_flight_rows(xml)
    assert len(rows) == 1
    assert rows[0]["flight_no"] == "OD617+OD528", rows


def test_text_code_wins_over_desc():
    """text 里有航班号时优先用它（desc 只是兜底）。"""
    xml = _card("15:40", "¥5031", 366, code_text="东航MU3686",
                desc_round="MU3686|SHA-BKK|2026-11-16")
    rows = parse_flight_rows(xml)
    assert rows[0]["flight_no"] == "MU3686"


# ---------------------------------------------------------------------------
# 4. 真实现场回归：7 行全部有航司码，且都不是纯数字
# ---------------------------------------------------------------------------
def test_real_scene_all_rows_have_airline_code():
    """2026-11-04 10:49 真实 SHA→HAK 现场：7 行，每行都有航司码。

    修前：`flight_no` 全空，甚至有一行是 `11022`（价格被当航班号）。
    """
    codes = ["MU3686", "MU3748", "CZ8757", "CZ3516", "CZ6686", "CZ6766",
             "CA8573"]
    prices = ["¥5031", "¥5031", "¥6591", "¥6591", "¥6591", "¥6591", "¥11022"]
    xml = "".join(
        _card("%02d:00" % (6 + i), p, 366 + i * 139,
              desc_round="%s|SHA-BKK|2026-11-16" % c)
        for i, (c, p) in enumerate(zip(codes, prices)))
    rows = parse_flight_rows(xml)
    assert len(rows) == 7
    got = [r["flight_no"] for r in rows]
    assert got == codes, got
    # 一行都不许是纯数字
    for c in got:
        assert not c.isdigit(), c


@pytest.mark.parametrize("bad", ["11022", "4999", "5711"])
def test_pure_digits_never_match(bad):
    from crawlers.app_qunar_parse import _FLIGHT_RE
    assert _FLIGHT_RE.search(bad) is None, bad
