# -*- coding: utf-8 -*-
"""r952：固定退避窗口仍然每轮烧一次预算——要按连续失败指数拉长。

r949 开了一个固定 20 分钟的窗口，解决了"同一轮内其余航线跟着等"。
但真实限流**持续了一整个下午**：

```
18:48:34  [qunar] 错峰等待 90s
18:50:41  [qunar] 抓取完成，得到 0 条记录 · 国际
18:50:45  [qunar] 错峰等待 176s
18:55:38  [qunar] 本轮等待已达预算（已 267s + 需 90s > 300s）
18:55:38  [qunar] 爬取率建议：间隔 30→75 分钟（下界 0.15 < 0.40）
```

也就是说：窗口 19:15 到期 → 下一轮又从头等 267s → 再放弃。
**每轮固定亏 5 分钟换 0 行**，和被修掉之前没本质区别。

修法：按**连续预算用尽次数**指数拉长窗口

```
第 1 次 1200s → 第 2 次 2400s → 第 3 次起封顶 3600s
```

而**一旦真的出了明细就立刻清零**（回到 20 分钟）：
配额是平台侧随机放行的，退避只该惩罚"连续被拒"，
不该把好不容易的放行也拖慢一小时。

三条不变量：

1. 指数增长且**封顶**（不许无限退避成"再也不试"）；
2. **成功清零**：出明细后 streak 归 0、窗口关闭；
3. 窗口内**零等待**（沿用 r949 的判定）。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r952_escalating_backoff.py -q
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers.qunar import QunarCrawler  # noqa: E402


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
