"""会话重建（r1063 T47）：连续被拦时，把该渠道的**浏览器档案**换一份干净的。

为什么做这条
-----------
用户实机观察：**飞猪验证码过不去，但清除数据之后又能看到机票了**。
这是很典型的一种：影子档案（cookie / localStorage / 各类持久化指纹状态）被
风控"记住"了，换一份干净档案反而回到"匿名但可信"的状态。

纪律（每一条都是踩过坑换来的）
------------------------------
* **不删，只挪**：整个目录改名为 `<plat>.bak_<时间>_<原因>`，随时可还原；
* **保住我们自己的账**：`policy_state.json`（熔断/停手）、`yield_stats.json`、
  `login_ledger.json` 会**拷回新档案**——重置的是浏览器身份，不是我们的学习成果；
* **有上限**：每日次数 + 冷却。重置必然丢 cookie（可能要重登），一天反复重置
  等于把账号往死里打；
* **判据明确**：只统计"被拦 / 挑战"类失败，普通超时不算（那是网络问题，
  重置档案没用，只会白丢登录态）。
"""
from __future__ import annotations

import os
import shutil
import time

# 这些是**我们的**状态，重置时必须拷回新档案（不然熔断/统计/登录台账全丢）
STATE_FILES = ("policy_state.json", "yield_stats.json", "login_ledger.json",
               "first_party_sets.json")


def profile_dir(plat: str, root: str = "user_data") -> str:
    return os.path.join(root, str(plat))


def _ts() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def _keep_cfg(plat: str, default: int = 3) -> int:
    """保留几份备份：**参数层优先**（`session_reset.keep`），否则用调用方默认值。

    读点放在这里而不是上层，是因为 `prune()` 也会被手动还原路径直接调用。
    """
    try:
        from core import strategy_params as _sp
        return int(float(_sp.resolve("session_reset.keep",
                                     plat=str(plat or "")).value))
    except Exception:
        return int(default or 3)


def list_backups(plat: str, root: str = "user_data") -> list:
    """列出该渠道的历史备份（新 → 旧）。"""
    d = os.path.abspath(root)
    if not os.path.isdir(d):
        return []
    pre = "%s.bak_" % plat
    out = []
    for name in os.listdir(d):
        if name.startswith(pre):
            p = os.path.join(d, name)
            if os.path.isdir(p):
                out.append({"name": name, "path": p,
                            "mtime": os.path.getmtime(p)})
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out


def _carry_state(old: str, new: str) -> list:
    """把我们自己的状态文件拷到新档案（失败不阻断）。"""
    kept = []
    for fn in STATE_FILES:
        src = os.path.join(old, fn)
        if not os.path.isfile(src):
            continue
        try:
            shutil.copy2(src, os.path.join(new, fn))
            kept.append(fn)
        except OSError:
            continue
    return kept


def backup(plat: str, root: str = "user_data", *, reason: str = "manual",
           keep: int = 3) -> dict:
    """把 `<root>/<plat>` 挪成备份并建一份新档案。返回可读的结果字典。

    幂等：目录不存在时什么都不做（返回 `{"ok": False, "why": "没有档案"}`），
    因为"重置一个不存在的档案"没有意义，也不该在界面上显示成成功。
    """
    old = profile_dir(plat, root)
    if not os.path.isdir(old):
        return {"ok": False, "plat": plat, "why": "没有档案，不需要重置"}
    safe_reason = "".join(c for c in str(reason) if c.isalnum() or c in "-_")[:16]
    base = "%s.bak_%s_%s" % (plat, _ts(), safe_reason or "manual")
    new_name = base
    new_path = os.path.join(os.path.abspath(root), new_name)
    # 同一秒内连续重置（或手动 + 自动撞一起）会撞名 → 加去重后缀，
    # 不要让它变成 "WinError 183 无法创建该文件" 这种看不懂的失败。
    _n = 1
    while os.path.exists(new_path):
        _n += 1
        new_name = "%s.%d" % (base, _n)
        new_path = os.path.join(os.path.abspath(root), new_name)
    try:
        os.rename(old, new_path)
    except OSError as e:
        return {"ok": False, "plat": plat, "why": "挪档案失败：%s" % str(e)[:80]}
    try:
        os.makedirs(old, exist_ok=True)
    except OSError as e:
        # 连新档案都建不起来就把旧的挪回去，别留下"没有档案"的坑
        try:
            os.rename(new_path, old)
        except OSError:
            pass
        return {"ok": False, "plat": plat, "why": "建新档案失败：%s" % str(e)[:80]}
    kept = _carry_state(new_path, old)
    # 调用方显式给了 keep 就用它；没给才读参数层（`session_reset.keep`）
    pruned = prune(plat, root,
                   keep=int(keep) if keep else _keep_cfg(plat, 3))
    return {"ok": True, "plat": plat, "backup": new_name, "kept_state": kept,
            "pruned": pruned, "at": time.time()}


def restore(plat: str, root: str = "user_data", name: str = "") -> dict:
    """把某份备份还原回去（当前档案会先被挪开，绝不覆盖）。"""
    backups = list_backups(plat, root)
    if not backups:
        return {"ok": False, "plat": plat, "why": "没有可用备份"}
    target = None
    for b in backups:
        if not name or b["name"] == name:
            target = b
            break
    if target is None:
        return {"ok": False, "plat": plat, "why": "找不到备份 %s" % name}
    cur = profile_dir(plat, root)
    moved = ""
    if os.path.isdir(cur):
        moved = "%s.discard_%s" % (plat, _ts())
        try:
            os.rename(cur, os.path.join(os.path.abspath(root), moved))
        except OSError as e:
            return {"ok": False, "plat": plat,
                    "why": "腾位置失败：%s" % str(e)[:80]}
    try:
        os.rename(target["path"], cur)
    except OSError as e:
        return {"ok": False, "plat": plat, "why": "还原失败：%s" % str(e)[:80]}
    return {"ok": True, "plat": plat, "restored": target["name"],
            "discarded": moved}


def prune(plat: str, root: str = "user_data", *, keep: int = 0) -> list:
    """只保留最近 `keep` 份备份（缺省读参数层），多出来的删掉。返回删掉的名字。"""
    keep = max(1, int(keep if keep else _keep_cfg(plat, 3)))
    backups = list_backups(plat, root)
    removed = []
    for b in backups[keep:]:
        try:
            shutil.rmtree(b["path"])
            removed.append(b["name"])
        except OSError:
            continue
    return removed


def should_reset(plat: str, *, fails: int, last_reset_ts: float = 0.0,
                 resets_today: int = 0, now: float = None,
                 config: dict = None) -> tuple:
    """该不该自动重置。返回 `(bool, 原因)`——原因要能直接显示给人看。

    三把闸：开关、冷却、每日上限。**任何一把没打开都不重置**（重置会丢登录态，
    代价高于收益时宁可让它继续被拦着）。
    """
    from core import strategy_params as sp

    now = time.time() if now is None else now
    if not sp.switch_on("session_reset.enabled", plat=plat):
        return False, "会话重建开关已关"
    try:
        need = int(sp.resolve("session_reset.after_fails", plat=plat).value)
    except Exception:
        need = 3
    if int(fails or 0) < max(1, need):
        return False, "连续被拦 %d 次，未到阈值 %d" % (int(fails or 0), need)
    try:
        cd = float(sp.resolve("session_reset.cooldown_s", plat=plat).value)
    except Exception:
        cd = 21600.0
    if last_reset_ts and (now - float(last_reset_ts)) < cd:
        left = int((cd - (now - float(last_reset_ts))) / 60)
        return False, "冷却中，还要 %d 分钟" % max(0, left)
    try:
        cap = int(sp.resolve("session_reset.daily_cap", plat=plat).value)
    except Exception:
        cap = 2
    if int(resets_today or 0) >= max(1, cap):
        return False, "今日已重置 %d 次（上限 %d）" % (int(resets_today or 0), cap)
    return True, "连续被拦 %d 次，换一份干净档案" % int(fails or 0)

def auto_step(state: dict, plat: str, root: str = "user_data", *,
              blocked: bool = False, now: float = None) -> dict:
    """跑完一轮后调用一次：累计"连续被拦"，满足条件就真的换一份干净档案。

    `state` 是调用方（main）持有的进程内字典，形如::

        {"fails": {plat: n}, "last": {plat: ts}, "day": {plat: [日期, 次数]}}

    返回 `{"acted": bool, "why": str, "result": {...}}`，**永远不抛**——
    会话维护不该把一轮采集搞挂。
    """
    import datetime as _dt

    now = time.time() if now is None else now
    st = state if isinstance(state, dict) else {}
    fails = st.setdefault("fails", {})
    last = st.setdefault("last", {})
    day = st.setdefault("day", {})

    if not blocked:
        # 没被拦 → 连续计数清零（"连续"才有意义）
        if fails.get(plat):
            fails[plat] = 0
        return {"acted": False, "why": "本轮没被拦"}

    fails[plat] = int(fails.get(plat) or 0) + 1
    today = _dt.date.today().isoformat()
    rec = day.get(plat) or [today, 0]
    if rec[0] != today:
        rec = [today, 0]
    day[plat] = rec

    ok, why = should_reset(plat, fails=fails[plat],
                           last_reset_ts=float(last.get(plat) or 0.0),
                           resets_today=int(rec[1] or 0), now=now)
    if not ok:
        return {"acted": False, "why": why}
    rep = backup(plat, root, reason="auto", keep=_keep_cfg(plat, 3))
    if rep.get("ok"):
        last[plat] = now
        rec[1] = int(rec[1] or 0) + 1
        day[plat] = rec
        fails[plat] = 0
    return {"acted": bool(rep.get("ok")), "why": why, "result": rep}
