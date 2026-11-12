# -*- coding: utf-8 -*-
"""r334 观测面三案（fields_b 移交 + 活体取证）：

案① share 哨同日去重击穿（实录：tuniu|share 单日 4 连鸣 14:43/15:52/
  17:04/18:16）——无源窗（SHA-CNX 穿插）与已供给在燃窗（SHA-SGN）
  共用跨窗 (plat,fld) 去重键引发的互扰家族。告警去重键升窗粒度后
  （r335 窗键控），本组钉面按窗键语义改写：各窗留痕互不可及、
  never-supplied 静默结构性自守、平键残留惰性滞留（零消费点）。

案③ zdom 基线门重启失忆（实录：tuniu dom 断供第 5 天恰处「zrow 被
  intl 行压住+zdom 被基线门压住」无哨在响态）——_DOMZERO_SEEN 纯
  内存态（对照 _SENT_SUPPLIED 有持久化），且哨上线时渠道已处断供中
  的域进程内永不建立基线。修法双层：持久化（_sent_load/_sent_save
  domzero| 族）+ 首启 DB 回填（该平台该域存在任意历史行=曾供给）。
"""

import json
import os
import sqlite3
import sys
import types

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

import main as _m  # noqa: E402


class _L:
    def __init__(self):
        self.seen = []

    def warning(self, m, *a):
        self.seen.append(("W", m % a if a else m))

    def info(self, m, *a):
        self.seen.append(("I", m % a if a else m))


def _prices(plat, fc, tc, date, share_rows):
    """单窗记录列表：20 行直飞，share_rows=带 shareCarrier 值的行数。"""
    rows = []
    for i in range(20):
        f = {"price": 1000 + i}
        if i < share_rows:
            f["shareCarrier"] = "X%d" % i
        rows.append(f)
    return [types.SimpleNamespace(
        platform=plat, from_city=fc, to_city=tc, depart_date=date,
        extra=json.dumps(rows))]


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(_m, "_SENT_LAST", {})
    monkeypatch.setattr(_m, "_SENT_CNT", {})
    monkeypatch.setattr(_m, "_SENT_SUPPLIED", {})
    monkeypatch.setattr(_m, "_DOMZERO_SEEN", {})
    monkeypatch.setattr(_m, "_ROW_HIST", {})
    monkeypatch.setattr(_m, "_sent_save", lambda: None)
    return _L()


SHARE_HIT = "决策字段 shareCarrier 命中 0/"


def test_share_dedup_survives_never_supplied_window(monkeypatch, tmp_path):
    """已供给窗在燃 + 无源窗穿插 + 在燃窗复扫：窗键各自去重——在燃窗
    恰一鸣、无源窗静默且不得波及他窗留痕、复扫不重鸣（单日多窗连鸣
    击穿的窗键终态）。"""
    lg = _setup(monkeypatch, tmp_path)
    # 轮 1 窗 A（SHA-SGN）：分子>0 → 窗 A 供给基线记位
    _m._field_sentinel(
        _prices("tuniu", "SHA", "SGN", "2026-11-16", 3), lg)
    # 轮 2 窗 A：恒 0 → 告警（当日首鸣）
    _m._field_sentinel(
        _prices("tuniu", "SHA", "SGN", "2026-11-16", 0), lg)
    hits_a = [m for lv, m in lg.seen if SHARE_HIT in m]
    assert len(hits_a) == 1, lg.seen
    akey = ("tuniu", "share", "SHA", "SGN", "2026-11-16")
    assert akey in _m._SENT_LAST, "在燃留痕应按窗键落位"
    # 轮 3 窗 B（SHA-CNX）：恒 0 never-supplied → 自身静默
    _m._field_sentinel(
        _prices("tuniu", "SHA", "CNX", "2026-11-16", 0), lg)
    assert akey in _m._SENT_LAST, "无源窗不得波及他窗窗键留痕"
    # 轮 4 窗 A：恒 0 → 窗 A「今日已报」短路，不重鸣
    _m._field_sentinel(
        _prices("tuniu", "SHA", "SGN", "2026-11-16", 0), lg)
    hits = [m for lv, m in lg.seen if SHARE_HIT in m]
    assert len(hits) == 1, "同字段单日多窗连鸣（无源窗穿插击穿）：" + str(hits)


def test_never_supplied_window_silent_with_stale_flat_marks(
        monkeypatch, tmp_path):
    """全部窗均无供给：无源窗静默，旧平键时代的存量留痕惰性滞留
    （窗键下告警判定按窗键供给门走，平键残留零消费点）。"""
    lg = _setup(monkeypatch, tmp_path)
    _m._SENT_LAST[("tuniu", "share")] = "2026-10-18"
    _m._SENT_CNT[("tuniu", "share")] = 2
    _m._field_sentinel(
        _prices("tuniu", "SHA", "CNX", "2026-11-16", 0), lg)
    assert not [m for lv, m in lg.seen if SHARE_HIT in m], lg.seen
    assert ("tuniu", "share", "SHA", "CNX", "2026-11-16") \
        not in _m._SENT_LAST
    assert ("tuniu", "share") in _m._SENT_LAST, \
        "平键残留惰性滞留（无消费点，摘除机械随共享键退役）"


def test_share_fossil_supply_keys_not_alert_basis(monkeypatch, tmp_path):
    """过期窗化石供给键不得点燃当前窗告警：供给门按当前窗键查，
    他窗化石键不在判定域（曾有他窗供给史 ≠ 本窗可警）。"""
    lg = _setup(monkeypatch, tmp_path)
    _m._SENT_SUPPLIED[("tuniu", "share", "SHA", "HAK", "2026-10-01")] = \
        "2026-10-01"
    _m._field_sentinel(
        _prices("tuniu", "SHA", "CNX", "2026-11-16", 0), lg)
    assert not [m for lv, m in lg.seen if SHARE_HIT in m], lg.seen


def test_domzero_seen_persisted_roundtrip(monkeypatch, tmp_path):
    """案③持久化层：_DOMZERO_SEEN 随 _sent_save/_sent_load 跨重启保留
    （对照 _SENT_SUPPLIED 同路）。"""
    sf = tmp_path / "sentinel_state.json"
    monkeypatch.setattr(_m, "_sent_state_path", lambda: str(sf))
    monkeypatch.setattr(_m, "_SENT_LAST", {})
    monkeypatch.setattr(_m, "_SENT_CNT", {})
    monkeypatch.setattr(_m, "_SENT_SUPPLIED", {})
    monkeypatch.setattr(_m, "_DOMZERO_SEEN", {})
    _m._DOMZERO_SEEN[("tuniu", "dom")] = True
    _m._sent_save()
    _m._DOMZERO_SEEN.clear()
    _m._sent_load()
    assert _m._DOMZERO_SEEN.get(("tuniu", "dom")) is True, \
        "zdom 基线应跨重启保留（案③）"


def _make_db(tmp_path):
    db = tmp_path / "backfill.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE flight_prices (platform TEXT, from_city TEXT,"
                " to_city TEXT)")
    con.execute("INSERT INTO flight_prices VALUES ('tuniu','SHA','BKK')")
    con.execute("INSERT INTO flight_prices VALUES ('tongcheng','上海','海口')")
    con.commit()
    con.close()
    return str(db)


def test_domzero_backfill_from_db_history(monkeypatch, tmp_path):
    """案③回填层：哨上线时渠道已处断供中的域（tuniu dom 实录）进程内
    永不建立基线——DB 历史行证明「曾供给」（该平台该域存在任意历史行）
    按航线对 is_intl_route 判域补记；全库史结构零域（tongcheng intl）
    不补记（静默语义保留）。"""
    monkeypatch.setattr(_m, "_SENT_LAST", {})
    monkeypatch.setattr(_m, "_SENT_CNT", {})
    monkeypatch.setattr(_m, "_SENT_SUPPLIED", {})
    monkeypatch.setattr(_m, "_DOMZERO_SEEN", {})
    monkeypatch.setattr(_m, "_sent_save", lambda: None)
    _m._sent_backfill_domzero(_make_db(tmp_path))
    assert _m._DOMZERO_SEEN.get(("tuniu", "intl")) is True
    assert _m._DOMZERO_SEEN.get(("tongcheng", "dom")) is True
    assert ("tuniu", "dom") not in _m._DOMZERO_SEEN, \
        "DB 无该域历史行不得补记"
    assert ("tongcheng", "intl") not in _m._DOMZERO_SEEN, \
        "全库史结构零域静默语义保留"


def test_domzero_backfill_idempotent_and_missing_db(monkeypatch, tmp_path):
    """回填幂等（已有基线零操作）+ DB 缺失/不可读零炸。"""
    monkeypatch.setattr(_m, "_SENT_LAST", {})
    monkeypatch.setattr(_m, "_SENT_CNT", {})
    monkeypatch.setattr(_m, "_SENT_SUPPLIED", {})
    monkeypatch.setattr(_m, "_DOMZERO_SEEN", {})
    monkeypatch.setattr(_m, "_sent_save", lambda: None)
    _m._DOMZERO_SEEN[("tuniu", "intl")] = True
    db = _make_db(tmp_path)
    _m._sent_backfill_domzero(db)
    assert _m._DOMZERO_SEEN.get(("tuniu", "intl")) is True
    assert _m._DOMZERO_SEEN.get(("tongcheng", "dom")) is True, \
        "预置他域基线后新域仍应补记（逐域幂等非全局短路，Soldier Minor-2）"
    _m._sent_backfill_domzero(str(tmp_path / "nope.db"))
    _m._sent_backfill_domzero("")
    assert _m._DOMZERO_SEEN.get(("tuniu", "intl")) is True
