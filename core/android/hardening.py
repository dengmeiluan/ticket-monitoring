# -*- coding: utf-8 -*-
"""设备侧硬化总入口：一次调用跑完五步，返回一份报告。

为什么要有这个「统一入口」
------------------------
硬化本身是五件互相有顺序依赖的事，散着调很容易做错：

```
① 身份（props/序列号/android_id）      ← 必须最先，App 启动前生效
② 显示对齐（身份声明 vs 真实屏幕）      ← 依赖 ① 的 identity 对象
③ root/模拟器隐藏                      ← 依赖 ① 写过的 props（不冲突）
④ 实例调优（动画/常亮/屏保）            ← 与 ①②③ 独立，随时可做
⑤ ABI 闸门（只在 canary 判定 ok 时才写） ← 依赖 ①，且必须最后
```

顺序错了会出现「先改 ABI 再改机型，结果 fingerprint 被 ABI 覆盖」或
「先对齐了 display，identity 又被 ensure 重写成机型原值」这类问题。

本模块只做编排，不实现任何一步的细节——细节仍在各自模块里，各自可单测。

失败语义
--------
**任何一步失败都不阻断后续步骤**，每一步的结果都进报告；``ok`` 只表示
「该做的都做了/该跳过的都跳过了」，不表示「设备一定没被发现」。
真正判断干不干净看 ``audit``（身份）与 ``detect``（隐藏）里的分数。
"""
from __future__ import annotations

from . import display as display_mod
from . import fingerprint as fp_mod
from . import stealth as st_mod
from . import emulator_tuning as tune_mod


def _flag(v, default=False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on", "auto")
    return bool(v)


def _sec(config: dict, name: str) -> dict:
    """读 ``android.<name>``；兼容 ``android.hardening.<name>`` 的写法。"""
    android = config.get("android") if isinstance(config, dict) else None
    android = android if isinstance(android, dict) else {}
    sec = android.get(name)
    if isinstance(sec, dict):
        return sec
    hard = android.get("hardening")
    if isinstance(hard, dict) and isinstance(hard.get(name), dict):
        return hard[name]
    return {}


def harden(dev, config: dict = None, logger=None, *, vm: int = 0,
           user_data_dir: str = "user_data", profile: str = "device",
           force: bool = False) -> dict:
    """跑完整套硬化。返回 ``{ok, steps, identity, stealth, tuning,
    display, abi}``。"""
    rep = {"ok": False, "steps": [], "identity": {}, "stealth": {},
           "tuning": {}, "display": {}, "abi": {}}

    # ---------- ① 身份 ----------
    try:
        rep["identity"] = fp_mod.ensure(
            dev, config, logger, user_data_dir=user_data_dir,
            profile=profile, vm=vm, force=force)
    except Exception as e:
        rep["identity"] = {"ok": False, "error": str(e)[:160]}
    rep["steps"].append(("identity", bool(rep["identity"].get("ok"))))

    # ---------- ② 显示对齐（零风险路线；不改设备设置）----------
    ident = None
    try:
        store = fp_mod.default_store(user_data_dir, profile)
        ident = store.get(vm)
        if ident.ident_id and _flag(_sec(config, "identity").get("align_display"),
                                    True):
            aligned = display_mod.align_identity(ident, dev)
            if aligned.get("changed"):
                store.put(ident)
                if logger:
                    logger.info("[android] 身份屏幕已对齐设备真实值：%s → %s",
                                aligned.get("from"), aligned.get("to"))
            rep["display"] = {
                "align": aligned,
                "audit": display_mod.audit(dev, ident),
            }
            rep["steps"].append(("display-align", True))
        else:
            rep["steps"].append(("display-align", True))
    except Exception as e:
        rep["display"] = {"error": str(e)[:160]}
        rep["steps"].append(("display-align", False))

    # ---------- ③ root / 模拟器隐藏 ----------
    try:
        rep["stealth"] = st_mod.prepare(dev, config, logger, vm=vm)
    except Exception as e:
        rep["stealth"] = {"ok": False, "error": str(e)[:160]}
    rep["steps"].append(("stealth", bool(rep["stealth"].get("ok"))))

    # ---------- ④ 实例调优 ----------
    try:
        rep["tuning"] = tune_mod.apply(dev, config, logger, vm=vm)
    except Exception as e:
        rep["tuning"] = {"ok": False, "error": str(e)[:160]}
    rep["steps"].append(("tuning", bool(rep["tuning"].get("ok"))))

    # ---------- ⑤ ABI 闸门（只有 canary 说行才写）----------
    try:
        rep["abi"] = _abi_gate(dev, config, logger, user_data_dir=user_data_dir)
    except Exception as e:
        rep["abi"] = {"ok": False, "error": str(e)[:160]}
    rep["steps"].append(("abi", bool(rep["abi"].get("ok", True))))

    rep["ok"] = all(ok for _name, ok in rep["steps"] if _name != "abi")
    return rep


def _abi_gate(dev, config: dict, logger, *, user_data_dir: str) -> dict:
    """ABI 伪装的**唯一开关点**。

    三种取值：
      * 未配置/``false``：不动 ABI（默认）；
      * ``"auto"``：**必须有 canary 的 ok 判定**才写（推荐）；
      * ``true``：无条件写（仅在你已经用 canary 验过、并且知道风险时）。
    """
    from . import abi_canary

    mode = _sec(config, "identity").get("spoof_abi")
    if not _flag(mode, False):
        return {"ok": True, "skipped": "spoof_abi 未开启"}

    pkg = ""
    try:
        # 包名表在 stealth 里已经有一份（与 crawlers/app_*.py 的 _APP_PKG 对齐）。
        # 放在同包里是为了避免 core → crawlers 的反向依赖（那会形成循环）。
        pkg = next(iter(st_mod.KNOWN_APPS.values()), "")
    except Exception:
        pkg = ""

    if str(mode).strip().lower() == "auto":
        if not pkg or not abi_canary.spoof_allowed(pkg, user_data_dir):
            return {"ok": True, "skipped": "auto：没有 %s 的 canary 判定"
                                           % (pkg or "目标包")}
    rep = abi_canary.apply_props(dev, abi_canary.ABI_ARM)
    if logger and rep.get("applied"):
        logger.info("[android] ABI 已按 canary 判定启用：%d 条生效",
                    len(rep["applied"]))
    return {"ok": bool(rep.get("applied")), "mode": str(mode),
            "pkg": pkg, "apply": rep}


def canary(dev, pkg: str = "", config: dict = None, logger=None, *,
           user_data_dir: str = "user_data", wait_s: int = 30) -> dict:
    """给操作员用的入口：跑一次 ABI 可行性验证（带自动回滚）。"""
    from . import abi_canary
    return abi_canary.run(dev, pkg, config, logger,
                          user_data_dir=user_data_dir, wait_s=wait_s)
