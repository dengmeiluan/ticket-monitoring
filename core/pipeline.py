"""跨查询流水线（r1063 T29）：把「一条查询等齐所有渠道」改成「渠道互斥、跨查询重叠」。

要解决的问题（真实数据）
------------------------
`data/pulse.json` 48 轮实测：墙钟中位 **253s**，单渠道耗时中位 25–50s，
**墙钟 / 最慢渠道 = 5.44**。慢的不是"单查询内等某一家"，而是**每条查询各排一次队**：
第 2 条查询必须等第 1 条的最后一家收工才开始。

模型
----
现行为（栅栏）：`墙钟 = Σ_查询 max_渠道(耗时)`
流水线：      `墙钟 ≈ max_渠道 Σ_查询(耗时) / K`（K = 同时在飞的渠道数）

**不改变任何单渠道速率**：同一渠道任意时刻最多一个任务在飞（互斥），
所以限速/会话/指纹语义一个都没动——省掉的全部是"别的渠道在等"的空档。

本模块只做调度，不碰采集：
  * 输入：`queries = [(标签, [渠道...]), ...]` + 一个 `fetch(标签, 渠道)` 回调；
  * 输出：`{标签: [(渠道, 结果), ...]}`（顺序 = 探针顺序，便于调用方按原顺序结算）；
  * 硬约束：**同渠道互斥**、每个任务恰好执行一次、异常不炸整轮。

它是纯函数式调度器（不 import 采集/存储），所以能在单测里用假 `fetch` 把
"互斥、不双采、结果齐"这三件事钉死——这是接进主循环之前必须先证明的。
"""
from __future__ import annotations

import concurrent.futures
import threading

DEFAULT_WORKERS = 0          # 0 = 按渠道数自动


def _plan(queries):
    """展开成 `[(查询标签, 渠道)]` 任务序列（保持提交顺序）。"""
    out = []
    for label, chans in (queries or ()):
        seen = set()
        for c in (chans or ()):
            c = str(c)
            if c in seen:
                continue
            seen.add(c)
            out.append((label, c))
    return out


def run(queries, fetch, *, workers=DEFAULT_WORKERS, on_task=None):
    """跨查询调度：渠道互斥 + 跨查询重叠。

    `workers` 是**同时在飞的渠道数**上限（不是线程数上限的语义差异：两者等价，
    因为一个渠道同一时刻只能有一个任务）。`workers<=0` → 取"本批渠道总数"。
    返回 `{标签: [(渠道, 结果|异常), ...]}`，标签顺序 = 输入顺序。
    """
    tasks = _plan(queries)
    buckets = {label: [] for label, _ in (queries or ())}
    if not tasks:
        return buckets
    chans = {c for _l, c in tasks}
    k = int(workers or 0)
    if k <= 0:
        k = max(1, len(chans))
    k = max(1, min(k, len(tasks)))

    lock = threading.Lock()
    busy = set()                       # 正在飞的渠道
    done_evt = threading.Condition(lock)
    pending = list(tasks)              # 待领任务（保持顺序）
    remaining = [len(tasks)]

    def _take():
        """领一个"渠道空闲"的任务（调用方持锁）。"""
        for i, (label, chan) in enumerate(pending):
            if chan in busy:
                continue
            busy.add(chan)
            pending.pop(i)
            return label, chan
        return None

    def _worker():
        while True:
            with done_evt:
                while True:
                    if remaining[0] <= 0:
                        return
                    got = _take()
                    if got is not None:
                        break
                    # 全部渠道都在忙：等有人收工（或全部做完）
                    done_evt.wait(timeout=0.5)
            label, chan = got
            try:
                res = fetch(label, chan)
            except BaseException as e:            # 单个任务失败不炸整轮
                res = e
            with done_evt:
                busy.discard(chan)
                buckets[label].append((chan, res))
                remaining[0] -= 1
                if on_task is not None:
                    try:
                        on_task(label, chan, res)
                    except Exception:
                        pass
                done_evt.notify_all()

    threads = [threading.Thread(target=_worker, daemon=True) for _ in range(k)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # 桶内按提交顺序排好（并发下 append 顺序随机，调用方要确定性）
    order = {}
    for idx, (label, _c) in enumerate(tasks):
        order.setdefault(label, {})[_c] = idx
    for label, items in buckets.items():
        o = order.get(label) or {}
        items.sort(key=lambda kv: o.get(kv[0], 1 << 30))
    return buckets


def critical_path(queries, lat_of, *, workers=DEFAULT_WORKERS):
    """找出「谁在决定整轮时长」——比"平均耗时"有用得多。

    三种典型结论：
      * `same_channel`：每条查询都由**同一个渠道**决定时长 → 流水线**没有收益**
        （那个渠道本身是串行瓶颈，换调度省不下它的工作量）；
      * `varies`：不同查询由不同渠道拖着 → 流水线有收益（空档能被别的查询填上）；
      * `none`：没有任何耗时数据。

    返回 `{kind, channel, share, gain_est}`：`share` 是该渠道在"每查询最长耗时"里
    的占比，`gain_est` 同 `potential()` 的估计倍数。
    """
    tasks = _plan(queries)
    if not tasks:
        return {"kind": "none", "channel": "", "share": 0.0, "gain_est": 0.0}
    per_chan = {}
    slowest_count = {}
    for label, chans in (queries or ()):
        best, best_c = -1.0, ""
        for c in (chans or ()):
            c = str(c)
            try:
                v = float(lat_of(label, c) or 0)
            except Exception:
                v = 0.0
            if v > best:
                best, best_c = v, c
        if best_c:
            slowest_count[best_c] = slowest_count.get(best_c, 0) + 1
    for label, chan in tasks:
        try:
            per_chan[chan] = per_chan.get(chan, 0.0) + float(
                lat_of(label, chan) or 0)
        except Exception:
            per_chan[chan] = per_chan.get(chan, 0.0)
    top = max(slowest_count.items(), key=lambda kv: kv[1]) if slowest_count else ("", 0)
    share = (top[1] / sum(slowest_count.values())) if slowest_count else 0.0
    est = potential(queries, lat_of, workers=workers)
    kind = "same_channel" if share >= 0.6 else "varies"
    return {"kind": kind, "channel": top[0], "share": round(share, 2),
            "critical_total": round(per_chan.get(top[0], 0.0), 1),
            "gain_est": est["gain"]}


def potential(queries, lat_of, *, workers=DEFAULT_WORKERS):
    """算"现行为 vs 流水线"的预期墙钟（秒），只用于收益预估与单测。

    `lat_of(标签, 渠道)` 给该任务的历史耗时；缺省返回 0（等于不参与）。
    """
    tasks = _plan(queries)
    if not tasks:
        return {"barrier": 0.0, "pipeline": 0.0, "gain": 0.0}
    lat = {}
    for label, chan in tasks:
        try:
            lat[(label, chan)] = max(0.0, float(lat_of(label, chan) or 0))
        except Exception:
            lat[(label, chan)] = 0.0
    barrier = 0.0
    for label, chans in (queries or ()):
        vals = [lat.get((label, str(c)), 0.0) for c in (chans or ())]
        if vals:
            barrier += max(vals)
    chans = {c for _l, c in tasks}
    k = int(workers or 0) or max(1, len(chans))
    per_chan = {}
    for label, chan in tasks:
        per_chan[chan] = per_chan.get(chan, 0.0) + lat[(label, chan)]
    pipeline = max(per_chan.values()) if per_chan else 0.0
    # 每个渠道的总工作量决定下界；实际还受 K 与任务不均影响，给个保守上界
    total = sum(per_chan.values())
    pipeline = max(pipeline, total / max(1, min(k, len(chans))))
    gain = (barrier / pipeline) if pipeline else 0.0
    return {"barrier": round(barrier, 1), "pipeline": round(pipeline, 1),
            "gain": round(gain, 2)}


def run_with_pool(queries, fetch, *, workers=DEFAULT_WORKERS):
    """线程池版本（任务数很大时更省线程）；语义与 `run` 完全一致。

    保留两套实现是为了单测能互相印证：`run` 用手写线程演示互斥逻辑，
    `run_with_pool` 用标准库；两者的 `potential` 估计必须对得上。
    """
    tasks = _plan(queries)
    buckets = {label: [] for label, _ in (queries or ())}
    if not tasks:
        return buckets
    chans = {c for _l, c in tasks}
    k = int(workers or 0) or max(1, len(chans))
    lock = threading.Lock()
    busy = set()
    cond = threading.Condition(lock)
    pending = list(tasks)

    def _one():
        while True:
            with cond:
                while True:
                    for i, (label, chan) in enumerate(pending):
                        if chan in busy:
                            continue
                        busy.add(chan)
                        pending.pop(i)
                        break
                    else:
                        if not pending:
                            return
                        cond.wait(timeout=0.5)
                        continue
                    break
            try:
                res = fetch(label, chan)
            except BaseException as e:
                res = e
            with cond:
                busy.discard(chan)
                buckets[label].append((chan, res))
                cond.notify_all()

    with concurrent.futures.ThreadPoolExecutor(max_workers=k) as ex:
        futs = [ex.submit(_one) for _ in range(k)]
        for f in futs:
            f.result()
    order = {}
    for idx, (label, c) in enumerate(tasks):
        order.setdefault(label, {})[c] = idx
    for label, items in buckets.items():
        o = order.get(label) or {}
        items.sort(key=lambda kv: o.get(kv[0], 1 << 30))
    return buckets
