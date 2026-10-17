# -*- coding: utf-8 -*-
"""r193 性能回归：/api/state 冷构建 222s → 秒级。

真机实测（2823 行 / 16.7 万航班 / 261MB DB）+ cProfile 定位：

- **主因**：`report.py` 两处把跨渠道孤低价守卫写进列表推导的
  **条件表达式**——
      [x for i, x in enumerate(ds) if i not in xchan_phantom_idx([...])]
  条件表达式对**每个元素重新求值** → O(n) 守卫退化成 O(n²)，内层
  `[... for p, pl in ds]` 还每次都重建整个列表。cProfile：xchan_phantom_idx
  被调 45098 次、吃掉 31.2s 中的 27.4s（88%）。
- **次因**：`xchan_phantom_idx` 内部对每个 i 重建 `sorted(...)`——
  渠道数 ≤5 时单次不贵，但被上面的 O(n²) 放大成 7.9M 次 sorted。
- **次因**：`recent_platform_flights` 先 `json.loads` 全历史行再按
  age 过滤（2823 行 × 28KB extra 白解析 ~8s/航线-日期）。

语义必须逐字不变：三条修法都是「同一判定的等值改写」，不得改变
任何输出（幻影行集合 / 走势序列 / 补位明细）。故本文件既有
**源码级钉**（钉住退化写法不再出现），也有**行为等价**测试。
"""

import datetime as _dt
import json as _json
import os as _os
import sqlite3 as _sq
import tempfile as _tf

import pytest


def _report_src():
    import report as _r
    with open(_r.__file__, encoding="utf-8") as f:
        return f.read()


def _mk_db(td):
    """最小 flight_prices 表（与 core.storage SCHEMA 同列，测试自足）。"""
    dbp = _os.path.join(td, "t.db")
    db = _sq.connect(dbp)
    db.execute(
        "CREATE TABLE flight_prices (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "platform TEXT, extra TEXT, fetched_at TEXT, from_city TEXT,"
        "to_city TEXT, depart_date TEXT, price REAL)")
    db.commit()
    db.close()
    return dbp


def _ins(dbp, platform, flights, hours_ago, from_city="A", to_city="B",
         date="2026-10-01"):
    ts = (_dt.datetime.now() - _dt.timedelta(hours=hours_ago)
          ).strftime("%Y-%m-%d %H:%M:%S")
    # 行价=行内最低元素价（与爬虫行级 price 字段同构——行级幻影
    # 守卫的判定输入）
    _rp = min((float(f.get("price") or 0) for f in flights), default=0)
    db = _sq.connect(dbp)
    db.execute("INSERT INTO flight_prices (platform,extra,fetched_at,"
               "from_city,to_city,depart_date,price) VALUES (?,?,?,?,?,?,?)",
               (platform, _json.dumps(flights), ts, from_city, to_city,
                date, _rp))
    db.commit()
    db.close()


class TestXchanGuardNotQuadratic:
    """修 A：跨渠道守卫不得写在列表推导条件里（O(n²) → O(n)）。"""

    def test_no_guard_call_in_listcomp_condition(self):
        src = _report_src()
        assert "if i not in xchan_phantom_idx(" not in src, (
            "report.py 仍有 `if i not in xchan_phantom_idx(...)` 写法："
            "条件表达式每元素重算 → O(n²)，冷构建被拖到 200s+")
        assert "for i not in xchan_phantom_idx(" not in src

    def test_guard_hoisted_to_local(self):
        """守卫结果必须先接到局部变量，再在推导里做 O(1) 集合判定。"""
        src = _report_src()
        assert src.count("= xchan_phantom_idx(") >= 2, \
            "两处守卫都未 hoist 到局部变量"

    def test_called_once_per_bucket_not_per_row(self):
        """调用次数上界：桶数×2（直飞池 + 中转池），与桶内元素数无关。"""
        import report as _r
        calls = {"n": 0}
        real = _r.xchan_phantom_idx

        def spy(entries):
            calls["n"] += 1
            return real(entries)

        with _tf.TemporaryDirectory() as td:
            dbp = _mk_db(td)
            # 3 轮 × 每轮 5 渠道 × 每渠道 6 个直飞 = 90 个元素
            for rnd in range(3):
                for pi, pl in enumerate(("ctrip", "fliggy", "qunar",
                                         "tongcheng", "tuniu")):
                    fl = [{"price": 2000 + pi * 10 + k, "depTime": "10:00",
                           "arrTime": "13:00"} for k in range(6)]
                    _ins(dbp, pl, fl, hours_ago=1 + rnd * 2)
            _r.xchan_phantom_idx = spy
            try:
                hist = _r._rounds(dbp, "A", "B", "2026-10-01", "02:00",
                                  hours=48)
            finally:
                _r.xchan_phantom_idx = real
        assert len(hist) == 3, hist
        # 每桶恒定 3 次（行级幻影守卫 r248 +1、直飞池、中转池），
        # 3 桶上界 9——与桶内元素数无关（修复前 = 逐元素重算 O(n²)）
        assert calls["n"] <= 9, (
            "xchan_phantom_idx 被调 %d 次（应 ≤9=每桶恒 3 次）：列表推导"
            "条件里仍在逐元素重算" % calls["n"])

    def test_phantom_row_still_filtered(self):
        """行为等价：幻影轮最低价仍被曲线剔除（修法不得放过毒行）。"""
        import report as _r
        with _tf.TemporaryDirectory() as td:
            dbp = _mk_db(td)
            # 一轮：fliggy 吐 700 幻影，其余四渠道 2500+
            _ins(dbp, "fliggy", [{"price": 700, "depTime": "10:00",
                                 "arrTime": "13:00"}], hours_ago=1)
            for pl in ("qunar", "ctrip", "tongcheng", "tuniu"):
                _ins(dbp, pl, [{"price": 2560, "depTime": "10:00",
                                "arrTime": "13:00"}], hours_ago=1)
            hist = _r._rounds(dbp, "A", "B", "2026-10-01", "02:00", hours=48)
        assert hist, "序列不应为空"
        assert hist[0][1] == 2560, (
            "幻影 700 未被剔除（曲线最低价应为 2560）: %r" % (hist[0],))

    def test_low_band_price_survives(self):
        """行为等价回归：150 元真实低价行仍保留（test_v1553 同口径）。"""
        from report import _rounds
        with _tf.TemporaryDirectory() as td:
            dbp = _mk_db(td)
            _ins(dbp, "qunar", [{"price": 150, "depTime": "10:00",
                                "arrTime": "13:00"},
                               {"price": 900, "depTime": "12:00",
                                "arrTime": "15:00"}], hours_ago=1)
            hist = _rounds(dbp, "A", "B", "2026-10-01", "02:00", hours=48)
        assert hist and hist[0][1] == 150, hist


class TestXchanMedianCache:
    """修 B：>渠道中位数按渠道缓存，不在行循环里重算 sorted。"""

    def test_median_computed_outside_row_loop(self):
        """中位数只依赖渠道（pmin 恒定）：必须在行循环**之外**算，
        按渠道缓存——不得逐行重建 sorted。"""
        import report as _r  # noqa: F401  确保链路可导入
        from core import alerter as _a
        with open(_a.__file__, encoding="utf-8") as f:
            src = f.read()
        i0 = src.index("def xchan_phantom_idx(")
        i1 = src.index("\ndef ", i0 + 10)
        seg = src[i0:i1]
        assert "med_by_pl" in seg, \
            "未按渠道缓存中位数：仍在行循环里逐行重建 sorted(...)"
        si = seg.index("others = sorted(")
        assert "med is None" in seg[:si], (
            "sorted(...) 未置于「缓存未命中」分支——每行仍会无条件重算")

    def test_semantics_unchanged(self):
        from core.alerter import xchan_phantom_idx
        ent = [(700.0, "fliggy"), (930.0, "fliggy"), (3070.0, "fliggy"),
               (2546.0, "qunar"), (2550.0, "ctrip"),
               (2850.0, "tongcheng"), (3280.0, "tuniu")]
        assert xchan_phantom_idx(ent) == {0, 1}
        assert xchan_phantom_idx([(100.0, "fliggy")]) == set()
        assert xchan_phantom_idx([(700.0, "fliggy"), (2546.0, "qunar")]) == {0}
        ok = [(2410.0, "tuniu"), (2410.0, "qunar"), (2412.0, "ctrip"),
              (2415.0, "fliggy"), (2430.0, "tongcheng")]
        assert xchan_phantom_idx(ok) == set()

    def test_multi_platform_median_stability(self):
        """多行同渠道：锚取该渠道最低（与修复前同式）。"""
        from core.alerter import xchan_phantom_idx
        ent = [(700.0, "fliggy"), (900.0, "fliggy"), (2546.0, "qunar"),
               (2560.0, "ctrip"), (2600.0, "tongcheng"), (2700.0, "tuniu"),
               (2750.0, "qunar")]
        assert xchan_phantom_idx(ent) == {0, 1}


class TestRecentPlatformFlightsTimeFilter:
    """修 C：补位明细的时间过滤下推到 SQL，不再白解析全历史 extra。"""

    def test_sql_filters_by_age(self):
        src = _report_src()
        i0 = src.index("def recent_platform_flights(")
        i1 = src.index("\ndef ", i0 + 10)
        seg = src[i0:i1]
        assert "datetime('now'" in seg, (
            "recent_platform_flights 未把 hours 下推到 SQL——"
            "仍会 json.loads 全历史 extra（真机 ~8s/航线-日期）")

    def test_old_rows_excluded(self):
        # 直调函数本体（conftest autouse 隔离面暂存了真身，
        # 补位链断源不适用于测 recent_platform_flights 本身的钉）
        import report as _rep
        recent_platform_flights = _rep._recent_platform_flights_raw
        with _tf.TemporaryDirectory() as td:
            dbp = _mk_db(td)
            _ins(dbp, "qunar", [{"price": 2000, "depTime": "10:00",
                                 "arrTime": "13:00"}], hours_ago=10)
            _ins(dbp, "ctrip", [{"price": 2100, "depTime": "10:00",
                                 "arrTime": "13:00"}], hours_ago=1)
            out = recent_platform_flights(dbp, "A", "B", "2026-10-01", hours=6)
        assert "ctrip" in out, "近期渠道应保留"
        assert "qunar" not in out, "10 小时前的行应被 hours=6 排除"

    def test_recent_value_returned(self):
        """保留语义：返回 age 小时与原始 flights 列表。"""
        import report as _rep
        recent_platform_flights = _rep._recent_platform_flights_raw
        with _tf.TemporaryDirectory() as td:
            dbp = _mk_db(td)
            _ins(dbp, "qunar", [{"price": 1888, "depTime": "09:00",
                                 "arrTime": "12:00"}], hours_ago=2)
            out = recent_platform_flights(dbp, "A", "B", "2026-10-01", hours=6)
        assert "qunar" in out
        age, fl = out["qunar"]
        assert 1.5 < age < 2.5, age
        assert fl and fl[0]["price"] == 1888


class TestDailyMinimaReusesNothingBroken:
    """回归护栏：_daily_minima 仍逐日取最低（修 A 不得改其档位口径）。"""

    def test_daily_minima_keeps_daily_min(self):
        from report import _daily_minima
        with _tf.TemporaryDirectory() as td:
            dbp = _mk_db(td)
            _ins(dbp, "qunar", [{"price": 2000, "depTime": "10:00",
                                 "arrTime": "13:00"}], hours_ago=1)
            _ins(dbp, "qunar", [{"price": 1800, "depTime": "10:00",
                                 "arrTime": "13:00"}], hours_ago=5)
            cal = _daily_minima(dbp, "A", "B", "2026-10-01", "02:00", days=14,
                                th_d=1900.0)
        assert cal, "日历不应为空"
        k, v, tier = cal[0]
        assert v == 1800, cal
        assert tier == 2, ("价 1800 ≤ 线 1900 应判真达标档 2: %r" % (cal[0],))


class TestPerfBudgetSanity:
    """性能护栏：同规模下守卫调用数不随行数平方增长。"""

    @pytest.mark.parametrize("n_rows", [2, 8])
    def test_call_growth_is_linear(self, n_rows):
        import report as _r
        calls = {"n": 0}
        real = _r.xchan_phantom_idx

        def spy(entries):
            calls["n"] += 1
            return real(entries)

        with _tf.TemporaryDirectory() as td:
            dbp = _mk_db(td)
            for rnd in range(n_rows):
                for pi, pl in enumerate(("ctrip", "fliggy", "qunar",
                                         "tongcheng", "tuniu")):
                    _ins(dbp, pl, [{"price": 2000 + pi * 10, "depTime":
                                    "10:00", "arrTime": "13:00"}],
                         hours_ago=1 + rnd * 2)
            _r.xchan_phantom_idx = spy
            try:
                hist = _r._rounds(dbp, "A", "B", "2026-10-01", "02:00",
                                  hours=48)
            finally:
                _r.xchan_phantom_idx = real
        assert len(hist) == n_rows, hist
        assert calls["n"] <= 2 * n_rows, (
            "n_rows=%d 时守卫被调 %d 次（应 ≤%d）"
            % (n_rows, calls["n"], 2 * n_rows))
