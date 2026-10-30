# -*- coding: utf-8 -*-
"""r254 渠道案：同程改期日历高档舱最低价 pc[].hlp（trendBiz 三端接入）。

hlp 与已采 pc[].lp（trendGo 载体）同槽兄弟键，语义经同报文
lowPrice.inHighCabin 三点全等实锤（同值/同航班/同折扣词面锚
「5.2折公务舱」）——r204 时代「语义未证不采」的排除依据被推翻
（白名单排除依据复验判例）。信息增量：行级 bizPrice 只承载查询日、
trendGo 只承载经济舱，「改期那天公务舱最低多少」无既有出口。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r254_fields.py
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from crawlers.tongcheng import TongchengCrawler  # noqa: E402


def _fl(lo_atp=1800, hi_atp=2200):
    return [{"fn": "9C8846", "dt": "2026-10-06 16:40", "at": "2026-10-06 21:30",
             "atp": hi_atp, "lps": [{"atp": hi_atp, "brs": [{"al": 3}]}]},
            {"fn": "CZ6981", "dt": "2026-10-06 08:00", "at": "2026-10-06 12:00",
             "atp": lo_atp, "lps": [{"atp": lo_atp, "brs": [{"al": 3}]}]}]


def test_tongcheng_trendbiz_mounts_on_lowest():
    """hlp 与 lp 同槽同循环提取，落 trendBiz 挂当轮最低价行（trendGo
    同律逐行重复=extra 膨胀）；[[MM-DD,价],…] 形态同协议。"""
    pc = [{"dd": "2026-09-29", "lp": 750, "hlp": 2350},
          {"dd": "2026-10-06", "lp": 1800, "hlp": 5100}]
    rows = TongchengCrawler._extract_flights(json.dumps(
        {"data": {"fl": _fl(), "pc": pc}}))
    lo = min(rows, key=lambda f: f["price"])
    assert lo["trendGo"] == [["09-29", 750], ["10-06", 1800]]
    assert lo["trendBiz"] == [["09-29", 2350], ["10-06", 5100]]
    hi = next(r for r in rows if r["code"] == "9C8846")
    assert "trendBiz" not in hi


def test_tongcheng_trendbiz_bad_points_dropped():
    """hlp 逐点同门守卫（价域 100-50000、非数/缺失弃）：坏点逐点弃，
    lp 好点照常落 trendGo；全坏点不落键（空列表不占位）。"""
    pc = [{"dd": "2026-09-29", "lp": 750, "hlp": 99},        # 价越界
          {"dd": "2026-10-01", "lp": 800, "hlp": "abc"},      # 非数
          {"dd": "2026-10-02", "lp": 900},                    # 缺 hlp
          {"dd": "2026-10-03", "lp": 950, "hlp": 60000}]      # 价越界上缘
    rows = TongchengCrawler._extract_flights(json.dumps(
        {"data": {"fl": _fl(), "pc": pc}}))
    lo = min(rows, key=lambda f: f["price"])
    assert lo["trendGo"] == [["09-29", 750], ["10-01", 800],
                             ["10-02", 900], ["10-03", 950]]
    assert "trendBiz" not in lo
    # 好点混排：好 hlp 照落、坏点同点弃
    pc2 = [{"dd": "2026-09-29", "lp": 750, "hlp": 2350},
           {"dd": "2026-10-01", "lp": 800}]
    rows2 = TongchengCrawler._extract_flights(json.dumps(
        {"data": {"fl": _fl(), "pc": pc2}}))
    lo2 = min(rows2, key=lambda f: f["price"])
    assert lo2["trendBiz"] == [["09-29", 2350]]


def test_tongcheng_trendbiz_real_dump_shape():
    """10-05 代真实 dump 形态（三点全等实锤样本）：pc[0] dd=2026-10-06
    hlp=5100 配 lp=2250——值落 DB bizPrice 带互证量级。"""
    pc = [{"dd": "2026-10-06", "lp": 2250, "hlp": 5100, "hms": "HO2290..."},
          {"dd": "2026-10-07", "lp": 1625, "hlp": 2895}]
    rows = TongchengCrawler._extract_flights(json.dumps(
        {"data": {"fl": _fl(2250, 2600), "pc": pc}}))
    lo = min(rows, key=lambda f: f["price"])
    assert lo["trendBiz"] == [["10-06", 5100], ["10-07", 2895]]


# ---- D3: flight_no 列词面归一（双名前缀剥离——最低价行 name 带营销
#      双名「新海航｜天津航空GS6478」塞进 flight_no 槽，与 ctrip/tuniu/
#      fliggy 裸号口径不一；对账列回归裸号，extra.code 本就裸号） ----

def test_qunar_flight_no_bare_code(monkeypatch):
    """qunar flight_no 落最低价行 code（裸号）而非 name（双名前缀）。"""
    import logging
    from crawlers.qunar import QunarCrawler
    c = QunarCrawler({}, logging.getLogger("t254"))
    flights = [{"code": "GS6478", "name": "新海航｜天津航空GS6478",
                "price": 900.0, "depTime": "08:00", "arrTime": "12:00"},
               {"code": "9C8866", "name": "春秋航空9C8866",
                "price": 619.0, "depTime": "19:00", "arrTime": "23:40"}]
    monkeypatch.setattr(c, "_fetch_one", lambda a, b, d: (619.0, flights))
    rows = c._fetch_inner("乌鲁木齐", "上海", ["2026-10-15"])
    assert rows and rows[0].flight_no == "9C8866"
    assert rows[0].depart_time == "19:00"


def test_tongcheng_flight_no_bare_code(monkeypatch):
    """tongcheng flight_no 同律落 code 裸号（browser 链 mock 全路径）。"""
    import contextlib
    import logging
    from unittest.mock import MagicMock
    c = TongchengCrawler({}, logging.getLogger("t254"))
    book1 = {"data": {"lp": 700, "fl": [
        {"fn": "GS7587", "asn": "天津航空", "dt": "2026-10-15 07:30",
         "at": "2026-10-15 11:50", "atp": 780,
         "lps": [{"atp": 780, "brs": [{"al": 3}]}]},
        {"fn": "CZ6993", "asn": "南航", "dt": "2026-10-15 12:00",
         "at": "2026-10-15 16:20", "atp": 700,
         "lps": [{"atp": 700, "brs": [{"al": 5}]}]}]}}
    monkeypatch.setattr(c, "browser",
                        lambda: contextlib.nullcontext(MagicMock()))
    monkeypatch.setattr(c, "attach_xhr_collector",
                        lambda page, keys: [
                            {"url": "https://x/book1/flights?d=1",
                             "text": json.dumps(book1)}])
    monkeypatch.setattr(c, "_pick_lowest", lambda captured, page: 700.0)
    monkeypatch.setattr(c, "_bag_fc_from_captured", lambda captured: "")
    monkeypatch.setattr(c, "_sleep", lambda: None)
    monkeypatch.setattr(c, "_dump_xhr", lambda captured, name: None)
    rows = c.fetch("乌鲁木齐", "上海", ["2026-10-15"])
    assert rows and rows[0].flight_no == "CZ6993"


# ---- webui 三端接线（源码钉，trendGo/trendHoliday 同款透传形态） ----

def test_webui_trendbiz_whitelist_passthrough():
    """/api/state 汇聚白名单原样透传 trendBiz（trendGo 同款 f.get
    形态，原样透传不做整形）。"""
    import webui
    src = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert '"trendBiz": f.get("trendBiz")' in src
    assert webui  # import 级验证（三.3）


def test_webui_trendbiz_render_gate():
    """渲染门：改期窗口柱图 title 附高档舱注（「公务￥X」词面，
    biz 日期映射与 hol 同构）+ CSV「改期公务」列对称「改期最低」。"""
    src = open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    assert 'f.trendBiz||[]' in src           # tgrowHtml biz 映射构造
    assert '公务￥' in src                    # 柱 title 附注词面
    assert '改期公务' in src                  # CSV 表头列
