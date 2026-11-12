# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r324_push_pool.py
- tests/test_v191_push.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import datetime as dt
import json
import logging
import os
import sys

from core.alerter import Alerter, _disp_dw, _fit_line, _l2_fallbacks
from core.models import FlightPrice, Route


# ---- merged from tests/test_r324_push_pool.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _fp(price, name, dpt, art, trans="", cross="", plat="qunar",
        dep="2026-11-02", **kw):
    d0 = dt.date.fromisoformat(dep)
    days = 1 if cross == "+1天" else (2 if cross == "+2天" else 0)
    f = {"price": price, "name": name, "code": name, "depTime": dpt,
         "arrTime": art, "depDate": dep,
         "arrDate": str(d0 + dt.timedelta(days=days)),
         "transCity": trans, "crossDayDesc": cross,
         "totalDuration": "6时", "_platform": plat}
    f.update(kw)
    return f


def _ps(plist, fc, tc, d):
    return [FlightPrice(platform=f["_platform"], from_city=fc, to_city=tc,
                        depart_date=d, price=f["price"],
                        extra=json.dumps([f], ensure_ascii=False))
            for f in plist]


def _route(**kw):
    d = dict(from_code="SHA", to_code="URC", from_name="上海",
             to_name="乌鲁木齐", dates=["2026-11-02"],
             alert_direct=1900, alert_transfer=1700)
    d.update(kw)
    return Route(**d)


def test_plat_top3_pool_matches_market_top5():
    """组尾各渠道最低与同图 TOP5 同价（直挂筛选不遮蔽行情口径）。"""
    a = Alerter(logging.getLogger("probe"), notifier=None, storage=None)
    r = _route(transfer_baggage="direct")
    # fliggy：中转 1750（行情口径在场：到达 23:50 未超 02:00、衔接
    # 120min；transferBaggage 缺失=直挂筛选滤掉）+ 直飞 1841（兜底底价）
    p = _ps([
        _fp(1750, "MU8370转", "09:00", "23:50", trans="郑州",
            plat="fliggy", layoverM=120),
        _fp(1841, "南航CZ6981", "18:30", "23:40", plat="fliggy"),
    ], "SHA", "URC", "2026-11-02")
    sec = a._build_sections(r, p)[0]
    tops = sec.get("top_transfer") or []
    assert any(f["price"] == 1750 for f in tops), "行情口径 TOP5 应含中转 1750"
    pt3 = (sec.get("plat_top3") or {}).get("fliggy") or []
    lo = min((f["price"] for f in pt3), default=None)
    assert lo == 1750, (
        f"组尾 plat_top3 最低 {lo}≠TOP5 行情口径 1750——"
        "组尾池混入直挂筛选口径，同图两数并存")
    mins = a._plat_mins_for(sec)
    assert mins.get("fliggy", (None,))[0] == 1750, (
        "「各渠道最低（含直飞）」组尾应与 TOP5 同价同口径")


def test_demo_transfer_codes_chain_form():
    """demo 中转行 code 恒「/」链形（与生产 qunar 同形态，退役
    裸段码——跨源时刻仲裁的「无 / 直飞」代理门不再误吞演示行）。"""
    import tempfile
    import sqlite3
    from core.demo import build_demo_db
    path = os.path.join(tempfile.gettempdir(), "r324_demo_code_probe.db")
    try:
        build_demo_db(path)
        conn = sqlite3.connect(path)
        rows = conn.execute(
            "SELECT extra FROM flight_prices WHERE extra LIKE '%transCity%'"
        ).fetchall()
        conn.close()
        assert rows, "demo 库应含中转明细行"
        bad = []
        for (extra,) in rows:
            for el in json.loads(extra):
                if el.get("transCity") and "/" not in str(el.get("code", "")):
                    bad.append((el.get("_platform"), el.get("code")))
        assert not bad, f"demo 中转行裸段码（生产不可达形态）：{bad[:4]}"
    finally:
        if os.path.exists(path):
            os.remove(path)


# ---- merged from tests/test_v191_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t1591p")


# ---- P1-1：图挂兜底头行 U+2026 ----

def test_cross_compare_fallback_no_ellipsis():
    """跨渠道共享航班双侧航司长名（28 半角名+结论尾 42/40 超宽）触发
    头行降级第二档（去航司名保航班号）：输出不含 U+2026（钉钉渲染
    。。。。），航班号与结论保留。"""
    long_name = "奥凯航空｜中国联合航空KN1234"
    pool = []
    for plat, price in (("qunar", 1000), ("fliggy", 1350),
                        ("tongcheng", 1700)):
        pool.append({"price": price, "name": long_name, "code": "GS7728",
                     "depTime": "08:20", "arrTime": "13:40",
                     "transCity": "", "crossDayDesc": "",
                     "stopover": False, "_platform": plat})
    txt = Alerter._cross_compare([{"date": "2026-10-10", "pool": pool}])
    assert txt
    assert "\u2026" not in txt, "图挂兜底头行残留 U+2026（钉钉渲染。。。）"
    assert "KN1234" in txt, "降级档丢航班号（地板档语义受损）"


def test_kpi_l2_call_site_uses_fallbacks_helper():
    """调用点源码钉：KPI 行2 降级走 _l2_fallbacks 单源（档序修复
    不被调用点内联链回退）。"""
    import core.alerter as al
    with open(al.__file__, encoding="utf-8") as f:
        src = f.read()
    assert "fallbacks=_l2_fallbacks(" in src, \
        "KPI 行2 调用点未走 _l2_fallbacks 单源"


# ---- P1-2：KPI 行2 跨天优先于涨跌 ----

def test_l2_fallbacks_cross_day_before_delta():
    """降级链档序：跨天括注档在首位；涨跌档（次要信号，恒宽于
    跨天档=不可达死档）已按档序律删除——地板档前自然丢失。"""
    fb = _l2_fallbacks("BASE", "+1天", " ｜ 较上轮 ↓￥133")
    assert fb[0] == "BASE+1天", "跨天档不在首位"
    assert not any("较上轮" in t for t in fb), "死档 d 未删净"
    # r281 修法 B：cross 真入地板链（修复地板档 cross 恒缺席的
    # 次生丢失）——短输入下地板=base+cross 整串
    assert fb[-1] == "BASE+1天", "地板档缺失或缺 cross"


def test_kpi_l2_cross_day_survives_narrow_fit():
    """生产可达输入（42 半角行基+跨天+涨跌）：fit 结果必须保留
    +1 天（旧链在跨天档也超时与涨跌双丢）。"""
    base = "新海航｜海南航空HU7849 21:10→02:35"
    cross, d = "+1天", " ｜ 较上轮 ↓￥133"
    full = base + cross + d
    assert _disp_dw(full) > 40, "样本未触发降级（判据失效）"
    l2 = _fit_line(full, fallbacks=_l2_fallbacks(base, cross, d))
    assert "+1天" in l2, f"跨天括注被降级丢弃 {l2!r}"
    assert _disp_dw(l2) <= 40, f"行2 超宽 {l2!r}"


# ---- P2-1：demo 演示面覆盖「有餐食」 ----

def test_demo_covers_meal_positive(tmp_path):
    """fliggy 演示行 meal 值域含「有餐食」与「无餐食」双态（演示
    目检面与生产值域对齐）。"""
    import core.demo as demo
    db = str(tmp_path / "demo.db")
    demo.build_demo_db(db)
    import sqlite3
    conn = sqlite3.connect(db)
    meals = set()
    for (extra,) in conn.execute(
            "SELECT extra FROM flight_prices WHERE platform='fliggy' "
            "AND extra != ''"):
        for f in json.loads(extra):
            if f.get("meal"):
                meals.add(f["meal"])
    conn.close()
    assert "无餐食" in meals, "负向演示行丢失"
    assert "有餐食" in meals, "「有餐食」正向值域无演示目检面"
