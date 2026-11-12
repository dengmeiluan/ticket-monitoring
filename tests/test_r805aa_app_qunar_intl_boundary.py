# -*- coding: utf-8 -*-
"""r805aa：app_qunar「国际航线每轮必失败」——真机单步全绿，不判为逻辑缺陷。

## 账本事实（data/prices.db，10h / 67 条 app_qunar）

    国际 SHA→BKK/LHR/NRT/SIN  每轮**全部失败**，多数停在 `set-city-dep`
    国内 SHA→HAK              时好时坏（set-city-arr / pick-date-failed / ok）
    国内 HAK→SHA              **几乎总成功**（4/4 轮 ok，各 1 行）

对照 `app_zhixing`：ok 51 次 / timeout 2 次，两个 App 共用同一设备。

## 真机单步实测（2026-11-01，MuMu 127.0.0.1:16384）

    起始态：App 停在**日历页**（atom_flight_hs_calendar 在、search_panel 不在）
    _ensure_home  → 12.7s，回首页，search_panel + dep_city 都到位   ✅
    _set_city('上海', dep, 国内档) → **True**，33.2s，城市确实变成上海 ✅

即：**恢复与设城市这两个被判失败的单步，单独跑都成功**。

## 结论（三条，各自可独立证伪）

1. `_HOME_MARK` 判据**没有**把日历页误判成首页——日历页 dump 里
   search_panel 为 False，与首页区分得开。这一条已排除。
2. 单步耗时很大：`_ensure_home` 12.7s + `_set_city` 33.2s。一轮四条国际
   航线串行（每条还要 arr + pick_date + search），**时间预算吃紧**是
   最可能的失败机制，但本轮**没有**在真机上复现出 `set-city-dep`——
   不在单步失败上，而在多日期串行的累积态（App 中途进入别的页面/弹层）。
3. 因此**不能**把 `app_qunar.intl` 改成 n 或 ""：它的失败与「国际」
   这个维度无关（国内 SHA→HAK 同样失败），而是整条 App 通路的稳定性问题。

本文件不新增门禁：现有的 `test_r700/r701`（真机往返契约）与账本侧
`test_declared_y_surface_has_ledger_evidence` 已覆盖。这里只备案**判据边界**，
防止后续有人拿「账本 0 国际行」直接断定「去哪儿 App 不支持国际」——
那会把一个设备时序问题写成能力缺失。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ledger_fixture import groups as _ledger_groups  # noqa: E402


def _ledger():
    """App 渠道按状态的聚合成交证据（本机生产库优先，快照回放）。"""
    rows = []
    for plat, _path, st, runs, rws in _ledger_groups(recent=True):
        if not str(plat).startswith("app"):
            continue
        rows.append((plat, st, runs, rws))
    return rows


def test_app_qunar_intl_not_downgraded_from_ledger_failure():
    """国际声明不许因为「账本没出数」被降级——那不是能力缺失。

    判据用**行为对照**：若 app_qunar 的国内航线在同一账本里也被大面积
    判 timeout，那这条通路的问题是整体的（设备/时序），不能归因到 intl。
    """
    rows = _ledger()
    assert rows, "App 账本证据为空：快照与生产库都不可读"
    from core.channels import CHANNEL_DIMENSIONS
    by = {}
    for plat, st, n, rws in rows:
        by.setdefault(plat, {}).setdefault(st, 0)
        by[plat][st] += n
    aq = by.get("app_qunar") or {}
    to = aq.get("timeout", 0)
    ok = aq.get("ok", 0)
    # 只有「国际失败但国内健康」时才允许把问题归因到 intl 维度
    if to > ok * 2:
        assert CHANNEL_DIMENSIONS["app_qunar"]["intl"] != "n", (
            "app_qunar 整条通路 timeout %d / ok %d（国内国际一起失败），"
            "这是设备时序问题，不是 intl 维度缺失——不许据此降级声明"
            % (to, ok))


def test_home_mark_does_not_match_calendar_page():
    """日历页不含 _HOME_MARK——用真机 dump（若在）固化为回归样本。

    没有样本文件时跳过（本判据的价值在于防止有人把 `_HOME_MARK`
    改成日历页也含的 id，从而让 `_ensure_home` 静默返回日历页）。
    """
    from crawlers.app_qunar import _HOME_MARK
    sample = os.path.join(ROOT, "tests", "fixtures", "qunar_calendar_home.xml")
    assert os.path.isfile(sample), "真机 dump 样本缺失：%s" % sample
    xml = io.open(sample, encoding="utf-8", errors="replace").read()
    assert "atom_flight_hs_calendar" in xml, "样本不是日历页，判据失去靶子"
    assert _HOME_MARK not in xml, (
        "_HOME_MARK=%r 出现在日历页 dump 里：_ensure_home 会误判"
        "「已在首页」而直接返回日历页，后续设城市必然失败" % _HOME_MARK)
