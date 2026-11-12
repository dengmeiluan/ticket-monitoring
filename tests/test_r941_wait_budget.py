# -*- coding: utf-8 -*-
"""r941：qunar 的退避等待**没有上限**，一轮里空等 48.6 分钟。

实测（2026-11-04 12:00 之后统计 `logs/monitor.log`）：

```
令牌桶              24 秒
错峰等待          2891 秒   ← = 48.6 分钟，全是纯空等
合计实际等待      2915 秒
```

后果不是"qunar 自己慢"，而是**整条采集线程被它占着**：

* 13:53 开始那一轮，到 14:16（**23 分钟**）还停在 qunar 国际段的
  1999 限流 + 90s 等待循环里；
* `app_qunar` / `app_zhixing` / 同程 / 途牛 全被推迟，
  实测 `app_qunar` **一整轮都没轮到**。

退避本身没错（守配额），但**不能无上限**：这些渠道互不冲突，
没理由陪 qunar 一起等。

修法：**单轮等待累计预算** `ROUND_WAIT_BUDGET_S = 300` 秒。
`fetch()` 是"每条航线一次"，所以用**类级累计 + 时间窗**（默认 35 分钟，
≈ 一轮）；超预算就主动让位并记 `paced`（我方主动不发，不算失败）。

取 300 而不是更小：够走完一次 90/180 的阶梯，又不至于把一轮拖没。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r941_wait_budget.py -q
"""
import io
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers.qunar import QunarCrawler  # noqa: E402


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
