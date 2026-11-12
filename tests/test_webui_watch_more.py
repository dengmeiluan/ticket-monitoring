# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r352_watch_studio.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import json
import logging
import os
import sys
import webui

from core.models import FlightPrice, Route
from core.storage import PriceStorage
from datetime import date, timedelta

# 活数据日期：防「日期已过」校验随日历腐化
_FUTURE = (date.today() + timedelta(days=7)).isoformat()


# ---- merged from tests/test_r352_watch_studio.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _payload(**kw):
    p = {"from": "SHA", "to": "BKK", "date": _FUTURE,
         "code": "MU541", "depTime": "09:55", "arrTime": "13:40",
         "trans": "", "cross": "", "stop": False, "cabin": "经济舱",
         "channels": ["ctrip"], "target": 1000}
    p.update(kw)
    return p


def _base(price=900):
    return {"code": "MU541", "name": "东航MU541", "depDate": _FUTURE,
            "depTime": "09:55", "arrTime": "13:40",
            "totalDuration": "3时45分", "price": price}


def _save(st, price, cabin="经济舱"):
    st.save(FlightPrice("ctrip", "SHA", "BKK", _FUTURE, price,
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
        "routes": [Route("SHA", "上海", "BKK", "曼谷", [_FUTURE])],
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
    src = webui_full_src()
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
        st.refresh_flight_daily("SHA", "BKK", _FUTURE, today)
        entry = webui._watch_entry(_payload())
        hist = st.flight_history("SHA", "BKK", _FUTURE,
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
    """悬停必须先恢复整张底图再叠十字线；直接叠画会留下拖影。

    r374 起底图改为「一次绘制 + 位图缓存」：悬停只贴回 WS._base，
    不再每次 mousemove 全量 wsDrawChart（实测 3.22ms/次 → 0.01ms）。
    仍然满足「先恢复底图，再画十字线」这条不变量。"""
    src = webui_full_src()
    tail = src[src.index("function wsHoverAt"):]
    assert "ctx.drawImage(WS._base,0,0)" in tail, "悬停未先恢复底图"
    assert "wsDrawChart(true)" in tail, "缺无底图时的兜底重绘"
    assert tail.index("drawImage(WS._base") < tail.index("wsDrawHover()"), \
        "必须先恢复底图再叠浮层"
