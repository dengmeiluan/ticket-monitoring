# -*- coding: utf-8 -*-
"""r805n：飞猪国际往返「有价可采」的实测证据，与国内「结构拒绝」的边界。

来由（2026-10-31 r805 实测，勿再重查）：
文档 INTL_DESIGN 的飞猪行原写「国际往返返回结构正确的行但当日 price=0」，
据此读者会以为「参数受理但拿不到价」。今天在**同一连接内交替取证**：

    SHA→TYO 去程 11-27 / 返程 12-01   tripType=1 → 7 天，每天带 backDate，
                                     当日 price=1479 + tax=768（含税 ¥2247）
    SHA→NRT 去程 11-27 / 返程 12-01   tripType=1 → 7 天，每天带 backDate
    同批 SHA→BJS 单程（正控）           → 出数 ¥400
    同批 SHA→BJS 往返 tripType=1        → 65B success:false

即：**国际往返有价、可采；国内往返是结构性拒绝**。而产品路径也真跑通过一次：
`FliggyCrawler.safe_fetch("SHA","TYO",["2026-11-27"], ret_date="2026-12-01")`
产出 1 行 ¥2247、path=`日历`、status=`calendar`。

判据（三层，全部可独立证伪）：
  1. 解析层：受理形态的往返行 → 出价 2247、backDate/tripType 回显；
  2. 证伪层：backDate 与请求不符、或往返行缺 backDate → 必须返回 None
     （防单程假冒往返，这是本项目反复强调的口径纪律）；
  3. 路由层：`_fetch_intl` 在 ret_date 在场时**不得**先跑 PC 明细列表
     （列表只有去程，会把单程价当往返总价）。
"""
import io
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers.fliggy import FliggyCrawler  # noqa: E402

RT_ROWS = [
    {"leaveDate": "2026-11-27", "backDate": "2026-12-01",
     "price": 1479.0, "tax": 768.0,
     "url": "//sijipiao.fliggy.com/ie/flight_search_result.htm?"
            "depCityCode=SHA&arrCityCode=TYO&tripType=1&"
            "depDate=2026-11-27&arrDate=2026-12-01"},
    {"leaveDate": "2026-11-28", "backDate": "2026-12-02",
     "price": 1509.0, "tax": 768.0, "url": ""},
]


def test_round_trip_row_yields_price_with_return_evidence():
    el = FliggyCrawler._parse_calendar_days(
        RT_ROWS, "2026-11-27", ret_date="2026-12-01",
        city_codes="SHA-TYO")
    assert el is not None, "受理形态的往返行被解析器丢掉了"
    assert el["price"] == 2247.0, el["price"]
    assert el["tax"] == 768.0
    assert el["backDate"] == "2026-12-01"
    assert el["tripType"] == "RT"
    # 深链也要体现往返口径（用户在界面点「查看」时落到往返页）
    assert "arrDate=2026-12-01" in el.get("view", "")
    assert "tripType=1" in el.get("view", "")


@pytest.mark.parametrize("bad_ret,rows,why", [
    ("2026-12-05", RT_ROWS, "回程日不符"),
    ("2026-12-01", [dict(RT_ROWS[0], backDate=None)], "往返行缺 backDate"),
])
def test_single_trip_price_cannot_masquerade_as_round_trip(
        bad_ret, rows, why):
    got = FliggyCrawler._parse_calendar_days(rows, "2026-11-27",
                                             ret_date=bad_ret)
    assert got is None, (
        "%s 时应拒绝该行，否则单程价会冒充往返总价（¥%s）"
        % (why, (got or {}).get("price")))


def test_intl_round_trip_skips_pc_list():
    """ret_date 在场时国际主路径不得先跑 PC 明细列表。

    PC 列表（sijipiao /ie/）只有去程一列；先跑它、拿它的最低价当往返，
    就会把 ¥1078 的单程价写成往返总价。代码里 `if not ret_date:` 是这条
    纪律的唯一闸门——改坏了不会报错，只会静默串味。
    """
    src = io.open(os.path.join(ROOT, "crawlers", "fliggy.py"),
                  encoding="utf-8").read()
    i = src.index("def _fetch_intl(")
    body = src[i:src.index("\n    def _fetch_intl_pc(", i)]
    gate = body.index("if not ret_date:")
    pc_call = body.index("self._fetch_intl_pc(")
    assert gate < pc_call, "PC 列表调用跑到了 ret_date 闸门之前"
    # 日历兜底必须收到 ret_date（否则它按单程拉）
    assert "ret_date)" in body, "日历兜底没把 ret_date 传下去"
