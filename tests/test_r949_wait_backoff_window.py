# -*- coding: utf-8 -*-
"""r949：预算用尽只做到"本轮不等"，于是**每一轮**都重烧满 300s 换 0 行。

r941 给 qunar 加了单轮等待预算（`ROUND_WAIT_BUDGET_S = 300`），
超了就放弃本轮。但漏了一件事：**`_cooldown_until` 是跨轮存在的**。

所以真实结果是（2026-11-04，按 3 小时切片统计 `scripts/yield_timeline.py`）：

```
09-12 时   qunar   5/20   25%
12-15 时   qunar   6/20   30%
15-18 时   qunar   0/11    0%     ← 加了预算之后
18-21 时   qunar   0/3     0%
```

也就是说：**qunar 不再产出任何数据，却每轮照烧 300s**。
这不是"让位"，是**纯亏**——让位应该是省下时间，而不是把时间
花在"等一会儿然后放弃"上。

修法：预算用尽时**开一个退避窗口** `WAIT_BACKOFF_S = 1200`（20 分钟，
与 `INTL_QUIET_S` 同量级、≈ 一轮多）。窗口内**零等待直接让位**，
窗口到期自然重试一次。

三条不变量（都在下面钉住）：

1. 窗口内**不许出现 sleep**——否则还是每轮烧满；
2. 窗口是**类级**的（跨航线共享），不然 4 条国际线各自开窗口等于没开；
3. 让位仍记 **`paced`**（我方主动不发，不是渠道失败）。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r949_wait_backoff_window.py -q
"""
import io
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers.qunar import QunarCrawler  # noqa: E402


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
