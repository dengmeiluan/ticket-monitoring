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
from . import vendor as vendor_mod


def _vendor_step(config: dict, logger, *, vm: int) -> dict:
    """读 MuMu 官方设置；**只有显式配置了才写**。

    可写键（``android.vendor`` 段）::

        android:
          vendor:
            apply: true                 # 默认 false = 只读
            brand: Samsung
            model: Galaxy A52 5G
            miit: SM-A5260
            width: 900                  # 改分辨率必须配 dev.set_design()
            height: 1600
            dpi: 240
            unlock_system_disk: false   # true=把系统盘改可写（ABI 前置，需重启）
    """
    sec = _sec(config, "vendor")
    mgr = None
    try:
        from .mumu import MuMuManager
        from .config import resolve_install_dir, normalize
        mgr = MuMuManager(install_dir=resolve_install_dir(normalize(None)),
                          vm_index=int(vm))
    except Exception:
        mgr = None
    out = vendor_mod.read(mgr) if mgr is not None else {}
    rep = {"ok": True, "available": bool(out), "current": {
        k: out.get(k) for k in ("phone_brand", "phone_model", "phone_miit",
                                "resolution_width", "resolution_height",
                                "resolution_dpi", "system_disk_readonly",
                                "root_permission") if k in out}}
    if not _flag(sec.get("apply"), False):
        rep["skipped"] = "只读（android.vendor.apply=false）"
        return rep
    if mgr is None or not mgr.available():
        rep["ok"] = False
        rep["error"] = "MuMuManager 不可用，无法写官方设置"
        return rep
    vals = {}
    for key, cfg_key in (("phone_brand", "brand"), ("phone_model", "model"),
                         ("phone_miit", "miit"),
                         ("resolution_width", "width"),
                         ("resolution_height", "height"),
                         ("resolution_dpi", "dpi")):
        v = sec.get(cfg_key)
        if v not in (None, ""):
            vals[key] = v
    if _flag(sec.get("unlock_system_disk"), False):
        vals["system_disk_readonly"] = "false"
    if not vals:
        rep["skipped"] = "没有要写的键"
        return rep
    rep["apply"] = vendor_mod.apply(mgr, logger=logger, **vals)
    rep["ok"] = bool(rep["apply"].get("ok"))
    return rep


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


def _coordinate_check(dev, config: dict, logger=None) -> dict:
    """坐标基准体检：设备分辨率 vs App 渠道写死的设计基准。

    App 渠道的坐标全部按 **900×1600 竖屏**写死（见 ``device.py`` 里横屏
    1600×900 让坐标全偏的现场记录）。所以一旦有人改了屏幕，就必须同时
    ``AdbDevice.set_design(900, 1600)`` 做换算，否则点击会按比例偏——
    这种错在账本上表现为「设城市失败 / 页面认不出」，很难追到根因。

    这里只做**体检 + 明确告警**，不替调用方开换算（开换算属于
    ``display.spoof`` 的配套动作，由 ``scripts/display_spoof.py`` 负责）。
    """
    design = (900, 1600)
    try:
        sec = _sec(config, "display")
        d = sec.get("design")
        if isinstance(d, (list, tuple)) and len(d) == 2:
            design = (int(d[0]), int(d[1]))
    except Exception:
        pass
    try:
        got = display_mod.actual(dev)
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}
    same = (got.get("width"), got.get("height")) == design
    rep = {"ok": same, "design": list(design),
           "actual": [got.get("width"), got.get("height")],
           "density": got.get("density"), "override": got.get("override", False)}
    if not same and logger:
        logger.warning(
            "[android] 屏幕 %sx%s ≠ 坐标基准 %dx%d：App 渠道写死坐标会偏，"
            "必须 dev.set_design(%d, %d)（或用 scripts/display_spoof.py --restore 回滚）",
            got.get("width"), got.get("height"), design[0], design[1],
            design[0], design[1])
    return rep


def harden(dev, config: dict = None, logger=None, *, vm: int = 0,
           user_data_dir: str = "user_data", profile: str = "device",
           force: bool = False) -> dict:
    """跑完整套硬化。返回 ``{ok, steps, identity, stealth, tuning,
    display, abi}``。"""
    rep = {"ok": False, "steps": [], "identity": {}, "stealth": {},
           "tuning": {}, "display": {}, "abi": {}, "vendor": {}}

    # ---------- ⓿ 厂商官方接口（比改 props 更稳，优先用）----------
    #
    # 机型 / 分辨率 / 系统盘只读 在 MuMu 上都有**官方键**，写进实例配置即可，
    # 不需要 root、不需要 Magisk，而且可持久化。所以放在最前面：凡是官方
    # 能做的就不去改 props（见 core/android/vendor.py 的分层原则）。
    # 默认**只读不写**——写配置要重启实例才生效，属于操作员的决定。
    try:
        rep["vendor"] = _vendor_step(config, logger, vm=vm)
    except Exception as e:
        rep["vendor"] = {"ok": False, "error": str(e)[:160]}
    rep["steps"].append(("vendor-read", bool(rep["vendor"].get("ok", False))))

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
        # 坐标基准体检：设备分辨率≠设计基准时**必须**开 set_design，
        # 否则写死坐标会按比例偏（仓库吃过一次横屏 1600×900 坐标全偏的亏）。
        rep["display"]["coordinate"] = _coordinate_check(dev, config, logger)
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
