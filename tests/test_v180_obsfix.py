# -*- coding: utf-8 -*-
"""v1.5.80 观测修复批（audit_v180_obs P1-1/P2-1/P2-4/P2-7/P2-8）。

P1-1 并桶分歧收口：生产最小轮间隔实测 483-503s，600s 轮界把 ~8 分钟
相邻轮并桶（曲线取桶内 min、列表 dedupe 取最新行）→ 313 桶 6 桶分歧
（1.9%，幅度 ≤￥253）。轮界收窄 420s（< 483 实测最小值，同改 webui
列表与 report 曲线两端——两套阈值曾 300/600 并存致「图有列无」，
历史教训必须同轮同值）。
P2-4 qunar stopCitys 脏值：normalize split(';')[0] 取到空段丢
stopCity（';庆阳' 12 行/48h）→ 取首个非空段。
P2-8 ctrip labels 渠道侧重复拼接（aset 同词重复 append 2,126 行/48h）
→ 组装去重。
P2-8 qunar transferService 前缀重复（'中转优享:中转优享：…'）→
 tsl 以 tsn 开头时不再重复前缀。
P2-7 停用航线（enabled:false）仍进 routesArr 且作为 routes[0] 使
state 顶层 history 恒空 → _user_state 过滤（与日报 _chart_routes
已滤停用对齐）。
"""

import json

from webui import _cluster_round_rows


def _row(t):
    return {"platform": "ctrip", "from_city": "URC", "to_city": "SHA",
            "depart_date": "2026-10-05", "price": 2000.0,
            "extra": "", "fetched_at": t}


# ---- P1-1 轮界 420s ----

def test_round_gap_default_dplits_8min():
    """默认轮界 420s：8 分钟（480s）断口切轮——生产实测最小轮间隔
    483-503s，600s 阈值曾把这类相邻轮并桶（曲线/列表口径分歧根因）。"""
    rows = ["2026-09-20 10:16:00", "2026-09-20 10:08:00"]
    assert len(_cluster_round_rows([_row(t) for t in rows])) == 1


def test_round_gap_500s_splits():
    """500s 断口（实测区间内）切轮：420 < 500 ≤ 600。"""
    rows = ["2026-09-20 10:16:40", "2026-09-20 10:08:00"]
    assert len(_cluster_round_rows([_row(t) for t in rows])) == 1


def test_round_gap_intra_round_holds():
    """轮内错峰（3 分钟）不切：一轮多查询跨 2-3 分钟 < 420s。"""
    rows = ["2026-09-20 10:16:00", "2026-09-20 10:13:00"]
    assert len(_cluster_round_rows([_row(t) for t in rows])) == 2


def test_report_bucket_gap_420_same_value():
    """曲线桶轮界与列表同值 420（两端同改——两套阈值并存曾「图有列无」）。"""
    src = open("report.py", encoding="utf-8").read()
    assert ".total_seconds() <= 420" in src, "曲线桶轮界未同步 420"


# ---- P2-4 normalize stopCity 首个非空段 ----

def test_norm_stopcity_first_nonempty():
    from core.flightnorm import normalize
    f = {"stopCitys": ";庆阳", "platform": "qunar"}
    normalize(f)
    assert f.get("stopCity") == "庆阳", "前导分号脏值致 stopCity 丢失"


def test_norm_stopcity_clean_first():
    from core.flightnorm import normalize
    f = {"stopCitys": "西安;库尔勒", "platform": "qunar"}
    normalize(f)
    assert f.get("stopCity") == "西安"


# ---- P2-8 ctrip labels 组装去重 ----

def test_ctrip_labels_dedup():
    """aset 同词重复（dump 两处 tagarea 同词）不再重复拼接。"""
    from crawlers.ctrip import CtripCrawler
    seg = {"basinfo": {"flgno": "HO1256"},
           "dateinfo": {"ddate": "2026-10-06 09:30:00",
                        "adate": "2026-10-06 14:05:00"},
           "dportinfo": {"city": "URC", "aport": "URC", "bsname": ""},
           "aportinfo": {"city": "SHA", "aport": "SHA", "bsname": "T2"}}
    item = {"mutilstn": [seg],
            "policyinfo": [{"tprice": 800, "quantity": 5}],
            "aset": [{"tagarea": [{"tagcnt": "宠物友好"},
                                  {"tagcnt": "宠物友好"},
                                  {"tagcnt": "轻飞享奖里程"},
                                  {"tagcnt": "轻飞享奖里程"}]}]}
    fs = CtripCrawler._extract_ctrip_flights(
        object.__new__(CtripCrawler), json.dumps({"fltitem": [item]}))
    assert fs[0]["labels"] == "宠物友好·轻飞享奖里程"


# ---- P2-8 qunar transferService 前缀重复 ----

def test_qunar_svc_txt_no_dup_prefix():
    from crawlers.qunar import QunarCrawler
    # tsl 自带 tsn 前缀（'中转优享：…'）不再重复拼 '中转优享:'
    assert QunarCrawler._svc_txt("中转优享", "中转优享：免费餐食") \
        == "中转优享：免费餐食"
    assert QunarCrawler._svc_txt("中转优享", "免费餐食") \
        == "中转优享:免费餐食"
    assert QunarCrawler._svc_txt("", "免费餐食") == "免费餐食"
    assert QunarCrawler._svc_txt("中转优享", "") == ""


# ---- P2-7 停用航线不进 routesArr ----

def test_user_state_filters_disabled_routes():
    """_user_state 的 routes 列表推导过滤 enabled is False（与日报
    _chart_routes 已滤停用对齐；停用线作 routes[0] 曾使顶层 history
    恒空）。源码钉：_user_state 重不可直测，钉过滤条件在场。"""
    src = open("webui.py", encoding="utf-8").read()
    assert 'if r.get("enabled") is not False' in src or \
        "if not r.get(\"enabled\") is False" in src or \
        'r.get("enabled") is not False' in src, \
        "停用航线过滤缺失（enabled:false 仍进 routesArr）"
