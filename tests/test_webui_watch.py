# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r351_watch.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import json
import os
import sys
import webui

from core.models import FlightPrice, Route
from core.storage import PriceStorage
from datetime import date, timedelta

# 活数据日期：防「日期已过」校验随日历腐化
_FUTURE = (date.today() + timedelta(days=7)).isoformat()
_FUTURE1 = (date.today() + timedelta(days=8)).isoformat()  # 相邻日：不在航线日期明细内


# ---- merged from tests/test_r351_watch.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _payload(**kw):
    p = {"from": "SHA", "to": "BKK", "date": _FUTURE,
         "code": "MU541", "depTime": "09:55", "arrTime": "13:40",
         "trans": "", "cross": "", "stop": False, "cabin": "经济舱",
         "airline": "东航", "platKey": "ctrip",
         "channels": ["qunar", "ctrip", "tuniu", "fliggy", "tongcheng"],
         "target": 800}
    p.update(kw)
    return p


def _temp_state(tmp_path):
    dbp = str(tmp_path / "watch.db")
    old_cfg, old_users = webui._State.cfg, webui._State.users
    webui._State.cfg = {"output": {"db_path": dbp}}
    webui._State.users = []
    webui._WATCH_CACHE.clear()
    return dbp, old_cfg, old_users


def _restore(old_cfg, old_users):
    webui._State.cfg, webui._State.users = old_cfg, old_users
    webui._WATCH_CACHE.clear()


def _save(st, platform, frm, to, date, price, extra):
    st.save(FlightPrice(platform, frm, to, date, price,
                        extra=json.dumps(extra, ensure_ascii=False)))


def test_watch_entry_identity_and_cabin_normalization():
    a = webui._watch_entry(_payload())
    b = webui._watch_entry(_payload(target=900, cabin="经济舱 · 空客A320"))
    assert a["id"] == b["id"]
    assert a["flightKey"].startswith("SHA|BKK|MU541|" + _FUTURE + "|09:55|13:40|")
    assert a["cabin"] == "经济"
    assert a["target"] == 800
    only = webui._watch_entry(_payload(channels=["ctrip", "bogus", "ctrip"]))
    assert only["channels"] == ["ctrip"]
    assert webui._watch_entry(_payload(channels=[]))["channels"] == list(
        webui._WATCH_PLATS)
    try:
        webui._watch_entry(_payload(target="abc"))
    except ValueError:
        pass
    else:
        raise AssertionError("非法目标价必须拒绝")


def test_watch_scope_accepts_route_object():
    old_users = webui._State.users
    webui._State.users = [{
        "name": "u1",
        "routes": [Route("SHA", "上海", "BKK", "曼谷", [_FUTURE])],
    }]
    try:
        e = webui._watch_entry(_payload())
        assert webui._watch_in_scope(e, "u1") is True
        assert webui._watch_in_scope(e, "nobody") is False
        # 关注航班是配置航线+日期明细的子集：未命中的日期不再是有效范围
        assert webui._watch_in_scope(
            webui._watch_entry(_payload(date=_FUTURE1)), "u1") is False
    finally:
        webui._State.users = old_users


def test_watch_apply_persists_without_price(tmp_path):
    _dbp, oc, ou = _temp_state(tmp_path)
    try:
        out = webui._watch_apply("u1", {"op": "add", "watch": _payload()})
        assert len(out["watches"]) == 1
        wid = out["watches"][0]["id"]
        path = webui._watch_path()
        raw = json.load(open(path, encoding="utf-8"))
        assert "u1" in raw and raw["u1"][0]["id"] == wid
        assert "price" not in raw["u1"][0]
        assert "profit" not in raw["u1"][0]
        out = webui._watch_apply("u1", {
            "op": "update", "id": wid,
            "patch": {"channels": ["fliggy"], "target": 700, "active": False}})
        w = out["watches"][0]
        assert w["channels"] == ["fliggy"] and w["target"] == 700
        assert w["active"] is False
        out = webui._watch_apply("u2", {"op": "add", "watch": _payload()})
        assert len(out["watches"]) == 1
        out = webui._watch_apply("u1", {"op": "remove", "id": wid})
        assert out["watches"] == []
        assert "u1" in json.load(open(path, encoding="utf-8"))
    finally:
        _restore(oc, ou)


def test_watch_trend_filters_cabin_and_missing_raw_cabin(tmp_path):
    dbp, oc, ou = _temp_state(tmp_path)
    try:
        st = PriceStorage(dbp)
        base = {"code": "MU541", "name": "东航MU541", "depDate": _FUTURE,
                "depTime": "09:55", "arrTime": "13:40",
                "totalDuration": "3时45分", "price": 800}
        _save(st, "ctrip", "SHA", "BKK", _FUTURE, 800, [dict(
            base, cabin="经济舱", cabinT="经济舱 · 空客A320")])
        _save(st, "qunar", "SHA", "BKK", _FUTURE, 2500, [dict(
            base, price=2500, cabin="公务舱", cabinT="公务舱 · 空客A330")])
        # raw 未给舱位的行不能并入已指定舱位的历史（宁缺勿错）
        _save(st, "fliggy", "SHA", "BKK", _FUTURE, 999, [dict(
            base, price=999)])
        entry = webui._watch_entry(_payload())
        webui._watch_apply("u1", {"op": "add", "watch": _payload()})
        tr = webui._watch_trend("u1", entry["id"], days=14)
        assert tr["ok"] is True
        prices = [p[1] for p in tr["points"]]
        assert prices == [800]
        assert tr["current"]["price"] == 800
        assert tr["current"]["platform"] == "ctrip"
        assert tr["daily"] and tr["daily"][0][1] == 800
        assert "同舱位" in tr["note"]
    finally:
        _restore(oc, ou)


def test_watch_ui_contract_static():
    src = webui_full_src()
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in src
    assert "1.06fr" not in src and ".94fr" not in src
    for marker in ("data-watchbtn", "srxOpenWatch", "srxWatchLoadTrend",
                   "/api/srx/watch", "/api/srx/watch/trend",
                   "srx-wstate", "srx-wtrend", "同航班同舱位"):
        assert marker in src, marker
