# -*- coding: utf-8 -*-
"""r931：`¥` 前缀让整页价格被丢——中转混合列表「带价 0 行」的真因。

真实日志（2026-11-04，一天三次）：

    [app_qunar] 2026-11-16 列表 1 行、带价 0 行（再等一拍仍无可用价）
    [app_qunar] 2027-01-30 列表 1 行、带价 0 行（再等一拍仍无可用价）

现场落盘 `debug/scene/qunar_app_20261104_103351_nopriced-2026-11-16.txt`
里的节点长这样：

    | ¥5711 | flight_search_rn|QunarFlightInterRoundMixList|ItemPrice |  | 662,366,723,399
    | ¥4999 | flight_search_rn|QunarFlightInterRoundMixList|ItemPrice |  | 653,505,723,538
    | 20:55 | flight_search_rn|QunarFlightInterRoundMixList|ItemDepTime |  | 18,366,80,399

**价格全在**，而且带结构化 desc。但 `parse_flight_rows` 取 `ItemPrice`
时要求 text 是**纯 2–5 位数字**：

    if not re.fullmatch(r"\\d{2,5}", val):   # "¥5711" 不匹配 → 丢掉

于是国际中转混合列表（`QunarFlightInterRoundMixList`）整页价格被丢光，
上层只看到"有航班行、带价 0 行"，记 `no-priced-rows`。

修法：先剥掉货币符号与千分位，再校验位数。

用**真实现场**跑同一份 dump：

    修前：解析 6 行、带价 0 行
    修后：解析 6 行、带价 6 行（¥5711 / ¥4999 / ¥5455 / ¥5465 / ¥8418 / ¥8418）

> 顺带记一笔踩坑：现场文本格式是 `| text | desc | desc2 | bounds`，
> 而 **desc 自身含 `|`**（`flight_search_rn|Qunar...|ItemPrice`）。
> 按 `split("|")` 取列会把 desc 切碎，必须先用正则剥掉尾部 bounds 再拼回。
> 我第一版诊断脚本就栽在这，误判成"价格取不到"。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r931_qunar_yuan_price.py -q
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers.app_qunar_parse import parse_flight_rows  # noqa: E402


def _card(dep, price, y, arr="00:45"):
    """造一张中转混合列表卡片。

    真实结构（现场 2026-11-04 10:33，同一排三个节点，y 相同）：
        ItemDepTime  x=18   20:55
        ItemArrTime  x=301  00:45
        ItemPrice    x=662  ¥5711
    解析器以"左半屏时刻 + 同排右侧时刻"为锚配成一行，所以**到达时刻必须有**。
    """
    return ('<node text="%s" content-desc="flight_search_rn|'
            'QunarFlightInterRoundMixList|ItemDepTime" '
            'bounds="[18,%d][80,%d]" />'
            '<node text="%s" content-desc="flight_search_rn|'
            'QunarFlightInterRoundMixList|ItemArrTime" '
            'bounds="[301,%d][366,%d]" />'
            '<node text="%s" content-desc="flight_search_rn|'
            'QunarFlightInterRoundMixList|ItemPrice" '
            'bounds="[662,%d][723,%d]" />'
            % (dep, y, y + 33, arr, y, y + 33, price, y, y + 33))


def _xml(*cards):
    return "".join(cards)


# ---------------------------------------------------------------------------
# 1. 核心修复：带 ¥ 的价格必须能取到
# ---------------------------------------------------------------------------
def test_yen_prefixed_price_is_parsed():
    xml = _xml(_card("20:55", "¥5711", 366), _card("03:55", "¥4999", 505))
    rows = parse_flight_rows(xml)
    prices = sorted(r["price"] for r in rows if r.get("price"))
    assert prices == [4999, 5711], rows


def test_fullwidth_yen_and_thousands_sep():
    xml = _xml(_card("10:45", "￥1,234", 366))
    rows = parse_flight_rows(xml)
    assert [r["price"] for r in rows if r.get("price")] == [1234]


def test_plain_number_still_works():
    """老形态（纯数字）不能因为这次改动而回归。"""
    xml = _xml(_card("13:10", "3305", 366))
    rows = parse_flight_rows(xml)
    assert [r["price"] for r in rows if r.get("price")] == [3305]


def test_price_none_when_absent():
    """没有价格的卡片仍给 price=None（绝不给 0）。"""
    xml = ('<node text="07:00" content-desc="flight_search_rn|'
           'QunarFlightInterRoundMixList|ItemDepTime" '
           'bounds="[18,366][80,399]" />')
    rows = parse_flight_rows(xml)
    assert rows == [] or all(r.get("price") is None for r in rows)


# ---------------------------------------------------------------------------
# 2. 不应该被误当成价格的东西
# ---------------------------------------------------------------------------
def test_too_many_digits_rejected():
    """位数超范围（如 6 位）不是票价。"""
    xml = _xml(_card("09:00", "¥123456", 366))
    rows = parse_flight_rows(xml)
    assert all(r.get("price") != 123456 for r in rows)


def test_discount_tag_not_price():
    """「已减 ¥70」是优惠标签，不是票价（既有判据不能被破坏）。"""
    xml = ('<node text="08:00" content-desc="flight_search_rn|'
           'QunarFlightInterRoundMixList|ItemDepTime" '
           'bounds="[18,366][80,399]" />'
           '<node text="¥" bounds="[1560,370][1570,395]" />'
           '<node text="已减" bounds="[1580,372][1620,394]" />'
           '<node text="70" bounds="[1625,370][1655,395]" />')
    rows = parse_flight_rows(xml)
    assert all(r.get("price") != 70 for r in rows), rows


# ---------------------------------------------------------------------------
# 3. 真实现场回归（一份 dump = 6 张卡片 6 个价）
# ---------------------------------------------------------------------------
def test_real_scene_six_prices():
    """2026-11-04 10:33 真实 SHA→BKK 现场：6 行，六个价全在。

    修前这份 dump 解析出「6 行、带价 0 行」→ 上层记 no-priced-rows。
    """
    cards = [_card("20:55", "¥5711", 366),
             _card("03:55", "¥4999", 505),
             _card("13:10", "¥5455", 645),
             _card("10:45", "¥5465", 784),
             _card("16:10", "¥8418", 923),
             _card("17:35", "¥8418", 1062)]
    rows = parse_flight_rows(_xml(*cards))
    priced = [r for r in rows if r.get("price")]
    assert len(priced) == 6, [r.get("price") for r in rows]
    assert sorted(r["price"] for r in priced) == [4999, 5455, 5465, 5711,
                                                 8418, 8418]


# ---------------------------------------------------------------------------
# 4. 源码钉：不许退回「只认纯数字」
# ---------------------------------------------------------------------------
def test_source_accepts_currency_prefix():
    import io
    src = io.open(os.path.join(ROOT, "crawlers", "app_qunar_parse.py"),
                  encoding="utf-8").read()
    assert '[¥￥$' in src or "\u00a5" in src, "没剥货币符号"
    assert "QunarFlightInterRoundMixList" in src, "没记录中转混合列表这条现场"
