"""r273 数据层：qunar 跨日中转停留（layover）日期钉修复。

缺陷（r273 观测切片②实锤，现役窗 2 组 + EXPIRED 5 组）：PC/H5 兜底
路径 stop_m=(二段起飞−首段到达)%1440，真停 ≥24h 时钟面差落在
[0,1440) 区间不触发回绕修正——SC4926/SC4603 14:30-21:00(+1天) 经青岛
真停 24:05 被落成 0:05（ctrip 同指纹 1445 互证），LAY_MIN 衔接筛选
按 5 分钟保守误剔低价隔夜中转候选；totalDuration 由 normalize 起止
重算兜底正确，唯 layover/layoverM/layoverT 带错值直通。

修复：二段起飞日由整体到达日钉（二段当日达 arrTime≥depTime → 起飞
日=arrDate；二段自身跨天 → 前一日），停留=相对首段到达日的天数差
×1440+钟面差；日期钉不住（arrDate 缺/解析败/结果 ≤0）退回旧
%1440+span 守卫形态（<24h 停留两法数学等价）。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.qunar import QunarCrawler  # noqa: E402


def _pc_row(b1, b2, code="SC4926/SC4603", trans_city="青岛", price="980"):
    return {"ret": True, "data": {"flights": [{
        "code": code, "minPrice": price, "transCity": trans_city,
        "crossDayDesc": "+1天", "transTime": "",
        "binfo1": b1, "binfo2": b2,
    }]}}


# ---- RED：跨日真停 ≥24h 不再被 %1440 回绕成小值 ----

def test_qunar_pc_crossday_transfer_layover_not_wrapped():
    b1 = {"airCode": "SC4926", "depTime": "14:30", "arrTime": "19:10",
          "date": "2026-10-15", "arrDate": "2026-10-15"}
    b2 = {"airCode": "SC4603", "depTime": "19:15", "arrTime": "21:00",
          "date": "2026-10-16", "arrDate": "2026-10-16"}
    out = QunarCrawler._parse_pc_flights(
        json.dumps(_pc_row(b1, b2), ensure_ascii=False), "2026-10-15")
    assert len(out) == 1
    t = out[0]
    # 真停 24:05（ctrip 同指纹 1445 互证），旧实现落 5
    assert t["layover"] == 1445, t
    assert t["layoverSrc"] == "times"
    assert t["lay2dep"] == "19:15" and t["arrDate"] == "2026-10-16"
    from core.flightnorm import normalize as _nf
    _t = _nf(dict(t), "2026-10-15")
    assert _t["layoverM"] == 1445 and _t["layoverT"] == "24:05", _t
    # LAY_MIN=90 衔接筛选放行（旧值 5 被保守误剔的决策面）
    assert _t["layoverM"] >= 90


def test_qunar_h5_crossday_transfer_layover_not_wrapped():
    row = {"minPrice": 800, "code": "SC4926/SC4603", "transCity": "青岛",
           "binfo1": {"depTime": "14:30", "arrTime": "19:10",
                      "depDate": "2026-10-15", "arrDate": "2026-10-15"},
           "binfo2": {"depTime": "19:15", "arrTime": "21:00",
                      "depDate": "2026-10-16", "arrDate": "2026-10-16"}}
    out = QunarCrawler._extract_flights_obj([row])
    assert out and out[0]["layover"] == 1445, out


# ---- 回归：钉不住/等价形态维持旧结果 ----

def test_qunar_pc_transfer_layover_legacy_shapes_unchanged():
    # 既有夹具形态（首段自身跨天，真停 19:25 <24h）：钉法与 %1440 等价
    b1 = {"airCode": "MU5533", "depTime": "23:25", "arrTime": "01:10",
          "date": "2026-09-25", "arrDate": "2026-09-26"}
    b2 = {"airCode": "SC8711", "depTime": "20:35", "arrTime": "00:55",
          "date": "2026-09-26", "arrDate": "2026-09-27"}
    out = QunarCrawler._parse_pc_flights(
        json.dumps(_pc_row(b1, b2, code="MU5533/SC8711", trans_city="济南"),
                   ensure_ascii=False), "2026-09-25")
    assert out[0]["layover"] == 1165, out

    # 同日中转：180 分钟
    b1 = {"depTime": "08:00", "arrTime": "10:00",
          "date": "2026-10-15", "arrDate": "2026-10-15"}
    b2 = {"depTime": "13:00", "arrTime": "15:00",
          "date": "2026-10-15", "arrDate": "2026-10-15"}
    out = QunarCrawler._parse_pc_flights(
        json.dumps(_pc_row(b1, b2), ensure_ascii=False), "2026-10-15")
    assert out[0]["layover"] == 180, out

    # 隔夜 <24h：23:00 到、次日 06:00 走 → 7h
    b1 = {"depTime": "20:00", "arrTime": "23:00",
          "date": "2026-10-15", "arrDate": "2026-10-15"}
    b2 = {"depTime": "06:00", "arrTime": "09:00",
          "date": "2026-10-16", "arrDate": "2026-10-16"}
    out = QunarCrawler._parse_pc_flights(
        json.dumps(_pc_row(b1, b2), ensure_ascii=False), "2026-10-15")
    assert out[0]["layover"] == 420, out


def test_qunar_pc_transfer_layover_dates_missing_fallback():
    # binfo1.arrDate 缺席（守卫不拦、生产可达的防御形态）→ 钉不住
    # 退回旧 %1440+span 守卫形态
    b1 = {"depTime": "20:00", "arrTime": "23:10", "date": "2026-10-15"}
    b2 = {"depTime": "06:00", "arrTime": "09:00",
          "date": "2026-10-16", "arrDate": "2026-10-16"}
    out = QunarCrawler._parse_pc_flights(
        json.dumps(_pc_row(b1, b2), ensure_ascii=False), "2026-10-15")
    assert out and out[0]["layover"] == 410, out

    # Soldier M-2 专属钉：钉不住 × span≥2 × 钟面差 <5h 的旧守卫组合
    # 形态（~25h 真停被回绕成 55min 的垃圾带）→ 弃算不落键（宁缺勿错）
    b1 = {"depTime": "20:00", "arrTime": "23:10", "date": "2026-10-15"}
    b2 = {"depTime": "00:05", "arrTime": "02:00",
          "date": "2026-10-18", "arrDate": "2026-10-18"}
    out = QunarCrawler._parse_pc_flights(
        json.dumps(_pc_row(b1, b2), ensure_ascii=False), "2026-10-15")
    assert out and "layover" not in out[0], out


def test_layover_pinned_helper_edges():
    # 纯函数边界：日期解析败/结果 ≤0/语义验证不过 → None（调用方退旧形态）
    from crawlers.qunar import _layover_pinned
    b1 = {"arrTime": "23:00", "arrDate": "2026-10-15"}
    # 二段自身跨天（arrTime<depTime）：b2.date=次日 → 停 7h
    b2 = {"depTime": "06:00", "arrTime": "09:00",
          "date": "2026-10-16", "arrDate": "2026-10-16"}
    assert _layover_pinned(b1, b2) == 420
    # 跨 2 天真停（45h15m 形态）
    b2 = {"depTime": "20:15", "arrTime": "22:00",
          "date": "2026-10-17", "arrDate": "2026-10-17"}
    assert _layover_pinned(b1, b2) == 2 * 1440 - 165
    # 矛盾形态（b2.date 早于 b1.arrDate，语义验证不过）→ None
    b1 = {"arrTime": "19:10", "arrDate": "2026-10-16"}
    b2 = {"depTime": "09:00", "arrTime": "11:00",
          "date": "2026-10-15", "arrDate": "2026-10-15"}
    assert _layover_pinned(b1, b2) is None
    # 日期键缺席 → None
    assert _layover_pinned(
        {"arrTime": "10:00"},
        {"depTime": "12:00", "date": "2026-10-16",
         "arrDate": "2026-10-16"}) is None
