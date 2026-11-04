# -*- coding: utf-8 -*-
"""账本证据源：本机生产库优先，干净克隆回放抓取快照。

`data/prices.db` 只在运行中的机器上存在；CI/干净克隆里没有它。过去这些
声明-账本对账门禁直接 skip——矛盾永远看不见。`tests/fixtures/ledger_snapshot.json`
是 2026-11-04 生产库的聚合快照（只含 platform/entry_path/path_status/
runs/rows，无 URL、城市、账号），抓取时同时导出「全部」与「近 30 天」两组，
与本机查询口径一致；本机有生产账本时仍读实时值，快照只做后备。
"""
import io
import json
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "prices.db")
SNAPSHOT = os.path.join(ROOT, "tests", "fixtures", "ledger_snapshot.json")

_GROUP_SQL = ("select platform, entry_path, path_status, count(*), "
              "coalesce(sum(rows), 0) from fetch_paths %s "
              "group by platform, entry_path, path_status")


def _live_ready():
    if not os.path.isfile(DB):
        return False
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"),
                               uri=True)
        try:
            n = conn.execute(
                "select count(*) from fetch_paths where platform='tongcheng'"
                " and rows>0 and entry_path like 'PC%'").fetchone()[0]
        finally:
            conn.close()
        return bool(n)
    except sqlite3.Error:
        return False


def groups(recent=False):
    """[(platform, entry_path, path_status, runs, rows)]

    recent=True 时只统计近 30 天；本机生产库不可用时回放快照的同口径组。
    """
    if _live_ready():
        where = ("where fetched_at > datetime('now','localtime','-30 days')"
                 if recent else "")
        try:
            conn = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"),
                                   uri=True)
            try:
                return [tuple(r) for r in
                        conn.execute(_GROUP_SQL % where).fetchall()]
            finally:
                conn.close()
        except sqlite3.Error:
            pass
    data = json.load(io.open(SNAPSHOT, encoding="utf-8"))
    return [tuple(r) for r in data["recent" if recent else "all_time"]]


def meta():
    return json.load(io.open(SNAPSHOT, encoding="utf-8"))["meta"]
