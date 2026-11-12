"""设备身份轮换（r1063 T72）——回答"被标记了是不是只能抹掉 MuMu 设备 ID"。

结论先说：**不必先动模拟器本身**。风控聚类靠的是一条链：
   设备指纹（build 家族/android_id/序列号）+ **App 自己攒的本地 ID**（utdid/umid/oaid）
   + 会话 cookie + 出口 IP
其中"App 本地 ID"最容易变、代价最小，"模拟器实例本身"代价最大（要重装+重登）。

本工具按**从便宜到贵**的顺序做三件事（每步都有备份/可回滚）：
 1. 换掉我们写入设备身份（`user_data/device/device_identity.json` → 备份后 drop，
    下一次采集自动生成新的一套：android_id、build 家族、序列号…）；
 2. 清掉指定 App 的**本地设备 ID 文件**（复用 `stealth.clear_app_identity`，
    先备份到 `/data/local/tmp/tm_idbak-*` 再删；默认 dry-run）；
 3. 重启模拟器（可选）让新身份在 App 冷启动前生效。

用法::

    python -m core.android.rotate                  # 演练：只说会做什么
    python -m core.android.rotate --apply          # 真做（身份 + App 本地 ID）
    python -m core.android.rotate --apply --apps app_ctrip,app_qunar --restart
    python -m core.android.rotate --restore <备份文件名>   # 回滚设备身份

判据纪律：**不清登录态**（`clear_app_identity` 只删 ID 类 shared_prefs/files，
不碰 cookie/token），所以换完通常不用重新登录。
"""
from __future__ import annotations

import glob
import json
import logging
import os
import shutil
import time

_LOG = logging.getLogger(__name__)

# 默认要清的 App（这些是"会自己攒设备 ID"的渠道）
DEFAULT_APPS = ("app_ctrip", "app_qunar", "app_fliggy", "app_zhixing",
                "app_tongcheng")


def _store(user_data_dir: str = "user_data"):
    from .fingerprint import default_store
    return default_store(str(user_data_dir or "user_data"), profile="device")


def _pkg_of(plat: str) -> str:
    try:
        from crawlers import REGISTRY
        cls = REGISTRY.get(str(plat))
        return str(getattr(cls, "package", "") or "")
    except Exception:
        return ""


def _log_path(root: str) -> str:
    return os.path.join(str(root), "device", "rotate_log.json")


def _append_log(root: str, rec: dict) -> None:
    try:
        p = _log_path(root)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        data = []
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f) or []
        except Exception:
            data = []
        data.append(rec)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data[-20:], f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _vm_index(user_data_dir: str = "user_data") -> int:
    """当前实例索引（`android.vm_index`，缺省 0）——身份按它分槽存。"""
    try:
        import yaml
        with open("config.yaml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return int((cfg.get("android") or {}).get("vm_index") or 0)
    except Exception:
        return 0


def plan(user_data_dir: str = "user_data", apps=None) -> dict:
    """演练：说清"会动什么、不会动什么"。"""
    st = _store(user_data_dir)
    ident = str(getattr(st, "path", "") or "")
    # 空列表 = 一个都不清。以前 `apps or DEFAULT_APPS` 把 [] 当作没传，
    # 于是只想换身份会把五家 App 的本地 ID 全清掉（T74 实测踩到）。
    plats = list(DEFAULT_APPS if apps is None else apps)
    pkgs = {p: _pkg_of(p) for p in plats if _pkg_of(p)}
    return {
        "identity_file": ident,
        "identity_exists": bool(ident and os.path.exists(ident)),
        "apps": pkgs,
        "steps": [
            "备份并 drop 设备身份（下次采集自动生成新的 android_id/build/序列号）",
            "备份并清掉 %d 个 App 的本地设备 ID 文件（不动 cookie/登录态）"
            % len(pkgs),
            "（可选）重启模拟器，让新身份在 App 冷启动前生效",
        ],
        "keeps": ["登录态（cookie/token）", "采集配置与策略", "历史数据与账本"],
    }


def rotate(user_data_dir: str = "user_data", apps=None, *,
           apply: bool = False, restart: bool = False, reason: str = "",
           apps_only: bool = False, logger=None) -> dict:
    """执行轮换。`apply=False` 时只回演练结果。

    `apps_only=True`：**只清 App 本地设备 ID，不动设备身份**——最便宜的一步，
    通常也最有效（很多"被标记"其实是 App 侧 utdid/guid 被记住了）。
    """
    log = logger or _LOG
    root = str(user_data_dir or "user_data")
    out = {"ok": False, "applied": False, "identity_backup": "",
           "apps": {}, "restart": None, "why": ""}
    st = _store(root)
    ident = str(getattr(st, "path", "") or "")
    # 空列表 = 一个都不清。以前 `apps or DEFAULT_APPS` 把 [] 当作没传，
    # 于是只想换身份会把五家 App 的本地 ID 全清掉（T74 实测踩到）。
    plats = list(DEFAULT_APPS if apps is None else apps)
    pkgs = {p: _pkg_of(p) for p in plats if _pkg_of(p)}
    if not apply:
        out.update(ok=True, why="演练（未改动）", plan=plan(root, plats))
        # 演练就告诉用户"真做之后哪些 App 要重登"（r1063 T101）
        try:
            from .identity import apps_need_relogin
            _need = apps_need_relogin()
            if _need:
                out["relogin_required"] = _need
                out["notice"] = ("执行后身份变更，以下 App 需重新登录：%s"
                                 % "、".join(_need))
        except Exception:
            pass
        return out

    # ① 身份：备份后 drop（apps_only 时跳过——这是"从便宜到贵"的第一档）
    if apps_only:
        out["identity_skipped"] = True
    elif ident and os.path.exists(ident):
        bak = "%s.bak_%s" % (ident, time.strftime("%Y%m%d_%H%M%S"))
        try:
            shutil.copy2(ident, bak)
            out["identity_backup"] = bak
        except Exception as e:
            out["why"] = "身份备份失败：%s" % str(e)[:80]
            return out
    if not apps_only:
        try:
            # 真实签名是 `drop(vm: int)`：身份按**实例索引**分槽存（多开场景）
            st.drop(_vm_index(root))
            log.info("[轮换] 设备身份已 drop（vm=%s；下次采集生成新的一套）",
                     _vm_index(root))
        except Exception as e:
            out["why"] = "身份 drop 失败：%s" % str(e)[:80]
            return out

    # ② App 本地 ID：备份后清（dry_run=False 才真删）
    try:
        from . import emulator as _emu
        from .stealth import clear_app_identity
        dev = _emu.device({"android": {"install_dir": ""}})
    except Exception as e:
        dev = None
        out["why"] = "拿不到设备：%s" % str(e)[:80]
    if dev is not None:
        for plat, pkg in pkgs.items():
            try:
                # 真实返回：{"dry_run", "packages": {pkg: {files, removed, backup}},
                #           "backup_dir"}
                rep = clear_app_identity(dev, [pkg], None, log, dry_run=False)
                rec = (rep.get("packages") or {}).get(pkg) or {}
                out["apps"][plat] = {
                    "pkg": pkg,
                    "ok": bool(rec.get("removed")),
                    "removed": int(rec.get("removed") or 0),
                    "files": len(rec.get("files") or []),
                    "backup": str(rec.get("backup") or rep.get("backup_dir")
                                  or "")[:80]}
            except Exception as e:
                out["apps"][plat] = {"pkg": pkg, "ok": False,
                                     "err": str(e)[:80]}

    # ③ 可选重启
    if restart:
        try:
            from . import emulator as _emu2
            out["restart"] = _emu2.restart({"android": {"install_dir": ""}},
                                           logger=log).get("ok")
        except Exception as e:
            out["restart"] = False
            out["why"] = (out["why"] or "") + " 重启失败：%s" % str(e)[:60]

    out["ok"] = True
    out["applied"] = True
    # r1063 T101：换身份 = 换设备 → **所有 App 会话失效**，必须明说
    try:
        from .identity import apps_need_relogin
        _need = apps_need_relogin()
        if _need:
            out["relogin_required"] = _need
            out["notice"] = ("身份已变，以下 App 需重新登录：%s"
                             % "、".join(_need))
    except Exception:
        pass
    out["why"] = out["why"] or "已轮换：身份已换、App 本地 ID 已清"
    _append_log(root, {"at": time.time(), "reason": str(reason)[:120],
                       "apps": list(pkgs), "identity_backup":
                       out["identity_backup"], "restart": out["restart"]})
    try:
        from core import degraded as _dg
        _dg.note("device_rotated", "",
                 "设备身份已轮换（%d 个 App 本地 ID 已清）" % len(pkgs))
    except Exception:
        pass
    return out


def restore(user_data_dir: str, name: str = "") -> dict:
    """回滚：把某份 `device_identity.json.bak_*` 还原回去。"""
    root = str(user_data_dir or "user_data")
    st = _store(root)
    ident = str(getattr(st, "path", "") or "")
    pat = ident + ".bak_*" if ident else os.path.join(
        root, "device", "device_identity.json.bak_*")
    baks = sorted(glob.glob(pat))
    if not baks:
        return {"ok": False, "why": "没有身份备份"}
    pick = baks[-1]
    if name:
        cand = [b for b in baks if name in os.path.basename(b)]
        if not cand:
            return {"ok": False, "why": "找不到备份 %s" % name}
        pick = cand[-1]
    try:
        shutil.copy2(pick, ident)
        return {"ok": True, "restored": os.path.basename(pick)}
    except Exception as e:
        return {"ok": False, "why": str(e)[:120]}


def _main(argv=None):                             # pragma: no cover - CLI
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    apply = "--apply" in argv
    restart = "--restart" in argv
    apps_only = "--apps-only" in argv
    apps = None
    reason = ""
    restore_name = ""
    for i, a in enumerate(argv):
        if a == "--apps" and i + 1 < len(argv):
            apps = [x.strip() for x in argv[i + 1].split(",") if x.strip()]
        if a == "--reason" and i + 1 < len(argv):
            reason = argv[i + 1]
        if a == "--restore" and i + 1 < len(argv):
            restore_name = argv[i + 1]
    if restore_name or "--restore" in argv:
        print(json.dumps(restore("user_data", restore_name), ensure_ascii=False,
                         indent=1))
        return 0
    rep = rotate("user_data", apps, apply=apply, restart=restart,
                 reason=reason, apps_only=apps_only)
    print(json.dumps(rep, ensure_ascii=False, indent=1, default=str))
    return 0 if rep.get("ok") else 1


if __name__ == "__main__":                        # pragma: no cover
    raise SystemExit(_main())
