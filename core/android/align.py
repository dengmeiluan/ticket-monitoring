# -*- coding: utf-8 -*-
'''r1063 T84：把设备身份**对齐到 GPU**（消掉最后一处矛盾）。

问题：MuMu 的 GPU 厂商前缀固定是 `Qualcomm`（`gpu_model.custom` 只改型号串），
所以真机上 `GL_RENDERER = Qualcomm, Adreno (TM) 750`。若设备身份是 vivo X200 Pro
（天玑 9400 / Mali），GPU 与 SoC 就矛盾——这正是风控判"环境异常"的依据之一
（携程 50003 / 阿里强制滑块）。

修法：**反向对齐** —— 保持 GPU 不变，把设备身份换成 **骁龙 8 Gen 3** 的机型
（池里 `Xiaomi 23127PN0CC`），于是 `Qualcomm + Adreno 750` 1:1 自洽。

另外同步 MuMu 的 `phone_brand/model/miit`，否则 hypervisor 层与 guest 层又打架。

用法::

    python -m core.android.align            # 演练：说会切成什么
    python -m core.android.align --apply    # 真写（随后需重生成开机模块并重启）
'''
from __future__ import annotations

import json
import random

# GPU 家族 → 该家族可信的池内机型（model 码）
GPU_TO_MODELS = {
    "Adreno": ("23127PN0CC", "2201123C", "SM-S9280"),   # 骁龙 8 Gen 3 / 8 Gen 1
    "Mali": ("V2405A", "MT6989"),                        # 天玑系
}

# 机型码 → MuMu hypervisor 侧品牌/型号/认证码
MUMU_IDS = {
    "23127PN0CC": ("Xiaomi", "Xiaomi 14", "23127PN0CC"),
    "2201123C": ("Xiaomi", "Xiaomi 12", "2201123C"),
    "SM-S9280": ("samsung", "Galaxy S24 Ultra", "SM-S9280"),
    "V2405A": ("vivo", "vivo X200 Pro", "V2405A"),
    "MT6989": ("vivo", "vivo X100 Pro", "V2324A"),
}


def _pool():
    from . import fingerprint as fp
    return fp.PHONE_POOL


def _gl_family(dev) -> str:
    """当前 GL_RENDERER 的家族：'Adreno' / 'Mali' / ''（读不到）。"""
    out = ""
    # ① 普通 shell（实测可行）
    try:
        fn = getattr(dev, "_sh", None)
        if callable(fn):
            out = str(fn("shell",
                         "dumpsys SurfaceFlinger | grep -m1 -i 'GLES:'") or "")
    except Exception:
        out = ""
    # ② 兜底：走 root 通道
    if not out:
        try:
            from .fingerprint import _text, as_root
            out = _text(as_root(
                dev, "dumpsys SurfaceFlinger | grep -m1 -i 'GLES:'")) or ""
        except Exception:
            out = ""
    low = out.lower()
    if "adreno" in low:
        return "Adreno"
    if "mali" in low or "immortalis" in low:
        return "Mali"
    return ""


def plan(dev=None, cfg: dict = None, vm: int = 0) -> dict:
    """演练：当前 GPU 家族 → 应该换成哪个池内机型。"""
    fam = _gl_family(dev) if dev is not None else ""
    pool = _pool()
    want_models = GPU_TO_MODELS.get(fam, ())
    pick = None
    for m in want_models:
        for p in pool:
            if str(p.get("model")) == m:
                pick = p
                break
        if pick:
            break
    return {"gpu_family": fam or "未知",
            "pick": pick,
            "mumu_id": MUMU_IDS.get(str((pick or {}).get("model")), ()),
            "why": "" if pick else "池里没有与当前 GPU 家族匹配的机型"}


def apply(dev, cfg: dict = None, vm: int = 0, *, write: bool = False,
          user_data_dir: str = "user_data") -> dict:
    """把身份对齐到 GPU 家族（默认只演练）。

    真写会：① 换 identity 档案（新 serial/android_id/imei）；② 同步 MuMu 身份；
    返回里带 `next_steps`（重生成开机模块 + 重启实例）。
    """
    p = plan(dev, cfg, vm)
    rep = dict(p, ok=False, applied=False, next_steps=[
        "python scripts/identity_boot_module.py",
        "重启 MuMu 实例（emulator.restart）",
    ])
    pick = p.get("pick")
    if not pick:
        return rep
    if not write:
        rep["ok"] = True
        rep["why"] = "演练（未写入）"
        return rep

    from . import fingerprint as fp
    st = fp.default_store(user_data_dir, profile="device")
    rng = random.Random()
    serial = "".join(rng.choice("0123456789ABCDEF") for _ in range(16))
    data = {"vm": vm, "profile": dict(pick), "serial": serial,
            "android_id": "%016x" % rng.getrandbits(64),
            "imei": _imei(rng),
            "pool_index": _pool().index(pick),
            "source": "align_to_gpu",
            "created_at": __import__("time").time()}
    try:
        st.put(fp.Identity(data))
        rep["identity_written"] = True
    except Exception as e:
        rep["why"] = "身份写入失败：%s" % str(e)[:80]
        return rep

    # 同步 MuMu hypervisor 侧
    try:
        from .mumu import MuMuManager
        install = str(((cfg or {}).get("android") or {}).get("install_dir") or "")
        m = MuMuManager(install or None)
        brand, model_name, miit = rep.get("mumu_id") or ("", "", "")
        wrote = {}
        for k, v in (("phone_brand", brand), ("phone_model", model_name),
                     ("phone_miit", miit), ("phone_imei", data["imei"])):
            if not v:
                continue
            try:
                wrote[k] = bool(m.setting(k, v, vm=vm))
            except Exception:
                wrote[k] = False
        rep["mumu_wrote"] = wrote
    except Exception as e:
        rep["mumu_wrote"] = {"err": str(e)[:60]}

    rep["ok"] = True
    rep["applied"] = True
    # r1063 T101：换身份 = 换设备 → 所有 App 会话失效
    try:
        from .identity import apps_need_relogin
        _need = apps_need_relogin(cfg)
        if _need:
            rep["relogin_required"] = _need
            rep["notice"] = ("身份已换，以下 App 需重新登录：%s"
                             % "、".join(_need))
    except Exception:
        pass
    rep["why"] = "身份已对齐到 %s（%s）" % (pick.get("model"), pick.get("soc"))
    return rep


def _imei(rng: random.Random) -> str:
    from .identity import _rand_imei
    return _rand_imei(rng)


def _main(argv=None):                            # pragma: no cover - CLI
    import logging
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from . import emulator
    cfg = {"android": {}}
    try:
        import yaml
        with open("config.yaml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        pass
    dev = emulator.device(cfg)
    rep = apply(dev, cfg, write="--apply" in argv)
    print(json.dumps(rep, ensure_ascii=False, indent=1, default=str))
    return 0 if rep.get("ok") else 1


if __name__ == "__main__":                       # pragma: no cover
    raise SystemExit(_main())
