"""会话可用期（r1063 T93）：量化"登录后能用多久 / 多久被拦"。

用户观察："飞猪登录了可以用一会儿，现在全被拦住了"。
这句话是判断"账号风控"还是"设备/环境风控"的关键指标，但一直只有口头描述。

做法：在路径账的中央入口（`path_note`）里记录**状态转变**：
* 出现 `ok/calendar` → 记「可用时刻」；
* 出现 `login` / `blocked` / `captcha` → 记「失效时刻」。
据此算每个渠道的：
  * `last_ok_at` / `last_lost_at` / `last_window_s`（最近一次"从可用到失效"多久）
  * `windows`（历史各次窗口时长，最多留 20 条）与 `avg_window_s`

为什么放在账本旁边而不是数据库：这是**渠道级事实**，和价格无关；
写进 `user_data/<渠道>/session_window.json`，面板与 CLI 都能读。
"""

from __future__ import annotations

import json
import os
import time

FILE = "session_window.json"
BLOCK_KINDS = ("login", "blocked", "captcha", "face")
OK_KINDS = ("ok", "calendar")
KEEP = 20


def _path(root: str, plat: str) -> str:
    return os.path.join(str(root or "user_data"), str(plat or ""), FILE)


def load(root: str, plat: str) -> dict:
    try:
        with open(_path(root, plat), encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _save(root: str, plat: str, data: dict) -> None:
    try:
        p = _path(root, plat)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


def note(root: str, plat: str, status: str, now: float = None) -> dict:
    """记一次状态；返回更新后的记录（永不抛）。"""
    st = str(status or "").strip()
    if not st:
        return load(root, plat)
    t = float(now if now is not None else time.time())
    d = load(root, plat)
    if st in OK_KINDS:
        d["last_ok_at"] = t
        # 从"失效"回到"可用"= 一次恢复；把上次失效时刻结算成一个窗口
        lost = float(d.get("last_lost_at") or 0)
        if lost and t > lost:
            win = round(t - lost, 1)
            ws = d.setdefault("recover_s", [])
            ws.append(win)
            d["recover_s"] = ws[-KEEP:]
    elif st in BLOCK_KINDS:
        d["last_lost_at"] = t
        d["last_block_kind"] = st
        ok_at = float(d.get("last_ok_at") or 0)
        if ok_at and t >= ok_at:
            win = round(t - ok_at, 1)
            ws = d.setdefault("windows", [])
            ws.append(win)
            d["windows"] = ws[-KEEP:]
            d["last_window_s"] = win
            d["last_window_kind"] = st
            # 记一条人话，面板直接显示
            d["last_window_text"] = "上次可用 %d 秒后被拦（%s）" % (int(win), st)
    else:
        return d
    _save(root, plat, d)
    return d


def summary(root: str, plat: str) -> dict:
    """给面板/CLI 的读数：最近窗口 + 平均窗口。"""
    d = load(root, plat)
    wins = [float(x) for x in (d.get("windows") or []) if x]
    recs = [float(x) for x in (d.get("recover_s") or []) if x]
    return {
        "last_ok_at": d.get("last_ok_at") or 0,
        "last_lost_at": d.get("last_lost_at") or 0,
        "last_block_kind": d.get("last_block_kind") or "",
        "last_window_s": d.get("last_window_s") or 0,
        "last_window_text": d.get("last_window_text") or "",
        "windows": len(wins),
        "avg_window_s": round(sum(wins) / len(wins), 1) if wins else 0,
        "recover_s": len(recs),
        "avg_recover_s": round(sum(recs) / len(recs), 1) if recs else 0,
    }


def _main(argv=None):                             # pragma: no cover - CLI
    import glob
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    root = "user_data"
    pats = sorted(glob.glob(os.path.join(root, "*", FILE)))
    if not pats:
        print("还没有会话窗口数据（跑一轮采集后会自动累积）")
        return 1
    for p in pats:
        plat = os.path.basename(os.path.dirname(p))
        s = summary(root, plat)
        if not (s["windows"] or s["last_ok_at"]):
            continue
        print("%-12s 上次可用 %s 秒后被拦(%s) | 样本 %d 个窗口 平均 %.0fs | "
              "恢复 %d 次 平均 %.0fs"
              % (plat, int(s["last_window_s"]), s["last_block_kind"] or "-",
                 s["windows"], s["avg_window_s"], s["recover_s"],
                 s["avg_recover_s"]))
    return 0


if __name__ == "__main__":                        # pragma: no cover
    raise SystemExit(_main())
