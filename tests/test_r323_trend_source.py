# -*- coding: utf-8 -*-
"""半年走势数据源与 demo 派生钉（r323 P1-1）。

- _trend_payload 数据源必须走 _State.cfg（单一事实源，与 /api/state
  同源）——初版读 config_path，demo 态从未设置该路径，读穿真实
  config.yaml→生产 DB（demo 页面吐真实生产价=数据来源声明失实）；
- build_demo_db 必须派生 price_daily 日桶（与生产同函数同口径），
  否则 demo 长窗三档全空态。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r323_trend_source.py -q
"""
import json
import os
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import demo as demo_mod  # noqa: E402
from core.models import FlightPrice  # noqa: E402
from core.storage import PriceStorage  # noqa: E402
import webui  # noqa: E402


def _now_s():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row(price, code, fetched):
    el = [{"price": price, "code": code, "name": code,
           "depTime": "08:00", "arrTime": "11:00"}]
    return FlightPrice(
        platform="qunar", from_city="URC", to_city="SHA",
        depart_date="2026-11-01", price=price, airline="",
        flight_no=code, depart_time="08:00", arrive_time="11:00",
        extra=json.dumps(el, ensure_ascii=False), fetched_at=fetched)


def test_trend_payload_reads_state_cfg_db(tmp_path, monkeypatch):
    """数据源=_State.cfg；config_path 是诱饵（lo=999）不得被读。"""
    db_cfg = os.path.join(str(tmp_path), "cfg.db")
    db_decoy = os.path.join(str(tmp_path), "decoy.db")
    now = _now_s()
    PriceStorage(db_cfg).save_many([_row(1710.0, "CZ1", now)])
    PriceStorage(db_decoy).save_many([_row(999.0, "CZ9", now)])
    for db in (db_cfg, db_decoy):
        PriceStorage(db).refresh_daily("URC", "SHA", "2026-11-01")
    cfg_yaml = os.path.join(str(tmp_path), "config.yaml")
    with open(cfg_yaml, "w", encoding="utf-8") as f:
        f.write(f"output:\n  db_path: {db_decoy}\n")
    monkeypatch.setattr(webui._State, "cfg",
                        {"output": {"db_path": db_cfg}})
    monkeypatch.setattr(webui._State, "config_path", cfg_yaml)
    out = webui._trend_payload({"from": ["URC"], "to": ["SHA"],
                                "date": ["2026-11-01"],
                                "days": ["30"], "th": ["1500"]})
    assert out["ok"], out
    assert out["direct"] and out["direct"][-1][1] == 1710.0, out


def test_build_demo_db_seeds_price_daily(tmp_path):
    """demo 库必须派生 price_daily（直/中双桶在案，长窗非空态）。"""
    path = demo_mod.build_demo_db(os.path.join(str(tmp_path), "demo.db"))
    con = sqlite3.connect(path)
    kinds = dict(con.execute(
        "SELECT kind, COUNT(*) FROM price_daily GROUP BY kind").fetchall())
    con.close()
    assert kinds.get("d", 0) > 0, kinds
    assert kinds.get("t", 0) > 0, kinds


def test_demo_bake_intercepts_trend_api(tmp_path, monkeypatch):
    """静态演示站 fetch shim 必须拦 /api/trend（长窗死通道=静态站长窗
    恒「正在加载」假死）——烘焙产物带三档×全航线的趋势数据。"""
    import docs.demo_build as bake
    import webui as _wui
    # build() 直写 _State.cfg/users/version（demo 态三件）——快照还原，
    # 不还原会污染后续用例（v193 statecache 假红实录，Soldier 抓获）
    for _attr in ("cfg", "users", "version"):
        monkeypatch.setattr(_wui._State, _attr,
                            getattr(_wui._State, _attr))
    out = os.path.join(str(tmp_path), "site")
    monkeypatch.setattr(bake, "OUT", os.path.join(out, "index.html"))
    bake.build()
    with open(bake.OUT, encoding="utf-8") as f:
        html = f.read()
    assert "/api/trend" in html, "shim 未拦 /api/trend"
    assert "trend" in html and html.count("|30") >= 3, \
        "烘焙数据缺三档趋势载荷"
