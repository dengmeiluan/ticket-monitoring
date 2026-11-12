"""策略配置快照：导出 / 对比 / 导入（r1063 T37）。

为什么需要
----------
策略现在有 30 条 × 98 个参数 + 四级作用域覆盖，全散在 `config.yaml` 的
`crawler.*` 点路径里。想"把这套调到好的配置备份下来""换台机器照搬""改坏了
回滚"，现在只能手工比对——这正是最容易出错的地方。

**快照只装"和默认不一样的东西"**：
  * 全局层：`{pid: 值}`，只收与声明默认值不同的（同一份默认配置导出来是空表，
    一眼能看出"我到底改了什么"）；
  * 粒度层：`crawler.strategy_overrides` 原样（它是显式声明，没有"默认"可比）；
  * 不含 `users` / 凭证 / 停手表（停手是运行期状态，导出它会把"临时停 15 分钟"
    变成"永久停"——这属于典型的数据搬错语义）。

三个动作都**只读不写盘**，写由调用方（webui 保存通路）负责：
  * `export(cfg)`   → 快照字典
  * `diff(cfg, snap)` → 逐项差异（谁会变成什么）
  * `apply(cfg, snap)` → 把快照合并进 cfg（返回变更条数与拒绝项）
"""
from __future__ import annotations

import time

SNAPSHOT_VERSION = 1


def _catalog():
    from core.strategy_contract import STRATEGIES
    return {p.pid: p for s in STRATEGIES for p in s.params}


def _get_path(cfg, dotted, default=None):
    node = cfg if isinstance(cfg, dict) else {}
    for seg in [x for x in str(dotted or "").split(".") if x]:
        if not isinstance(node, dict) or seg not in node:
            return default
        node = node[seg]
    return node


def _set_path(cfg, dotted, value):
    segs = [x for x in str(dotted or "").split(".") if x]
    if not segs:
        return False
    node = cfg
    for seg in segs[:-1]:
        nxt = node.get(seg)
        if not isinstance(nxt, dict):
            nxt = {}
            node[seg] = nxt
        node = nxt
    node[segs[-1]] = value
    return True


def _del_path(cfg, dotted):
    segs = [x for x in str(dotted or "").split(".") if x]
    if not segs:
        return
    node = cfg
    for seg in segs[:-1]:
        nxt = node.get(seg)
        if not isinstance(nxt, dict):
            return
        node = nxt
    node.pop(segs[-1], None)


def export(cfg, *, include_halt=False, halt_dir=None):
    """导出快照（只含与默认不同的项）。"""
    cat = _catalog()
    values = {}
    for pid, p in cat.items():
        if pid.endswith(".enabled") or pid.startswith("strategy_enabled."):
            # 族的开关也导出（它就是"我关了哪一族"），但以同样规则比较默认值
            pass
        cur = _get_path(cfg, p.cfg)
        if cur is None:
            continue
        if cur == p.default:
            continue
        values[pid] = cur
    ovr = _get_path(cfg, "crawler.strategy_overrides", {}) or {}
    snap = {
        "version": SNAPSHOT_VERSION,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "note": "只含与声明默认不同的项；不含用户/凭证/停手",
        "values": values,
        "overrides": dict(ovr) if isinstance(ovr, dict) else {},
    }
    if include_halt:
        try:
            from core.policy import read_halt
            snap["halt"] = read_halt(halt_dir or "user_data")
        except Exception:
            pass
    return snap


def diff(cfg, snap):
    """逐项差异：`[{pid, scope, before, after, action}]`。

    `action` ∈ `set`（会写）/ `clear`（会删回默认）/ `reject`（不认识的 pid）。
    """
    snap = snap if isinstance(snap, dict) else {}
    cat = _catalog()
    out = []
    for pid, want in (snap.get("values") or {}).items():
        p = cat.get(str(pid))
        if p is None:
            out.append({"pid": pid, "scope": "", "before": None,
                        "after": want, "action": "reject"})
            continue
        cur = _get_path(cfg, p.cfg)
        if cur == want:
            continue
        out.append({"pid": pid, "scope": "", "before": cur,
                    "after": want,
                    "action": "clear" if want == p.default else "set"})
    ovr_now = _get_path(cfg, "crawler.strategy_overrides", {}) or {}
    for scope, kv in (snap.get("overrides") or {}).items():
        for pid, want in (kv or {}).items():
            if str(pid) not in cat:
                out.append({"pid": pid, "scope": scope, "before": None,
                            "after": want, "action": "reject"})
                continue
            cur = ((ovr_now.get(scope) or {}).get(pid))
            if cur == want:
                continue
            out.append({"pid": pid, "scope": scope, "before": cur,
                        "after": want, "action": "set"})
    return out


def apply(cfg, snap, *, dry_run=False):
    """把快照合并进 cfg。返回 `{applied, rejected, cleared}`。

    **拒绝未知 pid**（不静默忽略）：一份来源不明的快照里出现目录里没有的键，
    要么是版本不匹配，要么是手改坏了——两种都该让人看见。
    """
    snap = snap if isinstance(snap, dict) else {}
    if int(snap.get("version") or 0) > SNAPSHOT_VERSION:
        raise ValueError("快照版本 %s 比本程序支持的 %s 更新，请升级后再导入"
                         % (snap.get("version"), SNAPSHOT_VERSION))
    rows = diff(cfg, snap)
    applied = cleared = 0
    rejected = [r for r in rows if r["action"] == "reject"]
    for r in rows:
        if r["action"] == "reject":
            continue
        if r.get("scope"):
            # **作用域行不写全局**：它由下面的 overrides 合并统一处理。
            # 漏这一条会把「ctrip 的覆盖」写成「全站的值」——一份快照导进去，
            # 全站参数被某个渠道的覆盖值顶掉（真实踩过的坑）。
            continue
        p = _catalog().get(str(r["pid"]))
        if p is None:
            continue
        try:
            from core.strategy_params import clamp
            val, _note = clamp(p.pid, r["after"])
        except Exception:
            val = r["after"]
        if dry_run:
            applied += 1 if r["action"] == "set" else 0
            cleared += 1 if r["action"] == "clear" else 0
            continue
        if r["action"] == "clear":
            _del_path(cfg, p.cfg)
            cleared += 1
        else:
            _set_path(cfg, p.cfg, val)
            applied += 1
    # 粒度覆盖：整块替换（快照里没有的作用域保持原样，避免"导一份丢一片"）
    ovr = snap.get("overrides")
    if isinstance(ovr, dict) and ovr and not dry_run:
        cur = _get_path(cfg, "crawler.strategy_overrides")
        if not isinstance(cur, dict):
            cur = {}
            _set_path(cfg, "crawler.strategy_overrides", cur)
        for scope, kv in ovr.items():
            if isinstance(kv, dict) and kv:
                cur[str(scope)] = dict(kv)
    return {"applied": applied, "cleared": cleared,
            "rejected": [{"pid": r["pid"], "scope": r["scope"]}
                         for r in rejected]}


def _main(argv=None):                            # pragma: no cover - CLI
    import json
    import sys

    import yaml

    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("用法：python -m core.cfg_snapshot export|diff|apply <config.yaml> [snapshot.json]")
        return 2
    cmd, cfg_path = argv[0], (argv[1] if len(argv) > 1 else "config.yaml")
    snap_path = argv[2] if len(argv) > 2 else "strategy_snapshot.json"
    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if cmd == "export":
        snap = export(cfg)
        with open(snap_path, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=1, sort_keys=True)
        print("已导出 %d 项改动 + %d 个作用域 → %s"
              % (len(snap["values"]), len(snap["overrides"]), snap_path))
        return 0
    with open(snap_path, encoding="utf-8") as f:
        snap = json.load(f)
    if cmd == "diff":
        rows = diff(cfg, snap)
        for r in rows:
            print("%-34s %-18s %r → %r [%s]"
                  % (r["pid"], r["scope"] or "-", r["before"], r["after"],
                     r["action"]))
        print("共 %d 项差异" % len(rows))
        return 0
    if cmd == "apply":
        got = apply(cfg, snap)
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False,
                           width=100)
        print("已应用：写 %d、清 %d、拒绝 %d"
              % (got["applied"], got["cleared"], len(got["rejected"])))
        return 0
    print("未知子命令：%s" % cmd)
    return 2


if __name__ == "__main__":                       # pragma: no cover
    raise SystemExit(_main())
