# -*- coding: utf-8 -*-
"""r967：测量工具读错路径 = 静默把"我看不到数据"播报成"没有数据"。

事故（2026-11-05 00:01）：`python scripts/yield_report.py` 打
    [爬取率] 还没有样本（跑完一轮采集后再看）
    [建议]   - 无（各渠道都在正常区间）
而**同一时刻**监控正在写 `user_data/qunar/yield_stats.json`（mtime 00:00:03）、
`user_data/tongcheng/yield_stats.json`（00:00:06）、`user_data/app_zhixing/...`（00:00:57），
日志里也明明有 `[tongcheng] 爬取率建议：间隔 30→24 分钟（下界 0.97 ≥ 0.90，有余量）`。

根因是**路径约定有两份、漂移了**：
  写侧  core.yield_stats.default_ledger(user_data, plat)
        → user_data/<plat>/yield_stats.json        （按渠道一个文件）
  读侧  scripts/yield_report.collect(profile="")
        → user_data/yield_stats.json               （**没有任何代码会写这里**）
`login_ledger.json` 与 `slider_ledger.json` 同罪；
更糟的是 `core.policy.PolicyEngine._known_plats()` 也在读那个扁平路径，
所以策略段一起变空 —— 三块报表同时瞎掉，却都打印得像"数据就是没有"。

**测量工具假阴性比没有工具更坏**：它不会报错，只会让人放弃看它。
本测试同时钉三件事：
  1) 按渠道分文件时，报表必须读得到（含多渠道聚合）；
  2) 坏文件不能拖垮整张报表（一个渠道账本烂掉，其余照常出）；
  3) 给定 profile 时只看那一个渠道（不混别人数据）。

跑：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r967_yield_report_reads_real_paths.py -q
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import yield_report as yr  # noqa: E402
from core.yield_stats import default_ledger  # noqa: E402
from core.riskscore import default_ledger as default_login  # noqa: E402


def _seed(tmp_path, plat, ok=5, fail=1, rows=40, streak=0):
    """按**写侧的真实约定**造数据（不自己拼路径，否则测的还是想象）。"""
    yl = default_ledger(str(tmp_path), plat)
    for i in range(ok):
        yl.note(plat, "h5", True, rows=rows)
    for i in range(fail):
        yl.note(plat, "h5", False, rows=0)
    ll = default_login(str(tmp_path), plat)
    for _ in range(streak):
        ll.note(plat, False)


def test_report_sees_per_platform_ledgers(tmp_path):
    _seed(tmp_path, "qunar", ok=6, fail=2)
    _seed(tmp_path, "ctrip", ok=9, fail=0)
    data = yr.collect(str(tmp_path))
    y = data["yield"]
    assert set(y) >= {"qunar", "ctrip"}, \
        "读不到按渠道账本（以前读 user_data/yield_stats.json 那个没人写的路径）"
    assert y["ctrip"]["samples"] == 9, y["ctrip"]
    assert y["qunar"]["samples"] == 8, y["qunar"]
    assert y["ctrip"]["rate"] > y["qunar"]["rate"]


def test_advice_not_empty_when_rate_is_high(tmp_path):
    """有真实样本且下界高，就该出'有余量'的建议，而不是'各渠道都在正常区间'。"""
    _seed(tmp_path, "tuniu", ok=20, fail=0, rows=30)
    data = yr.collect(str(tmp_path), base_interval=30)
    item = data["yield"].get("tuniu") or {}
    assert item.get("samples"), item
    assert item["interval"]["minutes"] <= 30, item["interval"]


def test_broken_ledger_does_not_blank_the_whole_report(tmp_path):
    """一个渠道的账本坏掉，其余渠道必须照常出。

    以前是"读错一个路径 → 整表空"，这属于同一类脆弱。
    """
    _seed(tmp_path, "good", ok=4, fail=0)
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "yield_stats.json").write_text("{ 这不是 json", encoding="utf-8")
    data = yr.collect(str(tmp_path))
    assert "good" in data["yield"], data["yield"].keys()
    assert data["yield"]["good"]["samples"] == 4


def test_profile_scopes_to_one_channel(tmp_path):
    _seed(tmp_path, "qunar", ok=7, fail=1)
    _seed(tmp_path, "ctrip", ok=3, fail=0)
    data = yr.collect(str(tmp_path), profile="qunar")
    assert set(data["yield"]) == {"qunar"}, data["yield"].keys()


def test_platform_dirs_skips_non_ledger_dirs(tmp_path):
    """渠道发现以"有没有账本文件"为准：目录清单会漏新渠道、留旧渠道。"""
    _seed(tmp_path, "tongcheng", ok=2, fail=0)
    (tmp_path / "device").mkdir()
    (tmp_path / "emptydir").mkdir()
    assert yr._platform_dirs(str(tmp_path)) == ["tongcheng"]


def test_slider_ledger_found_per_platform(tmp_path):
    plat = tmp_path / "app_qunar"
    plat.mkdir()
    (plat / "slider_ledger.json").write_text(
        json.dumps({"app_qunar": {"tries": 3, "ok": 1, "day": "2026-11-05",
                                  "day_tries": 1, "kinds": {}}}),
        encoding="utf-8")
    d = yr._slider_ledger(str(tmp_path))
    assert "app_qunar" in d, d


def test_writer_and_reader_share_one_path_convention():
    """约定只能有一份：读侧必须走 `default_ledger`，不许自己拼路径。

    这条是**结构**约束而非行为约束 —— 行为测试能过不代表下次改名时不会又漂移，
    而这次事故的正是"两边各写一遍路径"。
    """
    src = io.open(os.path.join(ROOT, "scripts", "yield_report.py"),
                  encoding="utf-8").read()
    i = src.find("def collect(")
    body = src[i:src.find("\ndef ", i + 10)]
    assert "default_ledger" in body, "collect 又自己拼账本路径了"
    assert 'os.path.join(base, "yield_stats.json")' not in body, \
        "仍在读 user_data/yield_stats.json（没有代码会写这个路径）"
