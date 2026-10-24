# -*- coding: utf-8 -*-
"""r352 关注航班监控台：独立配置 / 长窗真实回放 / 目标提醒去抖。"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui  # noqa: E402
from core.models import FlightPrice, Route  # noqa: E402
from core.storage import PriceStorage  # noqa: E402


def _payload(**kw):
    p = {"from": "SHA", "to": "BKK", "date": "2026-11-16",
         "code": "MU541", "depTime": "09:55", "arrTime": "13:40",
         "trans": "", "cross": "", "stop": False, "cabin": "经济舱",
         "channels": ["ctrip"], "target": 1000}
    p.update(kw)
    return p


def _base(price=900):
    return {"code": "MU541", "name": "东航MU541", "depDate": "2026-11-16",
            "depTime": "09:55", "arrTime": "13:40",
            "totalDuration": "3时45分", "price": price}


def _save(st, price, cabin="经济舱"):
    st.save(FlightPrice("ctrip", "SHA", "BKK", "2026-11-16", price,
                        extra=json.dumps([dict(
                            _base(price), cabin=cabin,
                            cabinT=cabin + " · 空客A320")],
                            ensure_ascii=False)))


def _state(tmp_path):
    dbp = str(tmp_path / "watch352.db")
    old_cfg, old_users = webui._State.cfg, webui._State.users
    webui._State.cfg = {"output": {"db_path": dbp}}
    webui._State.users = [{
        "name": "u1",
        "routes": [Route("SHA", "上海", "BKK", "曼谷", ["2026-11-16"])],
    }]
    webui._WATCH_CACHE.clear()
    return dbp, old_cfg, old_users


def _restore(old_cfg, old_users):
    webui._State.cfg, webui._State.users = old_cfg, old_users
    webui._WATCH_CACHE.clear()


class _Notifier:
    def __init__(self):
        self.sent = []

    def send(self, title, desp="", **kw):
        self.sent.append((title, desp))
        return True


def test_watch_notify_field_default_and_patch(tmp_path):
    dbp, oc, ou = _state(tmp_path)
    try:
        entry = webui._watch_entry(_payload())
        assert entry["notify"] is True
        out = webui._watch_apply("u1", {"op": "add", "watch": _payload()})
        wid = out["watches"][0]["id"]
        out = webui._watch_apply("u1", {
            "op": "update", "id": wid, "patch": {"notify": False}})
        assert out["watches"][0]["notify"] is False
    finally:
        _restore(oc, ou)


def test_watch_trend_supports_long_window(tmp_path):
    dbp, oc, ou = _state(tmp_path)
    try:
        st = PriceStorage(dbp)
        _save(st, 900)
        entry = webui._watch_entry(_payload())
        webui._watch_apply("u1", {"op": "add", "watch": _payload()})
        tr = webui._watch_trend("u1", entry["id"], days=180)
        assert tr["ok"] is True and tr["days"] == 180
        assert tr["points"] and tr["points"][0][1] == 900
    finally:
        _restore(oc, ou)


def test_watch_alert_round_dedupe_drop_and_reset(tmp_path):
    dbp, oc, ou = _state(tmp_path)
    try:
        st = PriceStorage(dbp)
        _save(st, 900)
        entry = webui._watch_entry(_payload(target=1000))
        webui._watch_apply("u1", {"op": "add", "watch": _payload(target=1000)})
        n = _Notifier()
        log = logging.getLogger("r352-test")
        assert webui._watch_alert_round(
            "u1", n, st, log, base_url="https://console.example.com") == 1
        assert len(n.sent) == 1
        assert "MU541" in n.sent[0][0] and "/#watch/u0" in n.sent[0][1]
        # 同价不重复
        assert webui._watch_alert_round("u1", n, st, log) == 0
        # 继续下探 ≥10 元补推
        _save(st, 850)
        webui._WATCH_CACHE.clear()
        assert webui._watch_alert_round("u1", n, st, log) == 1
        # 回到目标上方：清去抖基线
        _save(st, 1100)
        webui._WATCH_CACHE.clear()
        assert webui._watch_alert_round("u1", n, st, log) == 0
        # 再次跌破可重新提醒
        _save(st, 900)
        webui._WATCH_CACHE.clear()
        assert webui._watch_alert_round("u1", n, st, log) == 1
        assert len(n.sent) == 3
    finally:
        _restore(oc, ou)


def test_watch_studio_static_contract():
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "webui.py"), encoding="utf-8").read()
    for marker in ("montab-watch", "wsChart", "wsEmptyHero", "data-wsrange",
                   "data-wsfocus", "cwFromCity", "data-cwmode", "data-cwpick",
                   "_watch_alert_round", "cfgWatchStudio"):
        assert marker in src, marker


def test_flight_daily_persists_without_watch_and_survives_purge(tmp_path):
    dbp, oc, ou = _state(tmp_path)
    try:
        st = PriceStorage(dbp)
        _save(st, 900)
        _save(st, 850)
        today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
        st.refresh_flight_daily("SHA", "BKK", "2026-11-16", today)
        entry = webui._watch_entry(_payload())
        hist = st.flight_history("SHA", "BKK", "2026-11-16",
                                 entry["flightKey"], "经济", ["ctrip"], 30)
        assert len(hist) == 1
        assert (hist[0]["n"], hist[0]["lo"], hist[0]["hi"]) == (2, 850, 900)
        # 任意航班：不需要关注条目也能读
        gen = webui._flight_trend(_payload(), days=30)
        assert gen["ok"] is True and gen["watch"] is False
        assert gen["history"] and gen["current"]["price"] == 850
        # raw 明细被清理后，日桶仍可提供长窗（不依赖关注）
        with st._conn() as c:
            c.execute("DELETE FROM flight_prices")
        webui._WATCH_CACHE.clear()
        gen2 = webui._flight_trend(_payload(), days=180)
        assert gen2["points"] == []
        assert gen2["history"] and gen2["current"]["price"] == 850
        assert gen2["daily"]
    finally:
        _restore(oc, ou)


def test_cabin_class_rejects_discount_and_aircraft_labels():
    from core.flighthist import cabin_class
    assert cabin_class("经济舱 · 空客A320") == "经济"
    # v1.5.276：国内纯折扣词=经济舱折扣描述（否则关注「经济」漏掉
    # 去哪儿/飞猪的折扣行，flight_daily 桶恒空）；机型噪音仍归空
    assert cabin_class("7.0折") == "经济"
    assert cabin_class("全价") == "经济"
    assert cabin_class("空客A320") == ""
    assert cabin_class("Y") == "经济"
    assert cabin_class("公务舱 · 330") == "公务"


def test_watch_entry_normalizes_identity_inputs():
    e = webui._watch_entry(_payload(
        from_="上海", to_="曼谷", depTime="9:55", arrTime="13:40",
        cross="+1"))
    assert e["from"] == "SHA" and e["to"] == "BKK"
    assert e["depTime"] == "09:55"
    assert e["cross"] == "+1天"
    try:
        webui._watch_entry(_payload(depTime="9.55"))
    except ValueError:
        pass
    else:
        raise AssertionError("非法时刻必须拒绝")


def test_watch_hover_redraws_base_chart():
    """悬停只能重绘整张底图后再画一条十字线；直接叠画会留下拖影。"""
    src = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "webui.py"), encoding="utf-8").read()
    tail = src[src.index("function wsHoverAt"):]
    assert "wsDrawChart()" in tail
    assert "wsDrawHover()" not in tail
