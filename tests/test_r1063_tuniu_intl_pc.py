# -*- coding: utf-8 -*-
"""r1063 T146：途牛「国际 PC」通路（模板来自用户实测截图）。

用户截图给出真实模板（与 domestic 对称）：
```
https://flight.tuniu.com/intl/list/SHA_SEL_1_0_0?deptDate=…&type=2&cabinClass=0&arrvDate=…
```
此前国际只有 H5/API 一条接口路（常吃 710114 登录门）。现在：
* `PC·国际` 是**独立通路**，单独进面板/账本；
* 抽取**不依赖固定 class**（先等 `.J-flightlist`，失败则通用扫描带 ¥ 的
  flight 容器），避免"猜 DOM"；
* 解析在 Python 侧做（可测）：价格 + 两个时刻 + 航司关键词；
* PC 拿不到行的日期再回退 H5/API，开关 `crawler.tuniu_intl_pc`（默认 true）。

真机实测（探针）：
```
PC·国际  empty   国际 PC 页无可用行（DOM 结构或风控）
H5/API   ok      国际列表接口        ← 回退生效并出数
```
"""
import io
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.tuniu import TuniuCrawler  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _c(cfg=None):
    return TuniuCrawler(cfg or {}, logging.getLogger("t"))


def test_intl_pc_url_one_way():
    url = TuniuCrawler.intl_pc_url("SHA", "SEL", "2026-11-10")
    assert url == ("https://flight.tuniu.com/intl/list/"
                   "SHA_SEL_1_0_0?deptDate=2026-11-10&type=1&cabinClass=0")


def test_intl_pc_url_round_trip_has_arrv():
    url = TuniuCrawler.intl_pc_url("SHA", "SEL", "2026-11-10", "2026-11-14")
    assert "type=2" in url and "arrvDate=2026-11-14" in url


def test_parse_intl_pc_items_extracts_price_and_times():
    c = _c()
    items = ["东航 MU5603 10:15 16:30 中转1次 ¥2253 往返含税价",
             "南航 11:40 20:50 8h10m ¥2563",
             "没有价格的噪音行"]
    rows = c._parse_intl_pc_items(items, "2026-11-10")
    # 形状与国内 `_parse_pc_items` 一致（dict），上层共用同一份转 FlightPrice 逻辑
    assert len(rows) == 2, rows
    assert rows[0]["price"] == 2253
    assert rows[0]["depTime"] == "10:15" and rows[0]["arrTime"] == "16:30"
    assert "东航" in rows[0]["name"]
    assert rows[0]["depDate"] == "2026-11-10"


def test_switch_default_on_and_can_be_off():
    assert _c()._intl_pc_enabled() is True
    assert _c({"tuniu_intl_pc": False})._intl_pc_enabled() is False


def test_fetch_prefers_pc_then_falls_back():
    src = io.open(os.path.join(ROOT, "crawlers", "tuniu.py"),
                  encoding="utf-8").read()
    i = src.index("if is_intl_route(from_city, to_city):")
    seg = src[i:i + 1600]
    assert "_fetch_intl_pc" in seg, "国际必须先走 PC 页"
    assert "remain" in seg and "_fetch_intl(" in seg, "缺的日期要回退 H5/API"


def test_path_label_is_independent_dimension():
    src = io.open(os.path.join(ROOT, "crawlers", "tuniu.py"),
                  encoding="utf-8").read()
    assert '"PC·国际"' in src, "国际 PC 必须作为独立通路进账本/面板"


def test_empty_page_is_retried():
    """国际页会间歇性整页空白（国内实测同一 URL 5 次里 3 次正常）。

    空页必须重载一次，否则一次抽风就白丢一天数据。
    """
    src = io.open(os.path.join(ROOT, "crawlers", "tuniu.py"),
                  encoding="utf-8").read()
    i = src.index("def _fetch_intl_pc")
    seg = src[i:i + 2600]
    assert "for _attempt in range(2)" in seg, "缺少空页重载重试"
    assert "PC 页空，重载重试" in seg
