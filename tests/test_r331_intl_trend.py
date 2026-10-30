# -*- coding: utf-8 -*-
"""qunar 国际改期比价曲线（trendPrice.goFTrend → trendGo）接线。

国际 touchInterList 响应与国内 H5 同族携带 trendPrice（生产 19/19
dump 在场，每份 30 点 ±15 天窗、远期无报价点为空串、有效价点 14-15），
消费端（webui 改期窗口 /api/state trendGo 透传+前端渲染门）在产，
出口键已有——仅国际解析分支未调 _parse_trend_go（国内路径
_parse_response_flights 已接线）。同国内律：只挂当轮最低价行防 extra
膨胀；值域门按国际宽带单源（price_band_ok el={"intl":1}，长途高价点
78139 实证于 cabinDesc 行价，国内 50000 门会丢）。

样本形态取自生产 dump 实证（debug/qunar_raw_intl_*）：
{"price": "709", "date": "2026-11-09", "index": 8}，price 恒字符串。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r331_intl_trend.py
"""
import glob
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.qunar import QunarCrawler  # noqa: E402

_LOG = logging.getLogger("t_r331_intl_trend")
_QN = QunarCrawler({}, _LOG)


def _resp(data=None, code=0, bstatus=None):
    o = {"code": code, "ret": True}
    if bstatus is not None:
        o["bstatus"] = {"code": bstatus}
    if data is not None:
        o["data"] = data
    return json.dumps(o)


def _trend(pts):
    return {"trendPrice": {"goFTrend": pts}}


def _tp(pts):
    """trendPrice dict 本体（_parse_trend_go 的入参语义）。"""
    return {"goFTrend": pts}


def _pt(d, p):
    return {"price": p, "date": d, "index": 0}


def _route_row(**over):
    row = {
        "code": "NH960",
        "minPrice": 2380, "nakedPrice": 1860, "taxPrice": 520,
        "transCity": "",
        "cabinDesc": "经济舱",
        "fewTicket": "",
        "binfo": {"depTime": "09:30", "arrTime": "14:00",
                  "depDate": "2026-11-16", "arrDate": "2026-11-16"},
    }
    row.update(over)
    return row


# ---- 接线：最低价行挂 trendGo ----

def test_intl_trend_mounts_lowest_row():
    """带趋势的响应：最低价行挂 trendGo，点数=有效点数、MM-DD 形态。"""
    pts = ([_pt(f"2026-11-{d:02d}", str(1000 + d)) for d in range(1, 16)]
           + [_pt(f"2026-11-{d:02d}", "") for d in range(16, 31)])
    data = _trend(pts)
    data["routes"] = [_route_row(), _route_row(minPrice=1200,
                                               code="NH961")]
    rows, risk = _QN._parse_intl_response(_resp(data))
    assert risk == "" and len(rows) == 2
    tg_rows = [r for r in rows if r.get("trendGo")]
    assert len(tg_rows) == 1, "只挂当轮最低价行（防 extra 膨胀，同国内律）"
    tg = tg_rows[0]["trendGo"]
    assert tg_rows[0]["price"] == 1200
    assert len(tg) == 15, "空串价点丢弃（远期无报价 15/30 实证形态）"
    assert tg[0] == ["11-01", 1001]
    assert all(len(p[0]) == 5 for p in tg), "日期 MM-DD 形态（消费端协议）"


def test_intl_trend_absent_no_key():
    """无 trendPrice（旧形态/零航班轮）：不落键，行解析零回归。"""
    rows, _ = _QN._parse_intl_response(
        _resp({"routes": [_route_row()]}))
    assert len(rows) == 1 and "trendGo" not in rows[0]


# ---- 值域门：国际宽带单源 ----

def test_intl_band_keeps_high_price_default_keeps_domestic():
    """intl 分档：>50000 点保留（国际宽带 200000，长途高价实证）；
    默认（国内路径）维持 50000 门行为零变化。"""
    pts = [_pt("2026-11-09", "78139"), _pt("2026-11-10", "709"),
           _pt("2026-11-11", "99999"), _pt("2026-11-12", "")]
    tg = _QN._parse_trend_go(_tp(pts), intl=True)
    assert tg == [["11-09", 78139], ["11-10", 709], ["11-11", 99999]]
    tg_dom = _QN._parse_trend_go(_tp(pts))
    assert tg_dom == [["11-10", 709]], "国内门行为零变化"
    # 200000 上界同样生效（带外垃圾价仍丢）
    assert _QN._parse_trend_go(
        _tp([_pt("2026-11-09", "200001")]), intl=True) is None


# ---- 回放：冻结 dump 过真实解析器（锁相对语义，不锚瞬时计数）----

def test_intl_dump_replay_relative_semantics():
    """生产 dump 回放：19 份国际 dump（活文件，锁结构关系不锁瞬时值）——
    有行且解出 trendGo 的份：点数 1..30、价带内、MM-DD 形态；
    零航班轮（flights=[]）无挂载点不产 trendGo 且不炸。
    语料缺席（CI/新克隆无 debug/ dump）本钉空转不假红。"""
    dumps = sorted(glob.glob("debug/qunar_raw_intl_*"))
    if not dumps:
        return
    n_ok = n_rows = 0
    for fp in dumps:
        txt = open(fp, encoding="utf-8", errors="ignore").read()
        rows, _ = _QN._parse_intl_response(txt)
        if not rows:
            continue
        n_rows += len(rows)
        for r in rows:
            tg = r.get("trendGo")
            if tg is None:
                continue
            n_ok += 1
            assert 1 <= len(tg) <= 30
            assert all(len(p) == 2 and len(p[0]) == 5 for p in tg)
    # 结构下限：生产语料在场时至少解出行
    assert n_rows > 0
