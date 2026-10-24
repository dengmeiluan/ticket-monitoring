# -*- coding: utf-8 -*-
"""r326 R15 往返（tripType）一期契约钉（INTL_DESIGN §2.6 定稿落地）。

- Route 可选单键 ret_date（缺省=单程，存量零兼容负担）；
- base.safe_fetch 透传 ret_date（统一签名扩展，存量覆写零破坏）；
- 飞猪/同程日历通道 RT 参数与解析（元素 backDate/tripType=RT，
  price=往返总价含税）；
- UI「🔁 往返」徽标 + 回程日期配置槽（源码钉）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_intl_rt.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui  # noqa: E402
from core.models import Route  # noqa: E402
from crawlers.base import BaseCrawler  # noqa: E402
from crawlers.fliggy import FliggyCrawler  # noqa: E402
from crawlers.tongcheng import TongchengCrawler  # noqa: E402

_LOG = logging.getLogger("t_intl_rt")
_FG = FliggyCrawler({}, _LOG)
_TC = TongchengCrawler({}, _LOG)


# ---------- Route 契约 ----------

def test_route_ret_date_default_empty():
    r = Route(from_code="SHA", from_name="上海", to_code="TYO",
              to_name="东京", dates=["2026-11-16"])
    assert r.ret_date == ""          # 缺省单程（存量零兼容负担）


def test_route_ret_date_roundtrip():
    r = Route(from_code="SHA", from_name="上海", to_code="TYO",
              to_name="东京", dates=["2026-11-16"], ret_date="2026-11-20")
    assert r.ret_date == "2026-11-20"


def test_build_routes_passes_ret_date():
    import main
    routes = main.build_routes([{
        "from": "SHA", "from_name": "上海", "to": "TYO",
        "to_name": "东京", "dates": ["2026-11-16"],
        "alert_direct": 2500, "ret_date": "2026-11-20"}])
    assert routes[0].ret_date == "2026-11-20"
    # 缺省路径：不填 ret_date → 空串（单程）
    routes2 = main.build_routes([{
        "from": "SHA", "from_name": "上海", "to": "TYO",
        "to_name": "东京", "dates": ["2026-11-16"]}])
    assert routes2[0].ret_date == ""


# ---------- base 签名透传 ----------

def test_safe_fetch_passes_ret_date():
    seen = {}

    class _Probe(BaseCrawler):
        name = "probe"

        def fetch(self, from_city, to_city, dates, ret_date=""):
            seen["ret_date"] = ret_date
            return []

    p = _Probe({}, _LOG)
    p.safe_fetch("SHA", "TYO", ["2026-11-16"], ret_date="2026-11-20")
    assert seen["ret_date"] == "2026-11-20"
    # 缺省路径（存量调用点零破坏）
    p.safe_fetch("SHA", "TYO", ["2026-11-16"])
    assert seen["ret_date"] == ""


# ---------- 飞猪 RT ----------

def test_fliggy_calendar_params_rt():
    # 单程：tripType=0 无 backDate（现状逐字节不变锚）
    p_ow = _FG._calendar_params("SHA", "TYO", "2026-11-16")
    assert p_ow["tripType"] == 0 and "backDate" not in p_ow
    # 往返：tripType=1 + backDate（调研 §5/校准 R13 实证形态）
    p_rt = _FG._calendar_params("SHA", "TYO", "2026-11-16",
                                ret_date="2026-11-20")
    assert p_rt["tripType"] == 1
    assert p_rt["backDate"] == "2026-11-20"


def test_fliggy_rt_row_parse_and_element():
    # 真报文形态：RT 行带 backDate，price/tax=往返总价拆分
    # （fixture 已入库 tests/fixtures/——原引 _scratch/ 是 gitignore
    # 排除目录，CI fresh clone 必 FileNotFoundError）
    days = json.load(open(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "fixtures", "r13_fliggy_rt.json"), encoding="utf-8"))
    e = _FG._parse_calendar_days(days, "2026-11-16",
                                 ret_date="2026-11-20")
    assert e["price"] == 771.0 + 1550.0      # 往返总价含税
    assert e["tax"] == 1550.0
    assert e["backDate"] == "2026-11-20"
    assert e["tripType"] == "RT"
    assert e["intl"] == 1
    # 结构化占位键（校准 R22 定谳）：日历行结构性无时刻——下游推送行
    # 构造器硬键 f['depTime'] 需 key 安全（缺键曾炸整轮 digest）
    assert e["depTime"] == "" and e["arrTime"] == ""
    # 回程日不符的行不冒认（往返对唯一性）
    assert _FG._parse_calendar_days(days, "2026-11-16",
                                    ret_date="2026-11-21") is None
    # 渠道 RT 感知深链捕获（R28 深链复议）：url 字段→element view
    # （_view_url 恒单程形态，往返行点开单程页=所见非所点）
    assert "view" in e and e["view"].startswith("https://")
    assert "tripType=1" in e["view"] and "arrDate=2026-11-20" in e["view"]
    # 单程路径不受影响（无 backDate/tripType 键）
    e_ow = _FG._parse_calendar_days(
        [{"leaveDate": "2026-11-16", "price": 929.0, "tax": 70.0}],
        "2026-11-16")
    assert e_ow["price"] == 999.0
    assert "backDate" not in e_ow and "tripType" not in e_ow


# ---------- 同程 RT ----------

def test_tongcheng_calendar_url_rt():
    u_ow = _TC._calendar_url("SHA", "TYO", "2026-11-16")
    assert "TT=OW" in u_ow and "AD=1900-01-01" in u_ow
    u_rt = _TC._calendar_url("SHA", "TYO", "2026-11-16",
                             ret_date="2026-11-20")
    assert "TT=RT" in u_rt and "AD=2026-11-20" in u_rt


def test_tongcheng_rt_element():
    body = json.dumps({"data": {"RD": [
        {"DD": "2026-11-16", "RD": "2026-11-20", "P": 800, "TP": 2400,
         "ext": {"segments": [{"no": "MU1"}]}}]}})
    # RT 请求下四元组扩展（price, tax, transfer, backDate）——
    # 单程调用方三元组形态不变（test_intl_tongcheng 同钉）
    price, tax, transfer, back = TongchengCrawler._parse_intl_calendar(
        body, "2026-11-16", ret_date="2026-11-20")
    assert (price, tax, transfer, back) == (2400.0, 1600.0, True,
                                            "2026-11-20")
    # 回程日不符的行不冒认（往返对唯一性）
    assert TongchengCrawler._parse_intl_calendar(
        body, "2026-11-16", ret_date="2026-11-21") is None


# ---------- UI 源码钉 ----------

def test_push_link_prefers_element_rt_view():
    # R30 深链收口源码钉：推送行两处主包装点（KPI/summary）元素自带
    # RT 感知深链优先（_build_view_url 恒单程形态兜底）
    import core.alerter as _al
    src = open(_al.__file__, encoding="utf-8").read()
    assert src.count('str(best.get("view") or "").strip()') == 2,         "推送行 RT 深链优先点应恰 2 处（slim/KPI 主包装点）"


def test_webui_round_trip_badge_and_field():
    src = webui.PAGE
    # 行头「🔁 往返」徽标：返程日在场即亮（_rds 归一双键读取，
    # ×N 角标随 syncRouteHead 徽标族刷新）
    assert 'class="rrt"' in src
    assert "syncRouteHead" in src and "_rdsLen" in src
    # 配置槽：返程日期 chips 行（toggleRT 开合，ret_dates 主键；
    # legacy ret_date 读取兼容保留）
    assert "ret_dates" in src and "返程日期" in src


def test_webui_payload_passes_ret_date():
    mod = open(webui.__file__, encoding="utf-8").read()
    # 配置往返保存键在 setRoute 白名单（保存即热生效同律）
    assert "'ret_date'" in mod or '"ret_date"' in mod
