# -*- coding: utf-8 -*-
"""r280 首轮节流门语义修正。

旧实现：_first_run 的 300s 节流挂在每轮调度触发入口（docstring 意图=
进程启动后的首轮防轰炸）。15 分钟级周期下触发时上轮多已落库 5 分钟+
从不拦截；5 分钟级短周期下单轮扫描时长超过间隔，每个对齐点触发都距上
轮落库不足 5 分钟——节流逐轮拦截，实际轮距被拉长一倍以上（实测 5 分
钟网格退化为 ~15 分钟轮距，用户配置名存实亡）。

修正为 first-only 门：仅进程启动后的首次触发检查，后续触发恒放行；
连环重启不轰炸推送的原意图由「每次重启的首轮都被节流」完整保留。
"""
import sqlite3
from datetime import datetime, timedelta

import main as _m


class TestFirstRunGate:
    def test_gate_skips_only_first_round(self):
        """核心复现：fresh 谓词下首次跳过、之后恒放行。
        旧实现等价于每轮重查谓词（第二次仍 True）——修正前此断言红。"""
        gate = _m._FirstRunGate(lambda: 120.0)
        assert gate.should_skip() is True
        assert gate.should_skip() is False
        assert gate.should_skip() is False

    def test_gate_predicate_queried_once(self):
        """谓词只在有臂时被查询一次；耗臂后不再触谓词（DB 读每轮零开销）。"""
        calls = []
        gate = _m._FirstRunGate(lambda: calls.append(1) or 120.0)
        gate.should_skip()
        gate.should_skip()
        assert len(calls) == 1

    def test_gate_stale_or_missing_no_skip(self):
        """首轮上轮落库已老（>300s）或 DB 不可读（None）：不跳过。"""
        assert _m._FirstRunGate(lambda: 900.0).should_skip() is False
        assert _m._FirstRunGate(lambda: None).should_skip() is False
        assert _m._FirstRunGate(lambda: 299.9).should_skip() is True

    def test_gate_exposes_last_age(self):
        """Soldier Minor-3：跳过分支的日志龄取 gate.last_age（单次读库），
        不再二次读库（两读可竞态不一致，日志面失真）。"""
        gate = _m._FirstRunGate(lambda: 120.0)
        assert gate.should_skip() is True
        assert gate.last_age == 120.0

    def test_first_gate_shared_instance(self):
        """Soldier Minor-2：gate 实例必须在 main() 创建一次、_first_run
        闭包复用——每轮新建 gate 等于节流每轮重装臂，first-only 退化。"""
        src = open("main.py", encoding="utf-8").read()
        assert src.count("_first_gate = _FirstRunGate(") == 1
        assert "if _first_gate.should_skip():" in src
        assert "_first_gate.last_age" in src, "日志龄未走单次读库"


class TestRecentSweepAge:
    def _mkdb(self, tmp_path, ts):
        db = tmp_path / "p.db"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE flight_prices (fetched_at TEXT)")
        if ts is not None:
            con.execute("INSERT INTO flight_prices VALUES (?)", (ts,))
        con.commit()
        con.close()
        return str(db)

    def test_fresh_db_age_positive(self, tmp_path):
        ts = (datetime.now() - timedelta(seconds=60)
              ).strftime("%Y-%m-%d %H:%M:%S")
        age = _m._recent_sweep_age(self._mkdb(tmp_path, ts))
        assert age is not None and 0 <= age < 300

    def test_stale_db_age_over_window(self, tmp_path):
        ts = (datetime.now() - timedelta(minutes=30)
              ).strftime("%Y-%m-%d %H:%M:%S")
        age = _m._recent_sweep_age(self._mkdb(tmp_path, ts))
        assert age is not None and age > 300

    def test_empty_table_returns_none(self, tmp_path):
        assert _m._recent_sweep_age(self._mkdb(tmp_path, None)) is None

    def test_missing_db_returns_none(self, tmp_path):
        assert _m._recent_sweep_age(str(tmp_path / "nope.db")) is None
