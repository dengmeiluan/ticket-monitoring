# -*- coding: utf-8 -*-
"""r245 渠道字段：fliggy 中转跨航站楼标记（「换航站楼」双 p1 载荷）
→ transDepTerminal 同位槽位收编（r245 调研唯一真候选，连续零增量
序列十五轮处终结）。

证据（_scratch/r245_ch_b.md + r245_ch_b_fliggy_tc_ctx.txt）：
10-05 dump transferCityInfo 7 组中 1 组带双 transfer-p1——
「黄花机场T1 + 停6小时20分钟 + 换乘 + 黄花机场T2 起飞」；
现行 _TRANSFER_JS 只取首个 p1，二段起飞楼无出口承载。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r245_fields.py
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.fliggy import FliggyCrawler  # noqa: E402

_LOG = logging.getLogger("t245")

_TRANSFER_TXT = "\n".join([
    "奥凯BK2776", "中型机 738",          # 首段（pend）
    "上航FM9402", "中型机 738",          # 二段（cur）
    "10月05日 15:15", "10月05日 19:05",
    "10月06日 06:05", "10月06日 07:55",
    "乌鲁木齐天山国际机场", "长沙中转", "黄花国际机场T1",
    "¥2060 5.0折", "订票",
])


def test_fliggy_trans_dep_terminal_pairing():
    """跨航站楼中转：transfer_map 双 p1 → transDepTerminal 落键
    （剥「起飞」尾与「国际机场/机场」后缀，对齐 qunar「正定T5」
    同形值域）；transTerminal 现行语义零变化。"""
    rows = FliggyCrawler._parse_pc_text(
        _TRANSFER_TXT, "2026-10-05",
        transfer_map={"BK2776": ("黄花机场T1", "黄花机场T2 起飞")})
    assert rows[0]["transTerminal"] == "黄花T1"
    assert rows[0]["transDepTerminal"] == "黄花T2"


def test_fliggy_trans_dep_terminal_absent_on_single():
    """单楼中转（无第二 p1）：只落 transTerminal，transDepTerminal
    无值不落键（宁缺勿错族律，对齐 r230 四写点纪律）。"""
    rows = FliggyCrawler._parse_pc_text(
        _TRANSFER_TXT, "2026-10-05",
        transfer_map={"BK2776": ("黄花机场T1", "")})
    assert rows[0]["transTerminal"] == "黄花T1"
    assert "transDepTerminal" not in rows[0]


def test_fliggy_transfer_map_legacy_str_form():
    """协议守卫（Soldier P2-1）：transfer_map 旧单值 str 形态按
    「单到达楼」语义容错收编为 (str, '')——不许被当序列下标产出
    脏值（str 形态 _tt[0]='黄'、_tt[1]='花' 的静默脏字面）。"""
    rows = FliggyCrawler._parse_pc_text(
        _TRANSFER_TXT, "2026-10-05",
        transfer_map={"BK2776": "黄花国际机场T1"})
    assert rows[0]["transTerminal"] == "黄花T1"
    assert "transDepTerminal" not in rows[0]


def test_fliggy_transfer_js_collects_dual_p1():
    """_TRANSFER_JS 采集面：matchAll 全量取 transfer-p1（match 单发
    是跨楼事实丢失的根因）+ 三元组返回（[号, 到达楼, 二段起飞楼]）。
    源码钉锁采集面。"""
    src = open("crawlers/fliggy.py", encoding="utf-8").read()
    assert "matchAll(/transfer-p1" in src
    assert "ms[0]" in src and "ms[1]" in src
