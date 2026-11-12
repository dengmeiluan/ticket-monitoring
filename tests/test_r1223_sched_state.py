# -*- coding: utf-8 -*-
"""r1223：自适应退避在"首轮"从未生效——因为读了尚未赋值的局部变量。

现场（干净副本日志，2026-11-10 14:35:42）：

```
[节流] 计划 0 次渠道查询（快层 0 / 慢层 0 / TTL 内 0）；实际未发 0 次 …
[WARNING] [节流] 自适应退避计算失败: name 'sched_state' is not defined
```

`sched_state` 是 `main()` 的局部变量（约 4227 行赋值），而第一轮扫描可能在那之前
就开跑 → 那段 `sched_state.get(...)` 抛 `NameError`，被 `except` 吞成一行 warning。
结果：**"这一轮有多不顺 → 下一轮推远一点"这条保护，在首轮/空轮里从来没算过。**

契约：
1. 模块级 `_SCHED_STATE` 存在且可写（永远不 NameError）；
2. `_sched_state_now()` 返回的就是它（同一对象，不是拷贝）；
3. 扫描闭包里不再直接读裸 `sched_state`。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import main as M  # noqa: E402

MAIN_SRC = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()


def test_module_state_exists_and_writable():
    assert isinstance(M._SCHED_STATE, dict)
    for k in ("interval_minutes", "jitter_minutes", "backoff_minutes"):
        assert k in M._SCHED_STATE, k
    M._SCHED_STATE["backoff_minutes"] = 7
    assert M._SCHED_STATE["backoff_minutes"] == 7
    M._SCHED_STATE["backoff_minutes"] = 0


def test_accessor_returns_same_object():
    assert M._sched_state_now() is M._SCHED_STATE


def test_backoff_block_no_longer_reads_bare_local():
    i = MAIN_SRC.find("from core.pacing import round_backoff_minutes as _rbm")
    assert i > 0
    seg = MAIN_SRC[i:i + 700]
    assert "_sched_state_now()" in seg, "退避分支没走模块级容器"
    assert "sched_state.get(" not in seg, "仍在读可能未赋值的局部 sched_state"
    assert 'sched_state["backoff_minutes"]' not in seg


def test_round_backoff_is_pure():
    """`round_backoff_minutes` 的语义：**额外**延后分钟数，有界（默认封顶 240）。"""
    from core.pacing import round_backoff_minutes as rb
    assert rb(30, 0, 0) == 0                    # 全绿 → 不延时
    assert rb(30, 1, 0) == 30                   # 1–2 次受阻 → 延后一个间隔
    assert rb(30, 5, 3) == 60                   # ≥3 次受阻 → 延后两个间隔
    assert rb(200, 5, 5) == 240                 # 封顶 240：坏运气不会把监控冻住
    assert rb(0, 5, 5) == 0                     # 间隔为 0 时不延时
