# -*- coding: utf-8 -*-
"""r319 特价监控 P1：SpecialWatch 配置归一化（纯函数面）。

社区诉求（LinuxDo wujiu）：选定出发地 → 特价机票 + 回程。
配置操作简单纪律：缺省整体缺省=功能关闭；坏值降级禁用该条不炸进程；
钳制防手滑（days 上限 180、interval_rounds 下限 1）。"""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.specials import SpecialWatch, parse_specials  # noqa: E402

_TODAY = date(2026, 10, 16)


class TestParseSpecials(unittest.TestCase):
    def test_absent_key_yields_nothing(self):
        """无 specials 键=功能关闭（零打扰存量用户）。"""
        self.assertEqual(parse_specials(None, _TODAY), [])
        self.assertEqual(parse_specials([], _TODAY), [])

    def test_full_watch_normalizes(self):
        ws = parse_specials([{
            "enabled": True, "from": "SHA", "from_name": "上海",
            "max_price": 400, "days": 45, "round_trip": True,
            "round_trip_days": 5, "interval_rounds": 6,
            "dest_pool": ["URC", "KMG"], "platforms": ["ctrip"],
        }], _TODAY)
        self.assertEqual(len(ws), 1)
        w = ws[0]
        self.assertIsInstance(w, SpecialWatch)
        self.assertEqual(w.from_code, "SHA")
        self.assertEqual(w.from_name, "上海")
        self.assertEqual(w.max_price, 400)
        self.assertEqual(w.days, 45)
        self.assertEqual(w.round_trip_days, 5)
        self.assertEqual(w.interval_rounds, 6)
        self.assertEqual(w.dest_pool, ["URC", "KMG"])
        self.assertEqual(w.platforms, ["ctrip"])

    def test_defaults_fill(self):
        """只给必填三项也能跑（入手简单）：days=30/往返开/窗 7 天/
        节流 4 轮/双源发现。"""
        ws = parse_specials([
            {"enabled": True, "from": "sha", "from_name": "上海",
             "max_price": "400"}], _TODAY)
        w = ws[0]
        self.assertEqual(w.days, 30)
        self.assertTrue(w.round_trip)
        self.assertEqual(w.round_trip_days, 7)
        self.assertEqual(w.interval_rounds, 4)
        self.assertEqual(w.platforms,
                         ["tuniu", "ctrip", "ctripbd", "fliggy"])
        self.assertEqual(w.dest_pool, [])
        # 三字码归一：小写进大写出
        self.assertEqual(w.from_code, "SHA")

    def test_bad_entries_dropped(self):
        """坏条目整条降级丢弃，好条目照常保留（宁缺勿错，不炸进程）：
        缺出发地/码非法/价位非正/数值垃圾。"""
        ws = parse_specials([
            {"enabled": True, "from_name": "上海", "max_price": 400},
            {"enabled": True, "from": "SHANGHAI", "max_price": 400},
            {"enabled": True, "from": "SHA", "max_price": 0},
            {"enabled": True, "from": "SHA", "max_price": "abc"},
            {"enabled": False, "from": "SHA", "max_price": 400},   # 显式停用
            {"enabled": True, "from": "PEK", "from_name": "北京",
             "max_price": 500},
        ], _TODAY)
        self.assertEqual(len(ws), 1)
        self.assertEqual(ws[0].from_code, "PEK")

    def test_days_clamped(self):
        """手滑防线：days ≤0 回缺省 30、>180 钳 180；往返窗钳 0..30；
        interval_rounds <1 回 1。"""
        ws = parse_specials([
            {"enabled": True, "from": "SHA", "max_price": 400,
             "days": 9999, "round_trip_days": -3, "interval_rounds": 0},
        ], _TODAY)
        w = ws[0]
        self.assertEqual(w.days, 180)
        self.assertEqual(w.round_trip_days, 0)
        self.assertEqual(w.interval_rounds, 1)
        ws2 = parse_specials([
            {"enabled": True, "from": "SHA", "max_price": 400, "days": -1},
        ], _TODAY)
        self.assertEqual(ws2[0].days, 30)


class TestBuildUsers(unittest.TestCase):
    def test_specials_passthrough_and_specials_only_user(self):
        """build_users：specials 透传进运行时用户；只订特价无航线的
        用户也保留（发现模式独立于定向订阅）。"""
        import main as _main
        cfg = {"users": [
            {"name": "甲", "specials": [
                {"enabled": True, "from": "SHA", "from_name": "上海",
                 "max_price": 400}], "platforms": ["ctrip"],
             "notifier": {}, "schedule": {}},
            {"name": "乙", "routes": [], "platforms": ["ctrip"],
             "notifier": {}, "schedule": {}},
        ]}
        users = _main.build_users(cfg)
        self.assertEqual([u["name"] for u in users], ["甲"])
        self.assertEqual(len(users[0]["specials"]), 1)
        self.assertEqual(users[0]["specials"][0]["from"], "SHA")


if __name__ == "__main__":
    unittest.main()
