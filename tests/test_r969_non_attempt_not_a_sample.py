# -*- coding: utf-8 -*-
"""r969：**非采集轮不该进成功率样本**（与 is_paced 同一原则）。

实测（2026-11-05 00:10，修好报表读取路径后第一次看见真实数据）：

```
app_zhixing  1027 样本 / 636 成功 / 下界 0.59 / 建议 45 分钟
   日历        0.99(636)     ← 真正的采集通路，几乎满分
   航班明细    0.08(3)
   snap-restore 0.00(266)   ← 登录态快照恢复：基础设施，永远 rows=0
   android-runtime 0.00(52) ← 本渠道不支持的通路，**根本没尝试**
```

`snap-restore` 与 `android-runtime/unsupported` 共 318 条"失败"，
把一条 0.99 的采集通路拖成 0.59，于是建议间隔从 24 分钟涨到 45 分钟。
**这不是渠道被风控，是我方没尝试** —— 与 `is_paced` 当初要解决的问题
（"配额让位"被算成"渠道失败"，账面成功率只有 50%）是同一个病。

所以按同一原则新增 `is_non_attempt()`：
状态是 paced/unsupported、或通路属于基础设施白名单 → 这一轮不算样本。
只要有一条真的打了站点（ok/empty/timeout/soft_reject/login），
这一轮就是真实样本，**失败照实记**（不能借这个口子把真失败洗白）。

跑：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r969_non_attempt_not_a_sample.py -q
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.yield_stats import INFRA_PATHS, is_non_attempt, is_paced  # noqa: E402


def _p(path, status, rows=0):
    return {"path": path, "status": status, "rows": rows}


# ---------------------------------------------------------------------------
# 1. 不算样本的轮次
# ---------------------------------------------------------------------------
def test_only_infra_restore_is_not_a_sample():
    """只有快照恢复：说明的是设备状态，不是站点反应。"""
    assert is_non_attempt([_p("snap-restore", "error")]) is True
    assert is_non_attempt([_p("snap-restore", "ok", rows=0)]) is True


def test_unsupported_route_is_not_a_sample():
    """android-runtime/unsupported = 本渠道不支持该通路，**根本没尝试**。"""
    assert is_non_attempt([_p("android-runtime", "unsupported")]) is True


def test_paced_is_not_a_sample():
    """我方主动让位（配额/节流）：既不是成功也不是失败。"""
    assert is_non_attempt([_p("app-list", "paced")]) is True
    assert is_paced([_p("app-list", "paced")]) is True


def test_infra_plus_unsupported_is_not_a_sample():
    assert is_non_attempt([_p("snap-restore", "error"),
                           _p("android-runtime", "unsupported")]) is True


# ---------------------------------------------------------------------------
# 2. 真实样本（**不许**借这个口子把真失败洗白）
# ---------------------------------------------------------------------------
def test_login_wall_is_a_real_sample():
    assert is_non_attempt([_p("app-login", "login")]) is False


def test_timeout_is_a_real_sample():
    assert is_non_attempt([_p("app-list", "timeout")]) is False


def test_empty_listing_is_a_real_sample():
    assert is_non_attempt([_p("app-list", "empty")]) is False


def test_success_is_a_real_sample():
    assert is_non_attempt([_p("app-calendar", "ok", rows=40)]) is False


def test_mixed_with_real_attempt_is_a_sample():
    """只要有一条真打站点，这轮就是样本（哪怕另一条是基础设施）。"""
    assert is_non_attempt([_p("snap-restore", "error"),
                           _p("app-calendar", "empty")]) is False


def test_no_paths_is_not_non_attempt():
    """没有通路记录时**不**判成"非采集轮"（那是未知，不是结论）。"""
    assert is_non_attempt([]) is False
    assert is_non_attempt(None) is False


# ---------------------------------------------------------------------------
# 3. 边界：白名单必须窄
# ---------------------------------------------------------------------------
def test_infra_list_stays_narrow():
    """基础设施白名单只能装"永远不出行"的通路。

    一旦把 `app-list` / `app-calendar` 这类真数据通路塞进来，
    真实失败就会被静默排除，成功率虚高——那比低估更危险。
    """
    for bad in ("app-list", "app-calendar", "app-detail", "h5", "pc"):
        assert bad not in INFRA_PATHS, "%s 是真数据通路，不能算基础设施" % bad
    assert "snap-restore" in INFRA_PATHS
    assert "android-runtime" in INFRA_PATHS
