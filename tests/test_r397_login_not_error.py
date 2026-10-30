# -*- coding: utf-8 -*-
"""r397：login 不得并进 error——"该重登"和"该重试"是两回事。

真实库 24h：同程 `path_stats` 报 `error=53`，但查账本这 53 条全是
`path_status='login'`（444 历史行），一条网络/解析/超时错误都没有。
把登录墙算成 error 的后果是：

- 渠道错误率虚高（同程显示 40% 错误），读者以为链路坏了要排查；
- 处置建议错方向：error 对应"重试/看现场"，login 对应"重登"，
  按 error 处理＝让人反复重试一个只有重登能解的状态。

分类桶必须一状态一桶：blocked / soft / empty / unsupported / login /
error 六个语义，互不代偿。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.storage import PriceStorage  # noqa: E402


def _store():
    d = tempfile.mkdtemp(prefix="tm_r397_")
    return PriceStorage(os.path.join(d, "prices.db"))


def _feed(st, status, n=1, path="H5"):
    for _ in range(n):
        st.save_fetch_path("tongcheng", "SHA", "BKK", "2026-11-16",
                           path, status, rows=0)


def test_login_not_counted_as_error():
    st = _store()
    _feed(st, "login", 5)
    _feed(st, "error", 2)
    _feed(st, "timeout", 1)
    n = st.path_stats(hours=24)["tongcheng"]
    assert n["login"] == 5, n
    assert n["error"] == 3, n          # error + timeout 才是真基础设施失败


def test_login_bucket_exists_on_paths_too():
    st = _store()
    _feed(st, "login", 4, path="窗历")
    p = st.path_stats(hours=24)["tongcheng"]["paths"]["窗历"]
    assert p["login"] == 4, p
    assert p["error"] == 0, p


def test_buckets_sum_to_attempts():
    """六个桶必须能加总回 attempts——否则有状态在统计里凭空消失。"""
    st = _store()
    for s in ("ok", "calendar", "empty", "login", "blocked",
              "soft_reject", "unsupported", "error", "timeout",
              "parse_error"):
        _feed(st, s, 2)
    n = st.path_stats(hours=24)["tongcheng"]
    keys = ("ok", "empty", "login", "blocked", "soft", "unsupported",
            "error")
    assert sum(int(n.get(k) or 0) for k in keys) == n["attempts"], n


def test_login_does_not_shrink_rate_denominator():
    """login 仍是失败（不进分母剔除），只是不再冒充 error。"""
    st = _store()
    _feed(st, "ok", 5)
    _feed(st, "login", 5)
    n = st.path_stats(hours=24)["tongcheng"]
    assert n["rate"] == 0.5, n
    assert n["rate_excl_empty"] == 0.5, n
