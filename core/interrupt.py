"""手动中止：`python -m core.interrupt [--clear]`（r1063 T172）

objective 里"**一切可中断**"缺一块：以前只能等一轮自己跑完（一条航线最多
300 秒，一轮七八条航线就是十几分钟）。这个模块提供一个**进程内标志**：

* `python -m core.interrupt`       → 请求中止（下一次航线边界生效）
* `python -m core.interrupt --clear` → 撤销请求
* `POST /api/run/stop` 同效（面板/脚本都能用）

**诚实边界**：只在**航线之间**生效——不强杀线程。原因很实在：正在跑的浏览器
或模拟器操作没有安全中断点，硬杀会留下半截状态（页面残挂、设备被占）。
所以中止的语义是"**不再派发下一条航线**"，正在飞的那条会自然跑完并照常落库。
"""
from __future__ import annotations

import json
import os
import threading
import time

_LOCK = threading.Lock()
_STATE = {"requested": False, "at": 0.0, "by": ""}

#: 请求的有效期（秒）。防止"昨天点过一次"在今天悄悄吞掉一轮。
TTL_S = 900


def _marker_path() -> str:
    """落盘标记路径（跨进程通道）。

    监控进程与 CLI 是两个进程，只靠内存标志的话 CLI 那条路等于没接线
    （实测：webui 里置位成功，另开进程读到 false）。
    """
    root = os.environ.get("TM_USER_DATA_DIR") or ""
    if not root:
        try:
            import re as _re
            txt = open("config.yaml", encoding="utf-8").read()
            m = _re.search(r"(?m)^\s*user_data_dir:\s*(\S+)", txt)
            root = m.group(1).strip("\"'") if m else "user_data"
        except Exception:
            root = "user_data"
    return os.path.join(str(root), ".interrupt.json")


def _write_marker(rec: dict) -> None:
    try:
        p = _marker_path()
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
    except Exception:
        pass


def _read_marker() -> dict:
    try:
        with open(_marker_path(), encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _drop_marker() -> None:
    try:
        os.remove(_marker_path())
    except Exception:
        pass


def request(by: str = "") -> dict:
    """请求中止本轮（航线边界生效）。**内存 + 落盘**双写。"""
    with _LOCK:
        _STATE.update({"requested": True, "at": time.time(), "by": str(by)})
        rec = dict(_STATE)
    _write_marker(rec)
    return rec


def clear() -> dict:
    with _LOCK:
        _STATE.update({"requested": False, "at": 0.0, "by": ""})
        rec = dict(_STATE)
    _drop_marker()
    return rec


def requested() -> bool:
    """是否**有效**的中止请求（内存或落盘标记；过期自动失效）。"""
    with _LOCK:
        if _STATE["requested"]:
            if time.time() - float(_STATE["at"] or 0) <= TTL_S:
                return True
            _STATE.update({"requested": False, "at": 0.0, "by": ""})
    rec = _read_marker()
    if not rec.get("requested"):
        return False
    try:
        at = float(rec.get("at") or 0)
    except (TypeError, ValueError):
        at = 0.0
    if time.time() - at > TTL_S:
        _drop_marker()
        return False
    return True


def state() -> dict:
    with _LOCK:
        st = dict(_STATE)
    rec = _read_marker()
    if rec.get("requested") and not st.get("requested"):
        st.update({"requested": True, "at": rec.get("at") or 0.0,
                   "by": str(rec.get("by") or "")})
    st["active"] = requested()
    st["ttl_s"] = TTL_S
    st["marker"] = _marker_path()
    return st


def main(argv=None):                                    # pragma: no cover
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    if "--clear" in argv:
        print("已撤销中止请求：", json.dumps(clear(), ensure_ascii=False))
        return 0
    if "--state" in argv:
        print(json.dumps(state(), ensure_ascii=False))
        return 0
    print("已请求中止（航线边界生效）：",
          json.dumps(request(by="cli"), ensure_ascii=False))
    print("说明：不强杀线程——正在飞的那条航线会跑完并照常落库。")
    return 0


if __name__ == "__main__":                              # pragma: no cover
    raise SystemExit(main())
