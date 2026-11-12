# -*- coding: utf-8 -*-
"""goal 轮哨兵批：基线断代回填 + 退役留痕摘除 + trans 行型供给哨。

背景（观测轮实录）：供给基线 10-16 格式迁移遗留空窗旧键（窗三段空，
渠道×字段粒度时代产物）——它们证明的「历史曾有供给」恰是告警门判据，
但窗粒度门查不到它们：fliggy|prate + tongcheng avgd/cancel/bridge/page
五字段「曾有源后断链 7 天」零告警（假阴）。修复三面：
① 空窗键在册 → 从 DB 历史行按 (渠道,观测键,窗) 回填供给基线，
   末次供给日=行 fetched_at；回填毕删空窗死键（幂等）；
② 观测面豁免/死键退役的存量留痕同轮摘除（_warn 永不被调到退役键，
   ctrip|page 10-16 假火留痕悬挂实录）；
③ trans 行型供给哨：直飞行群满量而中转零行——查询粒度合计
   （zrow/qsup/rowfall）对「行型断供」失明（tongcheng conn 中转壳
   断供第 10 天三面全静默实录）。供给基线门同字段哨。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_sent_backfill.py -q
"""
import json
import os
import sqlite3

from types import SimpleNamespace as _NS

import main as _m


class _L:
    def __init__(self):
        self.seen = []

    def warning(self, *a, **k):
        self.seen.append(a)

    def info(self, *a, **k):
        self.seen.append(a)


def _setup(monkeypatch, tmp_path):
    # 状态文件隔离靠 conftest autouse（SENTINEL_STATE_FILE 环境变量
    # 是 _sent_state_path 的首选支，_SENT_PATH 属性 patch 是无效
    # 脚手架——Soldier M5 摘除）
    monkeypatch.setattr(_m, "_ROW_HIST", {})
    _m._SENT_LAST.clear()
    _m._SENT_CNT.clear()
    _m._SENT_SUPPLIED.clear()


def _mkdb(tmp_path, rows):
    db = str(tmp_path / "hist.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE flight_prices (platform TEXT, from_city TEXT,"
                " to_city TEXT, depart_date TEXT, extra TEXT, fetched_at TEXT)")
    con.executemany("INSERT INTO flight_prices VALUES (?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return db


def test_backfill_from_db_and_stale_key_cleanup(monkeypatch, tmp_path):
    """空窗旧键在册 → DB 历史行回填窗级供给基线 + 空窗死键删除。"""
    _setup(monkeypatch, tmp_path)
    db = _mkdb(tmp_path, [
        ("ctrip", "SHA", "HAK", "2027-01-29",
         json.dumps([{"price": 1000, "planeAge": "8.6年"}]),
         "2026-10-05 10:00:00"),
        ("fliggy", "SHA", "HAK", "2027-01-29",
         json.dumps([{"price": 1100, "prate": 97}]),
         "2026-10-06 11:00:00"),
    ])
    # 模拟 _sent_load 后态：空窗旧键在册（渠道×字段粒度时代产物）
    _m._SENT_SUPPLIED[("ctrip", "page", "", "", "")] = "2026-10-10"
    _m._SENT_SUPPLIED[("fliggy", "prate", "", "", "")] = "2026-10-10"
    n = _m._sent_backfill_supplied(db)
    assert n >= 2, n
    assert ("ctrip", "page", "SHA", "HAK", "2027-01-29") in _m._SENT_SUPPLIED
    assert ("fliggy", "prate", "SHA", "HAK", "2027-01-29") in _m._SENT_SUPPLIED
    # 末次供给日=行 fetched_at 日期
    assert (_m._SENT_SUPPLIED[("ctrip", "page", "SHA", "HAK", "2027-01-29")]
            == "2026-10-05")
    # 空窗死键删除（幂等：下次启动零空窗键零触发）
    assert ("ctrip", "page", "", "", "") not in _m._SENT_SUPPLIED
    assert ("fliggy", "prate", "", "", "") not in _m._SENT_SUPPLIED
    # 幂等：再跑一次零新增
    assert _m._sent_backfill_supplied(db) == 0


def test_backfill_without_stale_keys_is_noop(monkeypatch, tmp_path):
    """无空窗键（基线健康）→ 零触发，不扫 DB。"""
    _setup(monkeypatch, tmp_path)
    db = _mkdb(tmp_path, [
        ("ctrip", "SHA", "HAK", "2027-01-29",
         json.dumps([{"price": 1000, "planeAge": "8.6年"}]),
         "2026-10-05 10:00:00")])
    assert _m._sent_backfill_supplied(db) == 0
    assert not _m._SENT_SUPPLIED


def test_backfill_rowkey_mapping_apt_stopcitys(monkeypatch, tmp_path):
    """apt 桶行键=depAirport/arrAirport、stopcity 行键=stopCitys
    （Soldier M1/M2：apt 曾误用 aptc 的码键、stopCity 是推送期
    产物不进 DB——映射错则对应键永漏补=假阴复发）。"""
    _setup(monkeypatch, tmp_path)
    db = _mkdb(tmp_path, [
        ("qunar", "SHA", "HAK", "2027-01-29",
         json.dumps([{"price": 1000, "depAirport": "虹桥",
                      "stopCitys": ["西宁"]}]),
         "2026-10-05 10:00:00")])
    _m._SENT_SUPPLIED[("qunar", "apt", "", "", "")] = "2026-10-10"
    _m._SENT_SUPPLIED[("qunar", "stopcity", "", "", "")] = "2026-10-10"
    _m._sent_backfill_supplied(db)
    assert ("qunar", "apt", "SHA", "HAK", "2027-01-29") in _m._SENT_SUPPLIED
    assert (("qunar", "stopcity", "SHA", "HAK", "2027-01-29")
            in _m._SENT_SUPPLIED)


def test_backfill_added_count_skips_blank_fetched_at(monkeypatch, tmp_path):
    """added 计数只对可落日行（Soldier M3：fetched_at 空行虚增
    「补记键数」测试锚）；无末次供给日=基线不落。"""
    _setup(monkeypatch, tmp_path)
    db = _mkdb(tmp_path, [
        ("ctrip", "SHA", "HAK", "2027-01-29",
         json.dumps([{"price": 1000, "planeAge": "8.6年"}]), "")])
    _m._SENT_SUPPLIED[("ctrip", "page", "", "", "")] = "2026-10-10"
    assert _m._sent_backfill_supplied(db) == 0
    assert (("ctrip", "page", "SHA", "HAK", "2027-01-29")
            not in _m._SENT_SUPPLIED)


def test_retired_key_leaves_stale_trace_cleaned(monkeypatch, tmp_path):
    """观测面豁免键（如 ctrip|page）的存量在燃留痕同轮摘除——退役后
    _warn 永不被调，留痕悬挂成陈旧读数（10-16 假火一日实录）。"""
    _setup(monkeypatch, tmp_path)
    _m._SENT_LAST[("ctrip", "page")] = "2026-10-16"
    _m._SENT_CNT[("ctrip", "page")] = 1
    rows = [{"price": 1000 + i, "plane": "空客A320", "cabin": "经济舱",
             "meal": "有餐食", "prate": 90, "discount": "4.5折",
             "depTerminal": "T2", "arrTerminal": "T1",
             "depAirport": "咸阳", "arrAirport": "虹桥",
             "depAirportCode": "URC", "arrAirportCode": "SHA"}
            for i in range(12)]
    _m._field_sentinel([_NS(platform="ctrip", extra=json.dumps(rows))], _L())
    assert ("ctrip", "page") not in _m._SENT_LAST, _m._SENT_LAST


def test_trans_supply_sentinel_warns_after_gap(monkeypatch, tmp_path):
    """trans 行型供给哨：该窗曾有中转行后归零、直飞行群满量 → WARNING。"""
    _setup(monkeypatch, tmp_path)
    log = _L()
    direct_rows = [{"price": 1000 + i, "plane": "空客A320",
                    "cabin": "经济舱", "meal": "有餐食", "prate": 90,
                    "depTerminal": "T2", "arrTerminal": "T1",
                    "depAirport": "咸阳", "arrAirport": "虹桥",
                    "depAirportCode": "URC", "arrAirportCode": "SHA"}
                   for i in range(22)]
    trans_rows = [{"price": 900, "transCity": "西安", "layover": 90,
                   "depAirportCode": "URC", "arrAirportCode": "SHA"}]
    # 第一轮：中转供给在场（基线标记）
    _m._field_sentinel([_NS(platform="tongcheng",
                            extra=json.dumps(direct_rows + trans_rows))], log)
    assert any("trans" in str(k) for k in _m._SENT_SUPPLIED), _m._SENT_SUPPLIED
    # 第二轮：中转归零、直飞满量 → 行型断供告警
    _m._field_sentinel([_NS(platform="tongcheng",
                            extra=json.dumps(direct_rows))], log)
    msgs = " ".join(str(a) for a in log.seen)
    assert "中转零行" in msgs, msgs


def test_trans_never_supplied_stays_silent(monkeypatch, tmp_path):
    """窗口诞生起无中转供给（天然无中转航线）→ never-supplied 静默
    （卅二§1 同律，字段哨不为结构性无源燃警）。"""
    _setup(monkeypatch, tmp_path)
    log = _L()
    direct_rows = [{"price": 1000 + i, "plane": "空客A320",
                    "cabin": "经济舱", "meal": "有餐食", "prate": 90,
                    "depTerminal": "T2", "arrTerminal": "T1",
                    "depAirport": "咸阳", "arrAirport": "虹桥",
                    "depAirportCode": "URC", "arrAirportCode": "SHA"}
                   for i in range(22)]
    _m._field_sentinel([_NS(platform="ctrip",
                            extra=json.dumps(direct_rows))], log)
    assert not log.seen, log.seen
