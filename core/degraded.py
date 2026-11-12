"""能力降级账本（r1063 T60）：fail-soft 的地方必须**留下可查的证据**。

为什么要有它
------------
"失败就跳过、只写一行日志"在本仓很常见（`except Exception: pass` 几十处）。
问题是：**能力悄悄关掉 ≠ 一切正常**。上轮就是活例子——`geo.fix()` 调错了设备
API，定位固定从来没生效过，只在日志里留过一行 warning，藏了十几轮才被测试撞出来。

约定
----
* 只记**能力级**的降级（"定位没设上""识别后端缺失""UA 与内核不同步"），
  不记单次网络抖动——那会淹没真问题；
* 进程内计数 + 最近一次原因，由 `/api/pacing` 的 `degraded` 段带出去，
  面板上说得出"降级了几类、每类几次、最近为什么"；
* **不改控制流**：调用方照旧 fail-soft，这里只是记账（绝不因为记账失败而报错）。
"""
from __future__ import annotations

import json
import os
import threading
import time

_LOCK = threading.Lock()
_STATE: dict = {}
# 落盘（r1063 T96）：自检等**独立进程**写的降级也要能被面板读到
_FILE_NAME = "degraded.json"
_TTL_S = 24 * 3600


def _path() -> str:
    root = os.environ.get("TM_USER_DATA_DIR") or "user_data"
    return os.path.join(str(root), _FILE_NAME)


def _load_file() -> dict:
    try:
        with open(_path(), encoding="utf-8") as f:
            d = json.load(f) or {}
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_file(data: dict) -> None:
    try:
        p = _path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


def _merge(a: dict, b: dict) -> dict:
    """合并两份账（同键取 `at` 较新的）。"""
    out = dict(a or {})
    for k, v in (b or {}).items():
        cur = out.get(k)
        if not isinstance(cur, dict) or \
                float((v or {}).get("at") or 0) >= float(cur.get("at") or 0):
            out[k] = v
    return out


def note(cap: str, plat: str = "", detail: str = "", *, n: int = 1,
         now: float = None) -> None:
    """记一次能力降级。`cap` 是能力名（英文短横线），`plat` 可选。"""
    key = (str(cap or "").strip(), str(plat or "").strip())
    if not key[0]:
        return
    try:
        add = max(1, int(n or 1))
    except (TypeError, ValueError):
        add = 1
    ts = float(now if now is not None else time.time())
    try:
        with _LOCK:
            rec = _STATE.setdefault(key, {"n": 0, "last": "", "at": 0.0})
            rec["n"] = int(rec.get("n") or 0) + add
            if detail:
                rec["last"] = str(detail)[:160]
            rec["at"] = ts
    except Exception:
        pass                    # 记账失败不许影响调用方
    # 落盘（r1063 T96）：独立进程（自检/CLI）写的降级也要能被面板读到
    try:
        disk = _load_file()
        _k = "%s|%s" % key
        _cur = disk.get(_k) or {}
        disk[_k] = {"n": int(_cur.get("n") or 0) + add,
                    "last": (str(detail)[:160] if detail
                             else str(_cur.get("last") or "")),
                    "at": ts,
                    "cap": key[0], "plat": key[1]}
        _save_file(disk)
    except Exception:
        pass


def snapshot() -> dict:
    """按能力聚合：`{cap: {"n": N, "plats": {plat: n}, "last": 原因, "at": ts}}`。"""
    with _LOCK:
        items = [(k, dict(v)) for k, v in _STATE.items()]
    # 合并落盘账（TTL 内的），按 at 取较新者
    try:
        _now = time.time()
        for k, v in _load_file().items():
            if not isinstance(v, dict):
                continue
            if (_now - float(v.get("at") or 0)) > _TTL_S:
                continue
            key = (str(v.get("cap") or ""), str(v.get("plat") or ""))
            if not key[0]:
                continue
            cur = dict(dict(items).get(key) or {})
            if not cur or float(v.get("at") or 0) >= float(cur.get("at") or 0):
                items = [it for it in items if it[0] != key]
                items.append((key, {"n": int(v.get("n") or 0),
                                    "last": str(v.get("last") or ""),
                                    "at": float(v.get("at") or 0)}))
    except Exception:
        pass
    out = {}
    for (cap, plat), rec in items:
        row = out.setdefault(cap, {"n": 0, "plats": {}, "last": "",
                                   "at": 0.0})
        row["n"] += int(rec.get("n") or 0)
        if plat:
            row["plats"][plat] = int(row["plats"].get(plat) or 0) + int(
                rec.get("n") or 0)
        if rec.get("last") and float(rec.get("at") or 0) >= float(
                row.get("at") or 0):
            row["last"] = rec["last"]
            row["at"] = float(rec.get("at") or 0)
    return out


def reset() -> None:
    with _LOCK:
        _STATE.clear()


def total() -> int:
    with _LOCK:
        return sum(int((v or {}).get("n") or 0) for v in _STATE.values())
