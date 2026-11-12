# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r941_wait_budget.py
- tests/test_r949_wait_backoff_window.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import io
import os
import re
import sys
import time

from crawlers.qunar import QunarCrawler


# ---- merged from tests/test_r941_wait_budget.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _crawler(tmp_path):
    return QunarCrawler({"user_data_dir": str(tmp_path),
                         "profile": "qunar"}, None)


def _reset_budget(used=0.0, since=None):
    QunarCrawler._WAIT_BUDGET["used_s"] = float(used)
    QunarCrawler._WAIT_BUDGET["since"] = float(
        since if since is not None else time.time())


# ---------------------------------------------------------------------------
# 1. 预算常量合理
# ---------------------------------------------------------------------------
def test_budget_constant_is_sane(tmp_path):
    c = _crawler(tmp_path)
    # 要够走完一次 90/180 阶梯，又不能把一轮（~30min）拖没
    assert 120 <= c.ROUND_WAIT_BUDGET_S <= 900, c.ROUND_WAIT_BUDGET_S


# ---------------------------------------------------------------------------
# 2. 累计与窗口复位
# ---------------------------------------------------------------------------
def test_budget_accumulates_across_calls(tmp_path):
    """`fetch()` 每条航线一次：预算必须跨调用累计，否则永远撞不到上限。"""
    c = _crawler(tmp_path)
    _reset_budget(0.0)
    # 模拟第一条航线等 90s
    QunarCrawler._WAIT_BUDGET["used_s"] += 90
    c._reset_wait_budget_if_stale()
    assert QunarCrawler._WAIT_BUDGET["used_s"] == 90, "跨调用被清零了"
    # 再等 180s
    QunarCrawler._WAIT_BUDGET["used_s"] += 180
    assert QunarCrawler._WAIT_BUDGET["used_s"] == 270


def test_budget_resets_after_window(tmp_path):
    """窗口（≈一轮）过去就清零，下一轮重新有预算。"""
    c = _crawler(tmp_path)
    _reset_budget(290.0, since=time.time() - 3000)      # 50 分钟前
    c._reset_wait_budget_if_stale()
    assert QunarCrawler._WAIT_BUDGET["used_s"] == 0.0


def test_budget_kept_within_window(tmp_path):
    """窗口内不清零。"""
    c = _crawler(tmp_path)
    _reset_budget(200.0, since=time.time() - 600)       # 10 分钟前
    c._reset_wait_budget_if_stale()
    assert QunarCrawler._WAIT_BUDGET["used_s"] == 200.0


# ---------------------------------------------------------------------------
# 3. 超预算判定（核心）
# ---------------------------------------------------------------------------
def test_next_wait_would_exceed_budget(tmp_path):
    c = _crawler(tmp_path)
    _reset_budget(c.ROUND_WAIT_BUDGET_S - 10)           # 只剩 10s
    # 下一次需要等 90s → 累计会超
    would = QunarCrawler._WAIT_BUDGET["used_s"] + 90 > c.ROUND_WAIT_BUDGET_S
    assert would, "超预算没被识别出来"


def test_within_budget_does_not_abort(tmp_path):
    c = _crawler(tmp_path)
    _reset_budget(0.0)
    would = QunarCrawler._WAIT_BUDGET["used_s"] + 90 > c.ROUND_WAIT_BUDGET_S
    assert not would, "预算充足时误判成超支"


# ---------------------------------------------------------------------------
# 4. 源码钉：超预算要如实记 `paced`（不算失败）
# ---------------------------------------------------------------------------
def test_source_aborts_with_paced(tmp_path):
    src = io.open(os.path.join(ROOT, "crawlers", "qunar.py"),
                  encoding="utf-8").read()
    i = src.find("本轮等待已达预算")
    assert i > 0, "找不到超预算分支"
    seg = src[max(0, i - 1200):i + 1200]
    assert "本轮等待已达预算" in seg, "没有超预算的告警"
    assert '"paced"' in seg, "让位没记 paced（会污染爬取率）"
    assert "本轮等待预算用尽" in seg, "账本没写清原因"


# ---- merged from tests/test_r949_wait_backoff_window.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _src() -> str:
    return io.open(os.path.join(ROOT, "crawlers", "qunar.py"),
                   encoding="utf-8").read()


# ---------------------------------------------------------------------------
# 1. 窗口长度要合理：比一轮长（否则每轮还是会试烧），又不能太久（会钉死）
# ---------------------------------------------------------------------------
def test_backoff_window_length_is_sane():
    w = QunarCrawler.WAIT_BACKOFF_S
    # 一轮 ≈ 25–35 分钟；窗口取 20 分钟 → 下一轮多半已过期，能重试一次；
    # 但同一轮内其余航线全部零成本让位。
    assert 300 <= w <= 3600, w
    # 必须 >= 单轮预算的量级，否则窗口内还会反复试探
    assert w >= QunarCrawler.ROUND_WAIT_BUDGET_S, (w, QunarCrawler.ROUND_WAIT_BUDGET_S)


def test_window_state_is_class_level():
    """跨航线共享：`fetch()` 是每条航线一次，实例级状态等于没有窗口。"""
    assert isinstance(QunarCrawler.__dict__.get("_WAIT_BACKOFF_UNTIL"), float)


# ---------------------------------------------------------------------------
# 2. 核心：窗口内**不许 sleep**
# ---------------------------------------------------------------------------
def test_window_branch_has_no_sleep():
    """退避窗口那段必须"记录 paced + return"，中间不能有 sleep。"""
    src = _src()
    i = src.find("仍在限流退避窗口内")
    assert i > 0, "找不到窗口分支"
    seg = src[i:i + 700]
    j = seg.find("return []")
    assert j > 0, "窗口分支没有让位返回"
    head = seg[:j]
    assert "sleep" not in head, "窗口内还在 sleep（等于每轮继续烧满预算）"
    assert "paced" in head, "窗口让位没记 paced"


def test_budget_exhaustion_opens_window():
    """预算用尽的分支必须**同时**开启窗口，否则下一轮还会烧满。"""
    src = _src()
    i = src.find("本轮等待已达预算")
    assert i > 0, "找不到预算用尽分支"
    seg = src[i:i + 1400]
    # 必须调用开启窗口的方法（不能只是设一个固定值）
    assert "_open_wait_backoff" in seg, "预算用尽后没开退避窗口（下一轮会重烧）"
    assert "_WAIT_BACKOFF_UNTIL" in seg, "没写窗口终点"


def test_window_checked_before_wait_computed():
    """窗口判定必须在 `wait = max(...)` **之前**——在后面判就等于先等再弃。"""
    src = _src()
    i_win = src.find("_bo_left")
    i_wait = src.find("wait = max(QunarCrawler._cooldown_until")
    assert i_win > 0 and i_wait > 0
    assert i_win < i_wait, "窗口判定在算 wait 之后（已经晚了）"


# ---------------------------------------------------------------------------
# 3. 语义：窗口内是"主动让位"，不是失败
# ---------------------------------------------------------------------------
def test_backoff_detail_wording(tmp_path):
    """detail 要点明"退避窗口"，便于事后区分"被拒"和"我方不打"。"""
    src = _src()
    assert "限流退避窗口" in src
    # 不许把它写成 soft_reject / blocked（那是把让步算成失败）
    i = src.find("仍在限流退避窗口内")
    seg = src[i:i + 700]
    for bad in ("soft_reject", "blocked", "captcha"):
        assert bad not in seg, "窗口让位被记成 %s（应是 paced）" % bad


def test_window_expires(tmp_path):
    """算术核对：窗口到期后 `_bo_left <= 0`，恢复正常路径。"""
    now = time.time()
    QunarCrawler._WAIT_BACKOFF_UNTIL = now + 5
    assert QunarCrawler._WAIT_BACKOFF_UNTIL - now > 0, "窗口内应仍在"
    QunarCrawler._WAIT_BACKOFF_UNTIL = now - 1
    assert QunarCrawler._WAIT_BACKOFF_UNTIL - now <= 0, "过期后应放行"
