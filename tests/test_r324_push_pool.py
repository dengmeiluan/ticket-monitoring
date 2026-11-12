# -*- coding: utf-8 -*-
"""r324 推送层钉面。

- P3-1 「各渠道最低（含直飞）」单口径：总表组尾 plat_top3 池曾吃
  达标口径（ok_transfers，含直挂筛选），与同图 TOP5（行情口径
  top_transfers）和日报组尾（directs+mkt_t）三面两数——直挂筛选
  滤掉的中转低价被组尾高价遮蔽，同图两数并存无解释（产品律「行情
  展示不限直挂」）。钉=构造「中转低价过行情口径、被直挂筛选滤掉」
  的组，断言 plat_top3 组尾价与 TOP5 同价。
- P3-2 demo 中转行 code 形态退役：生产 qunar 中转 code 恒「/」链形
  （crawlers/qunar.py "/".join），demo 夹具裸段码撞跨源时刻仲裁的
  「无 / 直飞代理门」被整行改写起降（生产现状不可达的形态不应在
  演示语料在场，24§17 推论）。钉=demo 全部中转行 code 含「/」。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r324_push_pool.py -q
"""
import datetime as dt
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import Alerter  # noqa: E402
from core.models import FlightPrice, Route  # noqa: E402


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
