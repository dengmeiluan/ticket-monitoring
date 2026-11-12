"""策略成效账本（r1063 T51）：换道与会话重建的**历史成效**，重启不丢。

为什么需要
----------
`pacing` 里的计数是**进程内**的：重启归零。于是用户永远回答不了那个最关键的问题
——「这条自动策略对我到底有没有用？」。要么凭感觉开，要么干脆关掉。

记什么（只记**能证明**的，不猜）
--------------------------------
* 换道：当天预置次数 / 换道次数 / **回采条数**（回采是"救回了多少条"的硬证据）；
* 会话重建：当天重建次数 / **重建后下一轮恢复的次数**（恢复才算真有用。

  判据：重建后该渠道第一次出数 → `recovered`。

存储
----
一份小 JSON（`user_data/strategy_ledger.json`），只留最近 `KEEP_DAYS` 天：

```json
{"days": {"2026-11-07": {"failover": {"preloads": 2, "switches": 1, "rows": 6},
                          "reset": {"n": 1, "recovered": 1}}},
 "pending": {"fliggy": "2026-11-07"}}
```

`pending` 记「这家渠道刚重建过、还没看到下一轮结果」——它让 `recovered` 有据可依，
而不是靠猜。
"""
from __future__ import annotations

import json
import os
import time

LEDGER = "strategy_ledger.json"
KEEP_DAYS = 14


def ledger_path(root: str = "user_data") -> str:
    return os.path.join(str(root or "user_data"), LEDGER)


def _day(now: float = None) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(
        float(now if now is not None else time.time())))


def _load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(path: str, data: dict) -> None:
    try:
        d = os.path.dirname(os.path.abspath(path))
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except Exception:
        pass                      # 账本坏掉不许影响采集


def _prune(data: dict, keep: int = KEEP_DAYS) -> dict:
    days = data.get("days")
    if not isinstance(days, dict):
        return data
    keys = sorted(days)
    for k in keys[:-max(1, int(keep or KEEP_DAYS))]:
        days.pop(k, None)
    return data


def _bump(data: dict, day: str, sec: str, key: str, add) -> None:
    days = data.setdefault("days", {})
    row = days.setdefault(day, {})
    part = row.setdefault(sec, {})
    try:
        part[key] = (part.get(key) or 0) + add
    except TypeError:
        part[key] = add


def record_failover(*, preloads: int = 0, switches: int = 0, rows: int = 0,
                    root: str = "user_data", now: float = None) -> None:
    """记一天的换道成效（预置/换道/回采）。"""
    path = ledger_path(root)
    data = _load(path)
    day = _day(now)
    for k, v in (("preloads", preloads), ("switches", switches),
                 ("rows", rows)):
        if v:
            _bump(data, day, "failover", k, int(v))
    _prune(data)
    _save(path, data)


def record_reset(plat: str, *, root: str = "user_data",
                 now: float = None) -> None:
    """记一次会话重建，并把该渠道挂进 `pending`（等下一轮结果判"有用没有"）。"""
    path = ledger_path(root)
    data = _load(path)
    day = _day(now)
    _bump(data, day, "reset", "n", 1)
    pend = data.setdefault("pending", {})
    if isinstance(pend, dict):
        pend[str(plat or "")] = day
    _prune(data)
    _save(path, data)


def mark_recovered(plat: str, *, root: str = "user_data",
                   now: float = None) -> bool:
    """该渠道**重建之后**第一次出数：记一次 recovered 并清掉 pending。

    返回是否真的记了（没 pending 就返回 False——不认识的"恢复"不算数）。
    """
    key = str(plat or "")
    path = ledger_path(root)
    data = _load(path)
    pend = data.get("pending")
    if not isinstance(pend, dict) or key not in pend:
        return False
    day = str(pend.pop(key) or "") or _day(now)
    days = data.setdefault("days", {})
    row = days.setdefault(day, {})
    part = row.setdefault("reset", {})
    part["recovered"] = int(part.get("recovered") or 0) + 1
    _prune(data)
    _save(path, data)
    return True


def clear_pending(plat: str, *, root: str = "user_data") -> None:
    """该渠道又失败了/不重建了：撤掉 pending，别把后来的成功算成"重建救回来的"。"""
    path = ledger_path(root)
    data = _load(path)
    pend = data.get("pending")
    if isinstance(pend, dict) and str(plat or "") in pend:
        pend.pop(str(plat or ""), None)
        _save(path, data)


def summary(*, days: int = 7, root: str = "user_data",
            now: float = None) -> dict:
    """最近 N 天的成效汇总（给界面/CLI 用）。"""
    n = max(1, int(days or 7))
    end = float(now if now is not None else time.time())
    keep = []
    for i in range(n):
        keep.append(_day(end - i * 86400))
    data = _load(ledger_path(root))
    all_days = data.get("days") if isinstance(data.get("days"), dict) else {}
    fail = {"preloads": 0, "switches": 0, "rows": 0}
    res = {"n": 0, "recovered": 0}
    per_day = {}
    for d in keep:
        row = all_days.get(d) or {}
        f = row.get("failover") or {}
        r = row.get("reset") or {}
        if f or r:
            per_day[d] = {"failover": dict(f), "reset": dict(r)}
        for k in fail:
            fail[k] += int(f.get(k) or 0)
        for k in res:
            res[k] += int(r.get(k) or 0)
    return {"days": n, "from": keep[-1] if keep else "", "to": keep[0] if keep
            else "", "failover": fail, "reset": res, "per_day": per_day,
            "recovered_ratio": (round(res["recovered"] / res["n"], 2)
                                if res["n"] else None)}

def _main(argv=None):                            # pragma: no cover - CLI
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    days = 7
    root = "user_data"
    for a in argv:
        if str(a).isdigit():
            days = int(a)
        elif a and not str(a).startswith("-"):
            root = str(a)
    got = summary(days=days, root=root)
    f, r = got["failover"], got["reset"]
    print("=== 策略成效（近 %d 天：%s ~ %s）==="
          % (got["days"], got["from"], got["to"]))
    print("换道：预置 %d 次 · 换道 %d 次 · 救回 %d 条"
          % (f["preloads"], f["switches"], f["rows"]))
    extra = ("" if got["recovered_ratio"] is None
             else "（恢复率 %d%%）" % round(got["recovered_ratio"] * 100))
    print("会话重建：%d 次，其中 %d 次下一轮恢复%s"
          % (r["n"], r["recovered"], extra))
    if not got["per_day"]:
        print("（这段时间没有记录）")
    return 0


if __name__ == "__main__":                       # pragma: no cover
    raise SystemExit(_main())
