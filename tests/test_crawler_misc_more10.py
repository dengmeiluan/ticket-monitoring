# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r952_escalating_backoff.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import os
import sys

from crawlers.qunar import QunarCrawler


# ---- merged from tests/test_r952_escalating_backoff.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _crawler(tmp_path):
    return QunarCrawler({"user_data_dir": str(tmp_path),
                         "profile": "qunar"}, None)


def _reset():
    QunarCrawler._WAIT_BACKOFF_STREAK = 0
    QunarCrawler._WAIT_BACKOFF_UNTIL = 0.0


# ---------------------------------------------------------------------------
# 1. 指数增长 + 封顶
# ---------------------------------------------------------------------------
def test_backoff_grows_and_caps(tmp_path):
    _reset()
    c = _crawler(tmp_path)
    seq = [c._open_wait_backoff() for _ in range(5)]
    assert seq[0] == QunarCrawler.WAIT_BACKOFF_S, seq
    assert seq[1] == 2 * QunarCrawler.WAIT_BACKOFF_S, seq
    assert seq[2] == 3 * QunarCrawler.WAIT_BACKOFF_S, seq      # 封顶在 3x
    assert all(x <= QunarCrawler.WAIT_BACKOFF_MAX_S for x in seq), seq
    # 必须封顶：不封顶的退避等于"再也不试"，那是自杀式优化
    assert seq[-1] == QunarCrawler.WAIT_BACKOFF_MAX_S, seq


def test_backoff_window_is_set_forward(tmp_path):
    import time
    _reset()
    c = _crawler(tmp_path)
    w = c._open_wait_backoff()
    left = QunarCrawler._WAIT_BACKOFF_UNTIL - time.time()
    assert 0 < left <= w + 5, (left, w)


# ---------------------------------------------------------------------------
# 2. 成功必须清零（否则一次误判会惩罚一整天）
# ---------------------------------------------------------------------------
def test_source_resets_streak_on_detail():
    import io
    src = io.open(os.path.join(ROOT, "crawlers", "qunar.py"),
                  encoding="utf-8").read()
    i = src.find("if _has_detail and QunarCrawler._WAIT_BACKOFF_STREAK")
    assert i > 0, "出明细时没把退避计数清零"
    seg = src[i:i + 520]
    assert "_WAIT_BACKOFF_STREAK = 0" in seg
    assert "_WAIT_BACKOFF_UNTIL = 0.0" in seg, "清零没同时关掉窗口"
    # 而且必须在 `return res` 之前，否则等于没执行
    assert seg.find("return res") > 0, "清零逻辑不在成功返回路径上"


def test_reset_restores_first_window(tmp_path):
    _reset()
    c = _crawler(tmp_path)
    c._open_wait_backoff()
    c._open_wait_backoff()
    assert QunarCrawler._WAIT_BACKOFF_STREAK == 2
    _reset()
    assert c._open_wait_backoff() == QunarCrawler.WAIT_BACKOFF_S


# ---------------------------------------------------------------------------
# 3. 上限要够温和：封顶值不许超过一轮调度周期的量级太多
# ---------------------------------------------------------------------------
def test_max_backoff_is_not_absurd():
    # 一轮 ≈ 30 分钟；封顶 60 分钟 = 跳过两轮，能接受。
    # 再大就等于"今天不再试 qunar 国际"，那是把渠道主动判死。
    assert 600 <= QunarCrawler.WAIT_BACKOFF_MAX_S <= 7200, \
        QunarCrawler.WAIT_BACKOFF_MAX_S
