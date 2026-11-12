# -*- coding: utf-8 -*-
"""回归保护：qunar 撞门拒（整体门拒 / 1999 限流）不得在同轮退避重试。

为什么值得钉住：这条改动是拿**日志实测数据**换来的——
162 次「错峰等待」重试里只有 2 次（1.2%）真出数，其余 160 次白等
90–177 秒，而且这段等待是同步阻塞、会拖慢整轮并连累其它渠道。

如果有人把判断改回只认 `blanket_gate`（历史写法），1999 会重新变成
"等 90 秒再打一次"，浪费会静默回来——所以用结构断言把它焊住。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SRC = os.path.join(ROOT, "crawlers", "qunar.py")


def _src():
    return io.open(SRC, encoding="utf-8", errors="replace").read()


def test_gate_cooldown_constant_is_rate_limit_window():
    """冷却要覆盖限流窗口（代码内实测记录≈5 分钟/次），不能是 90 秒。"""
    from crawlers.qunar import QunarCrawler
    assert QunarCrawler.GATE_COOLDOWN_S == 300
    assert QunarCrawler.GATE_COOLDOWN_S >= QunarCrawler._BACKOFF_S[0]


def test_token_gate_is_treated_as_gate_not_retried():
    s = _src()
    assert 'if _gate.get("kind") in ("blanket_gate", "token_gate"):' in s, \
        "门拒分支必须同时覆盖 token_gate（1999 限流）"


def test_old_single_kind_check_is_gone():
    """旧写法（只认 blanket_gate）必须已经不存在，防止回退。"""
    s = _src()
    assert 'if _gate.get("kind") == "blanket_gate":' not in s


def test_gate_branch_sets_cooldown_and_skips_retry():
    s = _src()
    i = s.index('in ("blanket_gate", "token_gate")')
    branch = s[i:i + 1200]
    assert "_cooldown_until" in branch, "门拒分支要给渠道冷却"
    assert "GATE_COOLDOWN_S" in branch
    assert "同轮不再重试" in branch
    assert "return []" in branch, "门拒分支必须直接返回，不进入退避睡眠"


def test_backoff_ladder_unchanged_for_normal_soft_empty():
    """普通软空仍保留阶梯退避（那类确实有救，别一并砍掉）。"""
    from crawlers.qunar import QunarCrawler
    assert QunarCrawler._BACKOFF_S == (90, 180, 300)
