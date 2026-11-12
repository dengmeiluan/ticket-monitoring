# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r659_app_extra_is_flight_array.py
- tests/test_r918_warmup_timing.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import json
import logging
import os
import sys
import time

from crawlers.app_zhixing import AppZhixingCrawler
from crawlers.base import BaseCrawler


# ---- merged from tests/test_r659_app_extra_is_flight_array.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _crawler():
    c = AppZhixingCrawler.__new__(AppZhixingCrawler)
    c.name = "app_zhixing"
    return c


def test_detail_extra_is_array_of_flights():
    c = _crawler()
    rows = [{"flight_no": "CZ8212", "depart_time": "20:25",
             "arrive_time": "23:10", "price": 349.0}]
    out = c._to_prices(rows, "SHA", "CAN", "2026-12-05")
    assert len(out) == 1, "一渠道一日期只应产出一行（消费端按此去重）"
    obj = json.loads(out[0].extra)
    assert isinstance(obj, list), "extra 必须是数组，实际 %r" % type(obj)
    assert obj and isinstance(obj[0], dict)
    assert obj[0]["price"] == 349.0
    assert obj[0]["code"] == "CZ8212"
    assert obj[0]["depTime"] == "20:25" and obj[0]["arrTime"] == "23:10"


def test_one_row_carries_all_flights_of_that_date():
    """同日期多班合成一行：分开写会被 (platform, 航线, 日期) 去重丢掉。"""
    c = _crawler()
    rows = [{"flight_no": "CZ8212", "depart_time": "20:25",
             "arrive_time": "23:10", "price": 349.0},
            {"flight_no": "MU5317", "depart_time": "13:35",
             "arrive_time": "23:05", "price": 360.0}]
    out = c._to_prices(rows, "SHA", "CAN", "2026-12-05")
    assert len(out) == 1
    obj = json.loads(out[0].extra)
    assert len(obj) == 2, "两班必须都在 extra 里：%s" % obj
    assert out[0].price == 349.0, "行头价应是最低价"
    assert out[0].flight_no == "CZ8212", "行头航班号应跟随最低价那班"


def test_calendar_extra_is_array_too():
    """日历价同样要能进列表池：写成对象时整页只剩明细、日历全消失。"""
    from crawlers.app_zhixing import _cal_extra
    obj = json.loads(_cal_extra(450.0, "2026-11-07"))
    assert isinstance(obj, list) and obj
    assert obj[0]["price"] == 450.0
    assert obj[0]["calendar"] is True
    assert not obj[0]["depTime"], "日历行不得伪造时刻"


def test_produced_rows_are_visible_to_list_pool():
    """端到端形状检查：产出必须能被 webui 的列表池收集器吃下。

    只断言爬虫产出形状不够——真正丢数据的是读取侧的类型门。这里直接
    复现读取侧的两个判据（webui 与 alerter 同款），任一处不满足即失败。
    """
    c = _crawler()
    out = c._to_prices([{"flight_no": "CZ8212", "depart_time": "20:25",
                         "arrive_time": "23:10", "price": 349.0}],
                       "SHA", "CAN", "2026-12-05")
    obj = json.loads(out[0].extra)
    # webui._user_state: if not isinstance(obj, list): continue
    assert isinstance(obj, list)
    # 其后的 real_items 判据：code/depTime/arrTime 三者齐备
    real = [x for x in obj if isinstance(x, dict)
            and str(x.get("code") or "").strip()
            and str(x.get("depTime") or "").strip()
            and str(x.get("arrTime") or "").strip()]
    assert real, "列表池会把它当『日历薄行』，明细整片消失"
    # Alerter._build_sections 走同一形状 + 要求 price 键
    assert all("price" in x for x in obj)


# ---- merged from tests/test_r918_warmup_timing.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_LOG = logging.getLogger("test_r918")


class _Ctx:
    """按时间线返回 cookie 的假上下文（模拟服务端"过一会儿才下发"）。"""

    def __init__(self, timeline):
        # timeline: [(at_seconds, [names...]), ...]
        self.timeline = list(timeline)
        self.t0 = time.time()

    def cookies(self):
        now = time.time() - self.t0
        out = []
        for at, names in self.timeline:
            if now >= at:
                out.extend({"name": n, "value": "1"} for n in names)
        return out


class _C(BaseCrawler):
    name = "ctrip"
    RISK_COOKIES = ("cticket", "_bfa", "MKT_CKID")


def _c(raw=("cticket", "_bfa", "MKT_CKID")):
    c = _C({}, _LOG)
    c.RISK_COOKIES = raw
    return c


# ---------------------------------------------------------------------------
# 1. wait_risk_cookies
# ---------------------------------------------------------------------------
def test_returns_immediately_when_already_present():
    c = _c()
    ctx = _Ctx([(0.0, ["cticket", "_bfa"])])
    t0 = time.time()
    hit = c.wait_risk_cookies(ctx, timeout_s=5.0)
    elapsed = time.time() - t0
    assert set(hit) == {"cticket", "_bfa"}
    assert elapsed < 0.5, "cookie 已在场时不该等满超时（实测 %.2fs）" % elapsed


def test_waits_until_cookie_lands():
    c = _c()
    ctx = _Ctx([(0.4, ["cticket"])])
    t0 = time.time()
    hit = c.wait_risk_cookies(ctx, timeout_s=6.0, poll_s=0.1)
    elapsed = time.time() - t0
    assert hit == ["cticket"]
    assert 0.3 <= elapsed < 3.0, elapsed


def test_returns_empty_on_timeout():
    c = _c()
    ctx = _Ctx([])                     # 永远不下发
    t0 = time.time()
    hit = c.wait_risk_cookies(ctx, timeout_s=0.5, poll_s=0.1)
    elapsed = time.time() - t0
    assert hit == []
    assert elapsed >= 0.4


def test_no_declared_cookies_is_a_noop():
    c = _c(raw=())
    ctx = _Ctx([(0.0, ["cticket"])])
    t0 = time.time()
    assert c.wait_risk_cookies(ctx, timeout_s=5.0) == []
    assert time.time() - t0 < 0.2      # 没声明就不该等


def test_cookies_raising_is_fail_soft():
    c = _c()

    class _Bad:
        def cookies(self):
            raise RuntimeError("context closed")
    t0 = time.time()
    assert c.wait_risk_cookies(_Bad(), timeout_s=0.4, poll_s=0.1) == []
    assert time.time() - t0 >= 0.3     # 等满超时，不抛异常


# ---------------------------------------------------------------------------
# 2. 日历记账：预热没落下 cookie → soft_reject，不是 empty
# ---------------------------------------------------------------------------
def test_calendar_without_warm_cookie_is_soft_reject_not_empty():
    """把决策逻辑单独抽出来验证（不启动浏览器）。

    与 ctrip._fetch_intl_calendar 里那段 if 完全同构：
        ``if _cal_status == "empty" and not warm_ok: status = soft_reject``
    """

    def _status(_cal_status, warm_ok):
        if _cal_status == "empty" and not warm_ok:
            return ("soft_reject", "预热未落下风控 cookie，按软拒记")
        return (_cal_status,
                "登录/验证页，非空结果" if _cal_status != "empty"
                else "国际日历未返回该日报价")

    assert _status("empty", False)[0] == "soft_reject"
    assert _status("empty", True)[0] == "empty"
    assert _status("login", False)[0] == "login"
    assert _status("blocked", False)[0] == "blocked"
