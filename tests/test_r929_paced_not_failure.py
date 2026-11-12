# -*- coding: utf-8 -*-
"""r929：`paced` —— 主动让位不该被算成「渠道失败」。

发现路径（2026-11-04）：按**结果**统计各渠道成功率，发现 qunar 只有 50%。

    [qunar] 国际查询让位 774s（上一条国际查询软空/限流），本轮跳过 SHA→LHR
    [qunar] 抓取完成，得到 0 条记录 · 国际

去哪儿有国际列表配额保护：一次软空后 900s 不再查其它国际线。这本身是**对的**
（不守配额就会招真限流）。但让位原先被记成 `soft_reject`，于是：

* `core.yield_stats.statuses_ok()` 判这轮"失败" → 成功率只剩 50%；
* 账面看起来像"去哪儿被风控了"，实际它一直在**主动守配额**。

也就是说，**记账把"克制"写成了"被拒"**——这会误导运维去"想办法突破风控"，
而正解是"什么都不做，等配额"。这类失真比缺数据更危险。

修法：
  1. `PATH_STATUS` 增加 `paced`（规范词表同步写入 docs/EXECUTION_SPEC_LATEST.md）；
  2. `core.yield_stats.is_paced()` 识别「整轮只有 paced」；
  3. `base._note_round_yield` / `app_base._note_round_yield` 遇到纯 paced 直接
     跳过——既不算成功也不算失败，不进分母。

关键边界：**只要有一条路径真跑过（哪怕 timeout），这轮就是真实样本**，
不能被 paced 掩盖。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r929_paced_not_failure.py -q
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.yield_stats import is_paced, statuses_ok  # noqa: E402


# ---------------------------------------------------------------------------
# 1. is_paced 判定
# ---------------------------------------------------------------------------
def test_all_paced_is_paced():
    assert is_paced([{"status": "paced"}]) is True
    assert is_paced([{"status": "paced"}, {"status": "paced"}]) is True


def test_mixed_with_real_attempt_is_not_paced():
    """只要有一条真跑过，这轮就是真实样本（不能被 paced 掩盖）。"""
    assert is_paced([{"status": "paced"},
                     {"status": "timeout"}]) is False
    assert is_paced([{"status": "paced"},
                     {"status": "ok", "rows": 5}]) is False
    assert is_paced([{"status": "paced"},
                     {"status": "soft_reject"}]) is False


def test_empty_paths_is_not_paced():
    """没有路径记录 ≠ 主动让位（可能压根没跑，也可能是真失败）。"""
    assert is_paced([]) is False
    assert is_paced(None) is False


def test_non_dict_entries_ignored():
    assert is_paced([{"status": "paced"}, "junk", None]) is True


# ---------------------------------------------------------------------------
# 2. statuses_ok 对 paced 的处理（不冒充成功）
# ---------------------------------------------------------------------------
def test_paced_is_not_success():
    ok, rows, _ = statuses_ok([{"status": "paced"}])
    assert ok is False and rows == 0


def test_paced_does_not_mask_real_success():
    ok, rows, path = statuses_ok([{"status": "paced"},
                                  {"status": "ok", "rows": 7, "path": "H5"}])
    assert ok is True and rows == 7


# ---------------------------------------------------------------------------
# 3. 词表与规范同步（契约）
# ---------------------------------------------------------------------------
def test_path_status_contains_paced():
    from crawlers.base import BaseCrawler
    from crawlers.app_base import AppCrawler
    assert "paced" in BaseCrawler.PATH_STATUS
    assert "paced" in AppCrawler.PATH_STATUS


def test_spec_documents_paced_and_distinction():
    """规范必须写清 `paced` 与 `soft_reject` 的区别（否则下次又被混用）。"""
    spec = io.open(os.path.join(ROOT, "docs", "EXECUTION_SPEC_LATEST.md"),
                   encoding="utf-8").read()
    assert "`paced`" in spec
    assert "不进爬取率分母" in spec
    assert "is_paced" in spec


# ---------------------------------------------------------------------------
# 4. qunar 让位确实记 paced（源码钉）
# ---------------------------------------------------------------------------
def test_qunar_yield_records_paced():
    src = io.open(os.path.join(ROOT, "crawlers", "qunar.py"),
                  encoding="utf-8").read()
    # 认准**真正写账本**的那处：`path_note(` 紧跟着 paced 与"国际查询让位"
    idx = -1
    while True:
        idx = src.find("国际查询让位", idx + 1)
        if idx < 0:
            break
        seg = src[max(0, idx - 400):idx]
        if "path_note(" in seg and '"paced"' in seg:
            return                      # 找到"让位 → 记 paced"的实账
    raise AssertionError("没找到把让位记成 paced 的 path_note（会污染爬取率）")
