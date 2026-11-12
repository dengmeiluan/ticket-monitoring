"""App 版本与改版侦测（r1063 T64）。

为什么需要
----------
App 升级 / 页面改版会让「按坐标点 + 按文案认屏」的那套规则失效。我们的现状是：
失败会记成 `unknown` 路径或 0 行，**但"它今天升级了"这件事系统看不见**——于是
用户只能靠"怎么突然采不到了"来猜。

这条提供两个信号，分别回答两个问题：

1. **"它升级了吗"** —— `dumpsys package <pkg>` 里的 `versionName` / `versionCode` /
   `lastUpdateTime`。与上次快照比对，变了就记 `app_upgrade`（带旧→新版本）。
   实测智行：`10.26.2`（code 710262），`lastUpdateTime=2026-11-08 08:54:18`。
2. **"规则是不是失效了"** —— 该渠道连续 N 轮 0 行 **且** 路径落在
   `unknown` / `no-list-page` / 空页，记 `app_layout`（疑似改版）。

两者都进 `core.degraded`，健康页「降级」那一行就会说出来，并给出下一步。
"""
from __future__ import annotations

import json
import os
import re
import time

STATE_FILE = "app_versions.json"

# 改版嫌疑：连续这么多轮"0 行 + 认不出页面"就报
LAYOUT_STREAK = 2

_RE_VER = re.compile(r"versionName=([^\s]+)")
_RE_CODE = re.compile(r"versionCode=(\d+)")
_RE_UPD = re.compile(r"lastUpdateTime=([0-9:\-\s]+)")


def _state_path(root: str = "user_data") -> str:
    return os.path.join(str(root or "user_data"), "device", STATE_FILE)


def _load(root: str) -> dict:
    try:
        with open(_state_path(root), encoding="utf-8") as f:
            got = json.load(f)
        return got if isinstance(got, dict) else {}
    except Exception:
        return {}


def _save(root: str, data: dict) -> None:
    try:
        p = _state_path(root)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, p)
    except Exception:
        pass                    # 记账失败不许影响采集


def _adb(dev, *args, timeout: float = 15):
    """跑一条 adb 命令（与 `geo._adb` 同一套适配：`_sh` → `run_script` → `sh`）。"""
    sh = getattr(dev, "_sh", None)
    if callable(sh):
        return sh(*args, timeout=timeout)
    if args and str(args[0]) == "shell":
        run = getattr(dev, "run_script", None)
        if callable(run):
            return run(" ".join(str(a) for a in args[1:]), timeout=timeout)
    sh2 = getattr(dev, "sh", None)
    if callable(sh2):
        return sh2(*args, timeout=timeout)
    raise AttributeError("设备对象没有可用的 adb 执行入口")


def read_versions(dev, packages) -> dict:
    """读每个包的版本信息：`{pkg: {name, code, updated}}`（读不到就不写这一项）。"""
    out = {}
    for pkg in packages or ():
        pkg = str(pkg or "").strip()
        if not pkg:
            continue
        try:
            txt = str(_adb(dev, "shell", "dumpsys package %s" % pkg) or "")
        except Exception:
            continue
        m1 = _RE_VER.search(txt)
        if not m1:
            continue                # 没装/查不到：不记，别把"没装"当成"版本变了"
        m2 = _RE_CODE.search(txt)
        m3 = _RE_UPD.search(txt)
        out[pkg] = {
            "name": m1.group(1),
            "code": int(m2.group(1)) if m2 else 0,
            "updated": (m3.group(1).strip() if m3 else ""),
        }
    return out


def check(dev, packages, *, root: str = "user_data", plat_of=None,
          logger=None) -> dict:
    """比对版本快照；有变化就记 `app_upgrade` 并返回变化清单。

    `plat_of(pkg)` 用来把包名映射到渠道名（面板上要按渠道显示）。
    """
    now = read_versions(dev, packages)
    if not now:
        return {"ok": False, "why": "读不到任何 App 版本", "changed": {}}
    old = _load(root)
    changed = {}
    for pkg, cur in now.items():
        prev = old.get(pkg) or {}
        if not prev:
            continue                # 首次记录不算"升级"
        if (str(prev.get("name") or "") != cur["name"]
                or int(prev.get("code") or 0) != int(cur["code"] or 0)):
            changed[pkg] = {"old": prev, "new": cur}
            plat = ""
            try:
                plat = str(plat_of(pkg) or "") if callable(plat_of) else ""
            except Exception:
                plat = ""
            detail = "%s %s → %s（%s）" % (
                plat or pkg, prev.get("name") or "?", cur["name"],
                "解析规则可能需要适配")
            try:
                from core import degraded as _dg
                _dg.note("app_upgrade", plat, detail)
            except Exception:
                pass
            if logger is not None:
                try:
                    logger.warning("[App升级] %s", detail)
                except Exception:
                    pass
    _save(root, now)
    return {"ok": True, "changed": changed, "versions": now}


def note_layout_risk(plat: str, *, rows: int = 0, path: str = "",
                     root: str = "user_data", logger=None) -> bool:
    """连续 N 轮「0 行 + 认不出页面」就记一次 `app_layout`（疑似改版）。

    为什么把两个条件绑在一起：只 0 行可能是没票/被拦；只认不出页面可能是
    某一屏没命中。**两者同时连续发生**才像改版。
    """
    key = str(plat or "")
    if not key:
        return False
    state = _load(root)
    risk = state.get("_layout_risk") if isinstance(
        state.get("_layout_risk"), dict) else {}
    rec = risk.get(key) if isinstance(risk.get(key), dict) else {}
    bad_path = str(path or "").lower() in ("", "unknown", "no-list-page")
    if rows > 0 or not bad_path:
        if rec:
            risk.pop(key, None)
            state["_layout_risk"] = risk
            _save(root, state)
        return False
    streak = int(rec.get("streak") or 0) + 1
    risk[key] = {"streak": streak, "at": time.time()}
    state["_layout_risk"] = risk
    _save(root, state)
    if streak < LAYOUT_STREAK:
        return False
    try:
        from core import degraded as _dg
        _dg.note("app_layout", key,
                 "连续 %d 轮 0 行且认不出页面（末次路径 %s）——疑似改版，"
                 "该渠道的认屏/解析规则可能要更新" % (streak, path or "空"))
    except Exception:
        pass
    if logger is not None:
        try:
            logger.warning("[疑似改版] %s 连续 %d 轮 0 行 + 认不出页面",
                           key, streak)
        except Exception:
            pass
    risk[key] = {"streak": streak, "at": time.time(), "reported": True}
    state["_layout_risk"] = risk
    _save(root, state)
    return True

# 各 App 的"这一屏还是这一屏吗"锚点（可见文案/描述里应当出现的词）
ANCHORS = {
    "app_zhixing": ["机票", "往返", "出发", "到达", "搜索", "国内", "国际"],
    "app_fliggy": ["机票", "单程", "往返", "出发", "到达", "搜索"],
    "app_qunar": ["机票", "单程", "往返", "出发", "到达"],
    "app_ctrip": ["机票", "单程", "往返", "出发", "到达"],
    "app_tongcheng": ["机票", "单程", "往返", "出发", "到达"],
}


def read_ui(dev, *, timeout: float = 60) -> str:
    """抓当前 UI 树（只读，不点任何东西）。"""
    try:
        return str(_adb(dev, "shell",
                        "uiautomator dump /sdcard/ui.xml >/dev/null 2>&1; "
                        "cat /sdcard/ui.xml", timeout=timeout) or "")
    except Exception:
        return ""


def probe_anchors(dev, plat: str, *, xml: str = None) -> dict:
    """锚点体检：这一屏还认不认得出来。

    返回 `{plat, total, hits, missing, rate, texts}`；`rate` 低于 0.6 就记
    `app_layout`（"疑似改版"），因为连查询表单的关键词都对不上了。
    """
    key = str(plat or "")
    want = list(ANCHORS.get(key) or ["机票", "出发", "到达"])
    tree = xml if xml is not None else read_ui(dev)
    if not tree:
        return {"plat": key, "ok": False, "why": "抓不到 UI 树",
                "total": len(want), "hits": 0, "missing": want, "rate": 0.0}
    texts = [t for t in re.findall(r'(?:text|content-desc)="([^"]+)"', tree)
             if t.strip()]
    blob = "\n".join(texts)
    hits = [a for a in want if a in blob]
    missing = [a for a in want if a not in blob]
    rate = round(len(hits) / max(1, len(want)), 2)
    out = {"plat": key, "ok": True, "total": len(want), "hits": len(hits),
           "hit_words": hits, "missing": missing, "rate": rate,
           "texts": texts[:30]}
    if rate < 0.6:
        try:
            from core import degraded as _dg
            _dg.note("app_layout", key,
                     "锚点只命中 %d/%d（缺 %s）——疑似改版"
                     % (len(hits), len(want), "、".join(missing[:4])))
        except Exception:
            pass
    return out


def _cli(argv=None):                             # pragma: no cover - CLI
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    from . import emulator as _emu
    from .config import normalize, resolve_install_dir
    import yaml

    cfg = {}
    try:
        with open("config.yaml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        cfg = {}
    sec = cfg.get("android") or {}
    dev = _emu.device({"android": sec})
    cmd = argv[0] if argv else "versions"

    if cmd == "versions":
        from crawlers import REGISTRY
        pk = {str(c.package): p for p, c in REGISTRY.items()
              if str(p).startswith("app_") and getattr(c, "package", "")}
        ver = read_versions(dev, list(pk))
        for pkg, v in sorted(ver.items()):
            print("%-24s %-14s code=%-9s lastUpdate=%s"
                  % (pkg, v["name"], v["code"], v["updated"]))
        rep = check(dev, list(pk), root="user_data",
                    plat_of=lambda p: pk.get(p, ""))
        for pkg, ch in (rep.get("changed") or {}).items():
            print("!! 已升级：%s %s → %s" % (pk.get(pkg, pkg),
                                            ch["old"].get("name"),
                                            ch["new"].get("name")))
        return 0

    if cmd == "probe":
        plat = argv[1] if len(argv) > 1 else "app_zhixing"
        rep = probe_anchors(dev, plat)
        print("锚点体检 %s：命中 %s/%s（rate=%s）"
              % (plat, rep.get("hits"), rep.get("total"), rep.get("rate")))
        print("  命中：", "、".join(rep.get("hit_words") or []) or "无")
        print("  缺失：", "、".join(rep.get("missing") or []) or "无")
        return 0 if (rep.get("rate") or 0) >= 0.6 else 1

    print("用法：python -m core.android.appversion versions|probe [渠道]")
    return 2


if __name__ == "__main__":                       # pragma: no cover
    raise SystemExit(_cli())
