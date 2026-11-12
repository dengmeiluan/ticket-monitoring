"""渠道状态记忆（r1063 T69）：停服 / 登录墙，浏览器与 App **共用一套**。

为什么单独成模块：`crawlers/base.py::BaseCrawler`（浏览器）与
`crawlers/app_base.py::AppCrawler`（App）是**两个互不继承的类**，把记忆写进
任一边，另一边就拿不到。而"这条通路停服了""这家要登录"是**渠道级事实**，
与走浏览器还是走 App 无关。

接口（都很薄，任一侧包一层即可）：
    path_for(root, name, kind)      → 记忆文件路径
    until(root, name, kind)         → 到期时间（0 = 没记过）
    mark(root, name, kind, ...)     → 记一笔（可 permanent）
    clear(root, name, kind)         → 清掉
"""
from __future__ import annotations

import json
import os
import time

FILES = {"service_closed": "service_closed.json",
         "login_wall": "login_wall.json"}
WINDOWS = {"service_closed": 6 * 3600, "login_wall": 2 * 3600}


def path_for(root: str, name: str, kind: str) -> str:
    fn = FILES.get(str(kind) or "", "%s.json" % kind)
    return os.path.join(str(root or "user_data"), str(name or ""), fn)


def until(root: str, name: str, kind: str) -> float:
    """到期时间（0 = 没记过）。读不到就当没记过——不吓唬自己。"""
    try:
        with open(path_for(root, name, kind), encoding="utf-8") as f:
            return float((json.load(f) or {}).get("until") or 0)
    except Exception:
        return 0.0


def detail(root: str, name: str, kind: str) -> str:
    try:
        with open(path_for(root, name, kind), encoding="utf-8") as f:
            return str((json.load(f) or {}).get("detail") or "")
    except Exception:
        return ""


def mark(root: str, name: str, kind: str, text: str = "", *,
         window_s: float = 0, permanent: bool = False) -> None:
    win = 100 * 365 * 86400.0 if permanent else float(
        window_s or WINDOWS.get(str(kind) or "", 3600))
    try:
        p = path_for(root, name, kind)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"until": time.time() + win,
                       "detail": str(text)[:200],
                       "permanent": bool(permanent),
                       "at": time.time()}, f, ensure_ascii=False)
    except Exception:
        pass


def clear(root: str, name: str, kind: str) -> None:
    try:
        os.remove(path_for(root, name, kind))
    except Exception:
        pass


def is_permanent(root: str, name: str, kind: str = "service_closed") -> bool:
    try:
        with open(path_for(root, name, kind), encoding="utf-8") as f:
            rec = json.load(f) or {}
        return bool(rec.get("permanent")) and float(
            rec.get("until") or 0) > time.time()
    except Exception:
        return False
